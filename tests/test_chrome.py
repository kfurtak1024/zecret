"""Tests for the app's chrome: the title bar and what is not in it.

Required coverage:
    - The header shows "Zecret — <where you are>", following the screen.
    - The header cannot be expanded by clicking it, and carries no icon
      that opens anything.
    - The command palette is off: ctrl+p does nothing and the footer does
      not advertise it.
    - Every key the entry list advertises fits an 80-column terminal, and
      every screen wears the same compact footer.
    - Lock is one of the keys the bar advertises. Being able to find it is
      what the bar is for here, so this is not a styling detail.
    - A modal shows its own key. Without a footer of its own it let the
      entry list's bar show through, advertising eight keys that do
      nothing while a question has focus and none of the one that does.
    - Text lines up down the left edge of every screen. The gutter in
      app.tcss lines the borders up; what a reader follows is where the
      text starts, and Input and TextArea pad their insides by different
      amounts, so the two do not follow from each other.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from textual.widgets import Footer, Input, Label, ListView, TextArea

from zecret.app import ZecretApp
from zecret.models import Entry
from zecret.screens.entry_list import EntryListScreen
from zecret.screens.header import DiaryHeader
from zecret.screens.help import documented_bindings
from zecret.screens.unlock import UnlockScreen
from zecret.storage import DiaryFile

PASSWORD = "correct horse battery staple"
TODAY = dt.date.today()


# Argon2 at test cost, and no pause after a failed unlock: this suite
# opens diaries constantly (see tests/conftest.py).
pytestmark = pytest.mark.usefixtures("cheap_kdf")


@pytest.fixture(autouse=True)
def instant_failure_delay(monkeypatch):
    monkeypatch.setattr(UnlockScreen, "FAILED_ATTEMPT_DELAY", 0.0)


@pytest.fixture
def diary_path(tmp_path: Path) -> Path:
    path = tmp_path / "diary.enc"
    diary, key = DiaryFile.create_new(path, PASSWORD)
    diary.add_entry(Entry.new(TODAY, "A body"))
    diary.save(key)
    return path


async def unlock(pilot) -> None:
    pilot.app.screen.query_one("#password", Input).value = PASSWORD
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()


def header(app: ZecretApp) -> DiaryHeader:
    return app.screen.query_one(DiaryHeader)


def header_text(app: ZecretApp) -> str:
    return str(header(app).visual)


# --- what the header says --------------------------------------------------


async def test_header_shows_the_app_name_and_the_screen(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert header_text(app) == "Zecret — Locked"


async def test_header_follows_the_screen_you_are_on(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert header_text(app) == "Zecret — 1 entry"
        await pilot.press("slash")
        await pilot.pause()
        await pilot.pause()
        assert header_text(app) == "Zecret — Search"


# --- what the header will not do -------------------------------------------


async def test_clicking_the_header_does_nothing(diary_path):
    """Textual's own header expands to a taller variant on click. This one
    is a title, not a control."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        before = (header(app).size.height, header(app).classes, header_text(app))
        await pilot.click(header(app))
        await pilot.pause()
        assert (header(app).size.height, header(app).classes, header_text(app)) == before
        assert isinstance(app.screen, EntryListScreen), "nothing may open"


async def test_the_header_is_one_line(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert header(app).size.height == 1


async def test_the_header_carries_no_icon(diary_path):
    """The icon Textual docks left is what opened the command palette."""
    from textual.widgets._header import HeaderIcon

    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert not app.screen.query(HeaderIcon)


# --- no command palette ----------------------------------------------------


async def test_the_command_palette_is_disabled(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen)
        assert app.ENABLE_COMMAND_PALETTE is False


async def test_the_footer_does_not_advertise_the_palette(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        described = " ".join(key.description for key in app.screen.query("FooterKey"))
        assert "palette" not in described.lower()


# --- app-level guards ------------------------------------------------------


async def test_reaching_the_diary_before_unlocking_is_a_programming_error(diary_path):
    """Screens rely on app.unlocked being real. A half-open state would be
    a routing bug, so it raises rather than returning None."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        with pytest.raises(RuntimeError):
            _ = app.unlocked


# --- alignment -------------------------------------------------------------


#: Where text begins on every full-width screen, in columns from the left:
#: the 2-cell gutter, its border, and one cell inside that.
TEXT_COLUMN = 4


async def test_text_starts_at_the_same_column_on_every_screen(diary_path):
    """The search box used to sit one cell right of the results under it.
    Input pads its inside by two cells and TextArea by one, so bordering
    them at the same column is not the same as lining their text up --
    which is the edge a reader's eye actually runs down."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(NARROWEST, 20)) as pilot:
        await unlock(pilot)
        rows = app.screen.query_one("#entries", ListView).children
        assert rows[-1].query_one(Label).region.x == TEXT_COLUMN, "an entry row"

        await pilot.press("slash")
        await pilot.pause()
        app.screen.query_one("#query", Input).value = "A"
        await pilot.pause()
        await pilot.pause()
        assert app.screen.query_one("#query", Input).content_region.x == TEXT_COLUMN, "the query"
        results = app.screen.query_one("#results", ListView).children
        assert results[-1].query_one(Label).region.x == TEXT_COLUMN, "a result row"

        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.query_one("#body", TextArea).content_region.x == TEXT_COLUMN, "the editor"


# --- the key bar -----------------------------------------------------------


#: The narrowest terminal Zecret is expected to be usable in. Eighty is not
#: an arbitrary round number -- it is the width a terminal defaults to.
NARROWEST = 80


def footer_text(app: ZecretApp) -> str:
    """The bottom line of the screen, as rendered."""
    strips = app.screen._compositor.render_strips()
    return "".join(segment.text for segment in strips[-1])


async def test_every_advertised_key_fits_an_eighty_column_terminal(diary_path):
    """The entry list advertises more keys than any other screen, and the
    roomy spelling of Textual's footer needs 102 columns to lay them out.
    At 80 it stopped mid-word -- "? Hel" -- and dropped Quit entirely, which
    is how two keys got added without anyone seeing the bar overflow.
    """
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(NARROWEST, 16)) as pilot:
        await unlock(pilot)
        assert isinstance(app.screen, EntryListScreen)
        bar = footer_text(app)

        # Asked of the app rather than read off the binding: the footer
        # renders a chord the way Textual spells it, so ctrl+l is "^l"
        # there and comparing against the raw key name would look for
        # something the bar never contained.
        advertised = [
            f"{app.get_key_display(binding)} {binding.description}"
            for binding in documented_bindings(EntryListScreen.BINDINGS)
            if binding.show
        ]
        missing = [entry for entry in advertised if entry not in bar]
        assert not missing, (
            f"the footer at {NARROWEST} columns does not fully show: {missing}\ngot: {bar!r}"
        )


async def test_the_key_bar_advertises_lock(diary_path):
    """Hidden, this key was reachable only through '?'. Someone stepping
    away who cannot find it quits instead, or leaves the diary open on the
    screen -- which makes its place in the bar a security decision rather
    than a matter of taste."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(NARROWEST, 16)) as pilot:
        await unlock(pilot)
        assert isinstance(app.screen, EntryListScreen)
        assert "^l Lock" in footer_text(app)


async def test_a_modal_advertises_its_own_key_and_not_the_list_behind_it(diary_path):
    """A ModalScreen renders over the screen it was opened from, so with no
    footer of its own the list's bar stayed on show -- every key on it dead
    while the question had focus, and 'esc Cancel' displayed nowhere
    despite being declared show=True."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(NARROWEST, 20)) as pilot:
        await unlock(pilot)
        for key in ("a", "d"):
            await pilot.press(key)
            await pilot.pause()
            await pilot.pause()
            bar = footer_text(app)
            assert "esc Cancel" in bar, f"{key!r} opened a modal with no key of its own: {bar!r}"
            assert "n Today" not in bar, f"{key!r} left the list's dead keys on show: {bar!r}"
            await pilot.press("escape")
            await pilot.pause()
            await pilot.pause()


async def test_the_footer_is_compact_on_every_screen(diary_path):
    """One screen quietly using the roomy footer would look like a bug on
    the way in and out of it."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(NARROWEST, 20)) as pilot:
        await unlock(pilot)
        for key in ("n", "escape", "slash", "escape", "s", "escape", "a", "escape", "d"):
            await pilot.press(key)
            await pilot.pause()
            await pilot.pause()
            for footer in app.screen.query(Footer):
                assert footer.compact, f"{type(app.screen).__name__} has a roomy footer"
