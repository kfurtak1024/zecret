"""Tests for locking: by hand, and after a spell of quiet.

An unlocked Zecret holds every entry decrypted in memory and shows them to
whoever is at the terminal. Locking is what makes walking away survivable,
so what it forgets matters as much as what it shows.

Required coverage:
    - 'L' locks: the diary and key are gone from the app, the entry list is
      gone from the screen, and the lock screen is asking for a password.
    - Unlocking again works, and comes back to the entry list.
    - The idle timer locks once the wait has passed, and does not before.
    - Typing puts the wait back to the start.
    - A half-written entry holds the lock off -- and keeps holding it off
      after the writer comes back, rather than locking the instant they
      save.
    - A timeout of zero never locks.
    - Locking is scheduled at all, rather than only ever called by hand.
    - Locking from search, and from an entry opened through search, tears
      everything down without a screen underneath trying to redraw itself
      from a diary that is no longer open.

Elapsed time is faked by moving app.last_activity into the past, and the
lock check is called directly. A test that actually waited fifteen minutes
would be no more convincing and considerably less welcome.
"""

from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

import pytest
from textual.widgets import Input, TextArea

import zecret.app
from zecret.app import ZecretApp
from zecret.models import Entry
from zecret.screens.editor import EditorScreen
from zecret.screens.entry_list import EntryListScreen
from zecret.screens.search import SearchScreen
from zecret.screens.unlock import UnlockScreen
from zecret.storage import DiaryFile

PASSWORD = "correct horse battery staple"

TODAY = dt.date.today()
YESTERDAY = TODAY - dt.timedelta(days=1)

pytestmark = pytest.mark.usefixtures("cheap_kdf")


@pytest.fixture(autouse=True)
def instant_failure_delay(monkeypatch):
    monkeypatch.setattr(UnlockScreen, "FAILED_ATTEMPT_DELAY", 0.0)


@pytest.fixture
def diary_path(tmp_path: Path) -> Path:
    path = tmp_path / "diary.enc"
    diary, key = DiaryFile.create_new(path, PASSWORD)
    diary.add_entry(Entry.new(YESTERDAY, "Something private"))
    diary.save(key)
    return path


async def unlock(pilot) -> None:
    pilot.app.screen.query_one("#password", Input).focus()
    pilot.app.screen.query_one("#password", Input).value = PASSWORD
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()


def go_quiet(app: ZecretApp, minutes: float) -> None:
    """Pretend nothing has happened for `minutes`."""
    app.last_activity = time.monotonic() - minutes * 60


# --- locking by hand -------------------------------------------------------


async def test_shift_l_locks_the_diary(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert isinstance(app.screen, EntryListScreen)

        await pilot.press("L")
        await pilot.pause()
        await pilot.pause()

        assert app.diary is None, "the diary must not be left in memory"
        assert app.key is None, "the key must not be left in memory"
        assert isinstance(app.screen, UnlockScreen)
        assert not app.is_unlocked


async def test_locking_takes_the_entries_off_the_screen(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("L")
        await pilot.pause()
        await pilot.pause()

        assert not app.query(EntryListScreen), "the list must not be left behind the lock screen"


async def test_the_diary_can_be_unlocked_again(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("L")
        await pilot.pause()
        await pilot.pause()

        await unlock(pilot)
        assert isinstance(app.screen, EntryListScreen)
        assert set(app.diary.entries) == {YESTERDAY}


async def test_locking_an_already_locked_app_does_nothing(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, UnlockScreen)
        app.lock()
        await pilot.pause()
        assert isinstance(app.screen, UnlockScreen), "no second lock screen"


# --- locking on its own ----------------------------------------------------


async def test_the_diary_locks_after_the_wait(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        app.config.lock_after_minutes = 15

        go_quiet(app, 15)
        app.lock_if_idle()
        await pilot.pause()
        await pilot.pause()

        assert isinstance(app.screen, UnlockScreen)
        assert app.diary is None


async def test_the_diary_stays_open_before_the_wait_is_up(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        app.config.lock_after_minutes = 15

        go_quiet(app, 14)
        app.lock_if_idle()
        await pilot.pause()

        assert isinstance(app.screen, EntryListScreen)
        assert app.is_unlocked


async def test_typing_puts_the_wait_back_to_the_start(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        app.config.lock_after_minutes = 15

        go_quiet(app, 14)
        await pilot.press("down")
        await pilot.pause()
        app.lock_if_idle()
        await pilot.pause()

        assert app.is_unlocked, "a keypress should have reset the clock"


async def test_a_timeout_of_zero_never_locks(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        app.config.lock_after_minutes = 0

        go_quiet(app, 60 * 24)
        app.lock_if_idle()
        await pilot.pause()

        assert app.is_unlocked


async def test_the_lock_check_is_actually_scheduled(diary_path):
    """Everything else here calls lock_if_idle() by hand. Without this, all
    of it would still pass on an app that never runs the timer."""
    calls: list[int] = []

    class Counted(ZecretApp):
        # Absolute, because CSS_PATH is resolved relative to the module the
        # App subclass is defined in -- which for this one is tests/.
        CSS_PATH = str(Path(zecret.app.__file__).parent / "app.tcss")
        IDLE_CHECK_SECONDS = 0.01

        def lock_if_idle(self) -> None:
            calls.append(1)

    app = Counted(diary_path=diary_path)
    async with app.run_test() as pilot:
        await pilot.pause(0.05)
    assert calls, "the idle check was never scheduled"


# --- unsaved work ----------------------------------------------------------


async def test_a_half_written_entry_holds_the_lock_off(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        app.config.lock_after_minutes = 15

        await pilot.press("n")
        await pilot.pause()
        app.screen.query_one("#body", TextArea).text = "Half a thought"
        await pilot.pause()

        go_quiet(app, 60)
        app.lock_if_idle()
        await pilot.pause()

        assert isinstance(app.screen, EditorScreen)
        assert app.screen.body_text == "Half a thought", "the typing must survive"


async def test_a_modal_over_a_half_written_entry_still_holds_it_off(diary_path):
    """The editor is no longer the top screen, but the text is still there."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        app.config.lock_after_minutes = 15

        await pilot.press("n")
        await pilot.pause()
        app.screen.query_one("#body", TextArea).text = "Half a thought"
        await pilot.pause()
        await pilot.press("escape")  # the discard-confirmation modal
        await pilot.pause()

        go_quiet(app, 60)
        app.lock_if_idle()
        await pilot.pause()

        assert app.is_unlocked
        assert any(isinstance(screen, EditorScreen) for screen in app.screen_stack)


async def test_the_wait_starts_over_once_the_entry_is_saved(diary_path):
    """Holding the lock off is not the same as postponing it: locking the
    instant someone saves would be the same ambush a beat later."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        app.config.lock_after_minutes = 15

        await pilot.press("n")
        await pilot.pause()
        app.screen.query_one("#body", TextArea).text = "A whole thought"
        await pilot.pause()

        go_quiet(app, 60)
        app.lock_if_idle()  # held off, and the clock reset
        await pilot.pause()

        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()

        app.lock_if_idle()
        await pilot.pause()
        assert app.is_unlocked, "saving must not be immediately followed by a lock"
        assert app.diary.entry_for(TODAY).body == "A whole thought"


async def test_an_entry_left_untouched_does_not_hold_the_lock_off(diary_path):
    """Only unsaved *changes* count. Sitting in an entry you have not typed
    into is no different from sitting in the list."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        app.config.lock_after_minutes = 15

        await pilot.press("enter")  # open yesterday, change nothing
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)

        go_quiet(app, 15)
        app.lock_if_idle()
        await pilot.pause()
        await pilot.pause()

        assert isinstance(app.screen, UnlockScreen)


async def test_locking_from_search_tears_it_down_cleanly(diary_path):
    """Search rebuilds its results as it resumes, and locking pops it --
    so it is resumed on the way out, with no diary left to filter."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        app.config.lock_after_minutes = 15

        await pilot.press("slash")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, SearchScreen)

        go_quiet(app, 15)
        app.lock_if_idle()
        await pilot.pause()
        await pilot.pause()

        assert isinstance(app.screen, UnlockScreen)
        assert app.diary is None
        assert not app.query(SearchScreen)


async def test_locking_from_an_entry_opened_through_search(diary_path):
    """The flow that needs SearchScreen's own guard: locking pops the
    editor, which resumes search underneath it, which would go looking for
    a diary that is on its way out."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        app.config.lock_after_minutes = 15

        await pilot.press("slash")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("enter")  # focus the results
        await pilot.pause()
        await pilot.press("enter")  # open the highlighted day
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        assert [type(screen).__name__ for screen in app.screen_stack] == [
            "Screen",
            "EntryListScreen",
            "SearchScreen",
            "EditorScreen",
        ]

        go_quiet(app, 15)
        app.lock_if_idle()
        await pilot.pause()
        await pilot.pause()

        assert isinstance(app.screen, UnlockScreen)
        assert app.diary is None
