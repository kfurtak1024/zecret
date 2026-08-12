"""Tests for EntryListScreen: listing, selection, and delete.

Required coverage:
    - Unlocking routes to the entry list.
    - Entries render newest-first, with an empty state when there are none.
    - Delete asks for confirmation first; cancelling changes nothing.
    - Confirmed delete removes the entry from memory AND from disk, and
      leaves the other entries intact.
    - The list refreshes from app.diary whenever the screen is resumed.

Navigation to the editor/search/settings is asserted only as far as it
exists at build-order step 5.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from textual.widgets import Input, Label, ListView

from zecret.app import ZecretApp
from zecret.models import Entry
from zecret.screens.entry_list import EMPTY_MESSAGE, UNTITLED, ConfirmScreen, EntryListScreen
from zecret.screens.unlock import UnlockScreen
from zecret.storage import DiaryFile

PASSWORD = "correct horse battery staple"


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


def dated(title: str, minutes_ago: int) -> Entry:
    """An entry with a controlled created_at, for ordering assertions."""
    entry = Entry.new(title, f"Body of {title}")
    return Entry(
        id=entry.id,
        title=entry.title,
        body=entry.body,
        created_at=entry.created_at - timedelta(minutes=minutes_ago),
        updated_at=entry.updated_at,
    )


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


async def test_entries_render_newest_first(diary_path):
    seed(diary_path, dated("Oldest", 120), dated("Newest", 1), dated("Middle", 60))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        labels = row_labels(app)
        assert [label.split("  ")[-1] for label in labels] == ["Newest", "Middle", "Oldest"]


async def test_rows_show_the_entry_timestamp(diary_path):
    entry = dated("A title", 0)
    seed(diary_path, entry)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        expected = entry.created_at.astimezone().strftime("%Y-%m-%d %H:%M")
        assert row_labels(app)[0].startswith(expected)


async def test_untitled_entries_are_labelled(diary_path):
    seed(diary_path, Entry.new("", "Body only"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert UNTITLED in row_labels(app)[0]


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
    seed(diary_path, Entry.new("A title", "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert app.screen.query_one("#entries-empty", Label).display is False


async def test_first_row_is_selected_by_default(diary_path):
    seed(diary_path, dated("Older", 60), dated("Newer", 1))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert app.screen.selected_entry is not None
        assert app.screen.selected_entry.title == "Newer"


async def test_arrow_keys_move_the_selection(diary_path):
    seed(diary_path, dated("Older", 60), dated("Newer", 1))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("down")
        await pilot.pause()
        assert app.screen.selected_entry.title == "Older"


# --- delete ----------------------------------------------------------------


async def test_delete_asks_for_confirmation_first(diary_path):
    seed(diary_path, Entry.new("Keep me", "Body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("d")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        assert app.diary is not None
        assert len(app.diary.entries) == 1, "nothing may be deleted before confirming"


async def test_cancelling_the_confirmation_keeps_the_entry(diary_path):
    entry = Entry.new("Keep me", "Body")
    seed(diary_path, entry)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.diary.entries == {entry.id: entry}
        assert row_labels(app) == [f"{entry.created_at.astimezone():%Y-%m-%d %H:%M}  Keep me"]

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entries == {entry.id: entry}


async def test_confirmed_delete_removes_the_entry_everywhere(diary_path):
    doomed = dated("Delete me", 1)
    kept = dated("Keep me", 60)
    seed(diary_path, doomed, kept)

    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("d")
        await pilot.pause()
        await pilot.click("#confirm-yes")
        await pilot.pause()
        await pilot.pause()

        assert set(app.diary.entries) == {kept.id}
        assert [label.split("  ")[-1] for label in row_labels(app)] == ["Keep me"]

    # Persisted, not just dropped from memory.
    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert set(reopened.entries) == {kept.id}


async def test_deleting_the_last_entry_restores_the_empty_state(diary_path):
    seed(diary_path, Entry.new("Only one", "Body"))
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
    entry = Entry.new("Keep me", "Body")
    seed(diary_path, entry)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert app.diary.entries == {entry.id: entry}


# --- refresh on resume -----------------------------------------------------


async def test_list_refreshes_when_the_screen_resumes(diary_path):
    """Entries added while another screen was in front must appear on
    return -- this is the hook the editor and search rely on."""
    seed(diary_path, Entry.new("First", "Body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        entry_list = app.screen

        added = Entry.new("Added elsewhere", "Body")
        app.diary.add_entry(added)
        app.diary.save(app.key)

        # Stand in for returning from the editor.
        await app.push_screen(ConfirmScreen("dismiss me"))
        await pilot.pause()
        app.pop_screen()
        await pilot.pause()
        await pilot.pause()

        assert app.screen is entry_list
        assert "Added elsewhere" in " ".join(row_labels(app))
