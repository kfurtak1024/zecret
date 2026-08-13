"""Tests for EntryListScreen: listing days, selection, and delete.

Required coverage:
    - Unlocking routes to the entry list.
    - Days render most-recent-first, with an empty state when there are
      none.
    - 'g' offers another day to write about and opens the editor on it;
      backing out of the prompt changes nothing.
    - Delete asks for confirmation first; cancelling changes nothing.
    - Confirmed delete removes the entry from memory AND from disk, and
      leaves the other entries intact.
    - The list refreshes from app.diary whenever the screen is resumed.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from textual.widgets import Input, Label, ListView, MaskedInput

from zecret.app import ZecretApp
from zecret.models import Entry
from zecret.screens.base import EMPTY_BODY, format_day
from zecret.screens.date_prompt import DatePromptScreen
from zecret.screens.editor import EditorScreen
from zecret.screens.entry_list import EMPTY_MESSAGE, ConfirmScreen, EntryListScreen
from zecret.screens.unlock import UnlockScreen
from zecret.storage import DiaryFile

PASSWORD = "correct horse battery staple"

TODAY = dt.date.today()
YESTERDAY = TODAY - dt.timedelta(days=1)
LAST_WEEK = TODAY - dt.timedelta(days=7)
LAST_YEAR = TODAY - dt.timedelta(days=365)


@pytest.fixture(autouse=True)
def instant_failure_delay(monkeypatch):
    monkeypatch.setattr(UnlockScreen, "FAILED_ATTEMPT_DELAY", 0.0)


@pytest.fixture
def diary_path(tmp_path: Path) -> Path:
    return tmp_path / "diary.enc"


def seed(path: Path, *entries: Entry) -> None:
    diary, key = DiaryFile.create_new(path, PASSWORD)
    for entry in entries:
        diary.add_entry(entry)
    diary.save(key)


async def unlock(pilot) -> None:
    """Get past UnlockScreen to the entry list."""
    pilot.app.screen.query_one("#password", Input).value = PASSWORD
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()


def row_labels(app: ZecretApp) -> list[str]:
    return [
        str(item.query_one(Label).content)
        for item in app.screen.query_one("#entries", ListView).children
    ]


# --- routing and rendering -------------------------------------------------


async def test_unlocking_routes_to_the_entry_list(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert isinstance(app.screen, EntryListScreen)


async def test_days_render_most_recent_first(diary_path):
    seed(
        diary_path,
        Entry.new(LAST_YEAR, "Oldest"),
        Entry.new(YESTERDAY, "Newest"),
        Entry.new(LAST_WEEK, "Middle"),
    )
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert [label.split("   ")[-1] for label in row_labels(app)] == [
            "Newest",
            "Middle",
            "Oldest",
        ]


async def test_rows_show_the_day_then_a_glimpse_of_the_text(diary_path):
    seed(diary_path, Entry.new(YESTERDAY, "First line\nsecond line"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert row_labels(app) == [f"{format_day(YESTERDAY)}   First line"]


async def test_an_entry_with_no_text_still_shows_its_day(diary_path):
    seed(diary_path, Entry.new(YESTERDAY, ""))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert row_labels(app) == [f"{format_day(YESTERDAY)}   {EMPTY_BODY}"]


async def test_empty_diary_shows_the_empty_state(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        empty = app.screen.query_one("#entries-empty", Label)
        assert empty.display is True
        assert str(empty.content) == EMPTY_MESSAGE
        assert row_labels(app) == []


async def test_populated_diary_hides_the_empty_state(diary_path):
    seed(diary_path, Entry.new(TODAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert app.screen.query_one("#entries-empty", Label).display is False


async def test_first_row_is_selected_by_default(diary_path):
    seed(diary_path, Entry.new(LAST_WEEK, "Older"), Entry.new(YESTERDAY, "Newer"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert app.screen.selected_entry is not None
        assert app.screen.selected_entry.date == YESTERDAY


async def test_q_quits(diary_path):
    """The footer offers it, so it has to work: a binding whose action is
    not defined on the screen silently does nothing."""
    seed(diary_path, Entry.new(TODAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("q")
        await pilot.pause()
        assert app._exit is True


async def test_arrow_keys_move_the_selection(diary_path):
    seed(diary_path, Entry.new(LAST_WEEK, "Older"), Entry.new(YESTERDAY, "Newer"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("down")
        await pilot.pause()
        assert app.screen.selected_entry.date == LAST_WEEK


# --- writing another day ---------------------------------------------------


async def test_g_opens_the_date_prompt(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await pilot.press("g")  # ignored: still on the unlock screen
        await unlock(pilot)
        await pilot.press("g")
        await pilot.pause()
        assert isinstance(app.screen, DatePromptScreen)


async def test_choosing_a_day_opens_the_editor_on_it(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("g")
        await pilot.pause()
        app.screen.query_one("#date", MaskedInput).value = LAST_WEEK.isoformat()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        assert app.screen.date == LAST_WEEK


async def test_choosing_a_day_that_is_already_written_opens_its_entry(diary_path):
    seed(diary_path, Entry.new(LAST_WEEK, "What happened that day."))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("g")
        await pilot.pause()
        app.screen.query_one("#date", MaskedInput).value = LAST_WEEK.isoformat()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert app.screen.creating is False
        assert app.screen.body_text == "What happened that day."


async def test_backing_out_of_the_date_prompt_returns_to_the_list(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("g")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen)
        assert app.diary.entries == {}


# --- delete ----------------------------------------------------------------


async def test_delete_asks_for_confirmation_first(diary_path):
    seed(diary_path, Entry.new(YESTERDAY, "Keep me"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        assert app.diary is not None
        assert len(app.diary.entries) == 1, "nothing may be deleted before confirming"


async def test_the_confirmation_names_the_day(diary_path):
    seed(diary_path, Entry.new(YESTERDAY, "Keep me"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("d")
        await pilot.pause()
        question = str(app.screen.query_one("#confirm-question", Label).content)
        assert format_day(YESTERDAY) in question


async def test_cancelling_the_confirmation_keeps_the_entry(diary_path):
    entry = Entry.new(YESTERDAY, "Keep me")
    seed(diary_path, entry)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.diary.entries == {YESTERDAY: entry}
        assert row_labels(app) == [f"{format_day(YESTERDAY)}   Keep me"]

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entries == {YESTERDAY: entry}


async def test_confirmed_delete_removes_the_entry_everywhere(diary_path):
    seed(diary_path, Entry.new(YESTERDAY, "Delete me"), Entry.new(LAST_WEEK, "Keep me"))

    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("d")
        await pilot.pause()
        await pilot.click("#confirm-yes")
        await pilot.pause()
        await pilot.pause()

        assert set(app.diary.entries) == {LAST_WEEK}
        assert [label.split("   ")[-1] for label in row_labels(app)] == ["Keep me"]

    # Persisted, not just dropped from memory.
    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert set(reopened.entries) == {LAST_WEEK}


async def test_deleting_the_last_entry_restores_the_empty_state(diary_path):
    seed(diary_path, Entry.new(TODAY, "Only one"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("d")
        await pilot.pause()
        await pilot.click("#confirm-yes")
        await pilot.pause()
        await pilot.pause()
        assert app.screen.query_one("#entries-empty", Label).display is True


async def test_delete_on_an_empty_list_does_nothing(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen), "no modal for nothing to delete"


async def test_confirmation_defaults_to_cancel(diary_path):
    """A stray Enter on the modal must not delete anything."""
    entry = Entry.new(YESTERDAY, "Keep me")
    seed(diary_path, entry)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert app.diary.entries == {YESTERDAY: entry}


async def test_a_failed_delete_keeps_the_entry_visible(diary_path, monkeypatch):
    """The file still holds it, so the list must not claim otherwise."""
    entry = Entry.new(YESTERDAY, "Keep me")
    seed(diary_path, entry)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)

        def boom(*_args, **_kwargs):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(type(app.diary), "save", boom)
        await pilot.press("d")
        await pilot.pause()
        await pilot.click("#confirm-yes")
        await pilot.pause()
        await pilot.pause()

        assert app.diary.entries == {YESTERDAY: entry}
        assert row_labels(app) == [f"{format_day(YESTERDAY)}   Keep me"]


# --- refresh on resume -----------------------------------------------------


async def test_list_refreshes_when_the_screen_resumes(diary_path):
    """Entries added while another screen was in front must appear on
    return -- this is the hook the editor and search rely on."""
    seed(diary_path, Entry.new(YESTERDAY, "First"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        entry_list = app.screen

        app.diary.add_entry(Entry.new(LAST_WEEK, "Added elsewhere"))
        app.diary.save(app.key)

        # Stand in for returning from the editor.
        await app.push_screen(ConfirmScreen("dismiss me"))
        await pilot.pause()
        app.pop_screen()
        await pilot.pause()
        await pilot.pause()

        assert app.screen is entry_list
        assert "Added elsewhere" in " ".join(row_labels(app))
