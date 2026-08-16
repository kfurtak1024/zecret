"""Tests that a long diary stays usable.

Zecret is meant to be kept for years, so the screens that draw a list have
to cope with years of entries. They did not: both rebuilt their ListView by
awaiting one append per row, and every append re-laid-out every row already
mounted. That is quadratic, and it was not slow in a way anyone would
notice at ten entries -- at ten years it took over a minute, on *every*
return to the screen, because the rebuild runs on resume.

Required coverage:
    - A diary of several years redraws the entry list in about a second,
      not in tens of seconds.
    - The same for the search results, which rebuild on every keystroke.

This is a stopwatch, which is not the usual way to pin down complexity --
the tidier test compares the time at two sizes and asserts the curve is not
quadratic. That was tried and does not work here: below a couple of
thousand rows the per-append cost has not yet come to dominate, so the
broken code grew by 6.8x over a 4x span where the fixed code grows by 5x,
and no threshold separates them. The blow-up is real but it arrives late,
so the honest test is to build a diary large enough to feel it and put a
ceiling on the clock.

A stopwatch measures the machine as well as the code, and CEILING is set
for the slowest machine that runs it rather than the fastest. A GitHub
runner is about 4x slower than a development one -- measured, not guessed:
1.35s/1.72s here against 5.34s/6.02s there -- which sailed past a ceiling
of 4.0s and failed a build for the one reason this test promises not to
fail for. So the ceiling is now centred on the runner: the regression it
guards against costs about 6.8x, which is ~41s where a healthy rebuild is
~6s, and 15.0 sits between them in the log sense.

The cost is a blind spot on a fast machine, where the same regression
lands around 12s and passes. That is tolerable only because this test is
marked `slow` and deselected from a local run anyway: CI is where it
actually stands guard. If you are chasing this by hand, lower CEILING for
the duration rather than trusting a local pass.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from textual.widgets import Input

from zecret.app import ZecretApp
from zecret.models import Entry
from zecret.screens.search import SearchScreen
from zecret.screens.unlock import UnlockScreen
from zecret.storage import DiaryFile

PASSWORD = "correct horse battery staple"

#: Four years of writing every day. Past the point where mounting rows one
#: at a time starts to hurt, and still quick enough to sit in a suite meant
#: to be run constantly.
ENTRIES = 1500

#: Seconds, sized for CI rather than for a development machine -- see the
#: module docstring. Mounting the rows in one pass takes about 1.3s on a
#: fast machine and about 6s on a GitHub runner; mounting them one at a
#: time took 8.9s and would take ~41s. Halfway between in the log sense.
CEILING = 15.0

pytestmark = [
    pytest.mark.usefixtures("cheap_kdf"),
    # Deselect with `-m "not slow"`: this builds a thousand entries twice
    # and is the one test here that is not near-instant.
    pytest.mark.slow,
]


@pytest.fixture(autouse=True)
def instant_failure_delay(monkeypatch):
    monkeypatch.setattr(UnlockScreen, "FAILED_ATTEMPT_DELAY", 0.0)


def seed(path: Path, count: int) -> Path:
    """A diary of `count` consecutive days, which is `count` rows plus a
    heading for every month they span."""
    diary, key = DiaryFile.create_new(path, PASSWORD)
    first = dt.date(2010, 1, 1)
    for day in range(count):
        diary.add_entry(Entry.new(first + dt.timedelta(days=day), f"Entry number {day}"))
    diary.save(key)
    return path


async def timed(rebuild: Callable[[], Awaitable[None]]) -> float:
    """Seconds for one run of `rebuild`.

    Each screen has already rebuilt once by the time this is called -- the
    entry list on unlock, the results on opening search -- so nothing here
    is paying to warm anything up.
    """
    started = time.perf_counter()
    await rebuild()
    return time.perf_counter() - started


async def rebuild_seconds(path: Path) -> dict[str, float]:
    """How long each list screen takes to rebuild over the diary at `path`.

    Both are measured from one run of the app, since getting a screen on
    the air costs more than the rebuild being timed. The rebuild coroutine
    is called directly rather than through a keypress, so what is measured
    is the list being built and not the screen being routed to.
    """
    app = ZecretApp(diary_path=path)
    async with app.run_test() as pilot:
        pilot.app.screen.query_one("#password", Input).value = PASSWORD
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        entry_list = await timed(app.screen.refresh_entries)

        await pilot.press("slash")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, SearchScreen)
        search = await timed(app.screen.refresh_results)

    return {"entry list": entry_list, "search": search}


async def test_a_long_diary_still_redraws_quickly(tmp_path: Path):
    seconds = await rebuild_seconds(seed(tmp_path / "long.enc", ENTRIES))

    too_slow = {screen: taken for screen, taken in seconds.items() if taken >= CEILING}
    assert not too_slow, (
        f"{ENTRIES} entries took over {CEILING:.0f}s to draw: {pretty(too_slow)}. "
        f"This runs on every return to the screen, so that is the wait after "
        f"every entry read or written. It means rows are being mounted one at "
        f"a time again -- mount them in one pass. (All screens: "
        f"{pretty(seconds)}.)"
    )


def pretty(times: dict[str, float]) -> str:
    return ", ".join(f"{screen} {seconds:.2f}s" for screen, seconds in sorted(times.items()))
