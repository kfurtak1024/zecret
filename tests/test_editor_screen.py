"""Tests for EditorScreen: creating and editing entries.

Required coverage:
    - 'n' from the list opens an empty editor; Enter opens the selected
      entry prefilled.
    - Saving a new entry persists it to disk and shows it in the list.
    - Saving an edit updates the entry in place: same id and created_at,
      refreshed updated_at, and no other entry rewritten.
    - Backing out with unsaved changes asks before discarding; backing out
      unchanged leaves immediately.
    - An entry with neither title nor body is refused.
    - A save that fails keeps the user on the screen with their text.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Input, Label, ListView, TextArea

from zecret.app import ZecretApp
from zecret.models import Entry
from zecret.screens.confirm import ConfirmScreen
from zecret.screens.editor import EMPTY_ENTRY, EditorScreen
from zecret.screens.entry_list import EntryListScreen
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


async def unlock(pilot) -> None:
    pilot.app.screen.query_one("#password", Input).value = PASSWORD
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()


async def type_entry(pilot, title: str, body: str) -> None:
    """Fill the open editor's fields."""
    pilot.app.screen.query_one("#title", Input).value = title
    pilot.app.screen.query_one("#body", TextArea).text = body
    await pilot.pause()


def row_labels(app: ZecretApp) -> list[str]:
    return [
        str(item.query_one(Label).content)
        for item in app.screen.query_one("#entries", ListView).children
    ]


# --- opening the editor ----------------------------------------------------


async def test_n_opens_an_empty_editor(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        assert app.screen.creating is True
        assert app.screen.title_text == ""
        assert app.screen.body_text == ""


async def test_enter_opens_the_selected_entry_prefilled(diary_path):
    entry = Entry.new("A title", "A body\nover two lines")
    seed(diary_path, entry)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        assert app.screen.creating is False
        assert app.screen.title_text == "A title"
        assert app.screen.body_text == "A body\nover two lines"


# --- creating --------------------------------------------------------------


async def test_saving_a_new_entry_persists_it(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        await type_entry(pilot, "Morning walk", "It was cold.")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()

        assert isinstance(app.screen, EntryListScreen), "should return to the list"
        assert len(app.diary.entries) == 1

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    saved = next(iter(reopened.entries.values()))
    assert saved.title == "Morning walk"
    assert saved.body == "It was cold."


async def test_a_new_entry_appears_in_the_list(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        await type_entry(pilot, "Morning walk", "It was cold.")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()
        assert "Morning walk" in " ".join(row_labels(app))


async def test_an_entry_with_only_a_body_is_allowed(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        await type_entry(pilot, "", "Just some thoughts.")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()
        assert len(app.diary.entries) == 1


async def test_a_wholly_empty_entry_is_refused(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen), "must not leave"
        assert str(app.screen.query_one("#editor-error", Label).content) == EMPTY_ENTRY
        assert app.diary.entries == {}


# --- editing ---------------------------------------------------------------


async def test_saving_an_edit_updates_the_entry_in_place(diary_path):
    entry = Entry.new("Original", "Original body")
    seed(diary_path, entry)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_entry(pilot, "Edited", "Edited body")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()
        assert len(app.diary.entries) == 1, "an edit must not add a second entry"

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    saved = reopened.entries[entry.id]
    assert saved.title == "Edited"
    assert saved.body == "Edited body"
    assert saved.id == entry.id
    assert saved.created_at == entry.created_at
    assert saved.updated_at > entry.updated_at


async def test_editing_one_entry_leaves_others_ciphertext_alone(diary_path):
    """The UI path must preserve the per-entry independence that storage
    guarantees (CLAUDE.md requirement 6)."""
    import json

    edited = Entry.new("Edit me", "Body")
    untouched = Entry.new("Leave me", "Body")
    seed(diary_path, edited, untouched)

    def ciphertexts() -> dict[str, str]:
        document = json.loads(diary_path.read_bytes())
        return {rec["id"]: rec["ciphertext"] for rec in document["entries"]}

    before = ciphertexts()

    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        # Select "Edit me" wherever it landed in the list.
        while app.screen.selected_entry.id != edited.id:
            await pilot.press("down")
            await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await type_entry(pilot, "Edited", "Edited body")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()

    after = ciphertexts()
    assert after[str(untouched.id)] == before[str(untouched.id)]
    assert after[str(edited.id)] != before[str(edited.id)]


# --- backing out -----------------------------------------------------------


async def test_escape_with_no_changes_returns_immediately(diary_path):
    seed(diary_path, Entry.new("A title", "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen)


async def test_escape_with_unsaved_changes_asks_first(diary_path):
    seed(diary_path, Entry.new("A title", "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_entry(pilot, "Changed", "A body")
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)


async def test_cancelling_the_discard_keeps_you_editing(diary_path):
    seed(diary_path, Entry.new("A title", "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_entry(pilot, "Changed", "A body")
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("escape")  # dismisses the modal as "cancel"
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        assert app.screen.title_text == "Changed", "the edit must survive"


async def test_confirming_the_discard_drops_the_changes(diary_path):
    entry = Entry.new("A title", "A body")
    seed(diary_path, entry)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_entry(pilot, "Changed", "A body")
        await pilot.press("escape")
        await pilot.pause()
        await pilot.click("#confirm-yes")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen)
        assert app.diary.entries == {entry.id: entry}, "nothing may be persisted"

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entries[entry.id].title == "A title"


async def test_a_new_empty_editor_backs_out_without_asking(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen)


# --- save failures ---------------------------------------------------------


async def test_a_failed_save_keeps_you_on_the_editor(diary_path, monkeypatch):
    """Losing the text because the disk was full would be the worst
    possible outcome here."""
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        await type_entry(pilot, "Important", "Do not lose this.")

        def boom(*_args, **_kwargs):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(type(app.diary), "save", boom)
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert isinstance(app.screen, EditorScreen)
        assert app.screen.body_text == "Do not lose this."
        assert "No space left" in str(app.screen.query_one("#editor-error", Label).content)
