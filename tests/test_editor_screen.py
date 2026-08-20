"""Tests for EditorScreen: writing and revising a day's entry.

Required coverage:
    - 'n' from the list opens today: empty if the day is unwritten,
      prefilled if it is not -- never a second entry for the same day.
    - Enter opens the selected day prefilled.
    - Saving a new entry persists it to disk under its date and shows it
      in the list, and says so on the way back -- a revised day looks no
      different in the list once you are there.
    - A refused save says nothing about having saved.
    - The message does not follow you into the next thing you open. A
      notification is the app's and outlives the screen that raised it, so
      "Saved." used to reappear over the empty editor opened next.
    - Saving an edit updates the entry in place: same date and created_at,
      refreshed updated_at, and no other entry rewritten.
    - Backing out with unsaved changes asks before discarding; backing out
      unchanged leaves immediately.
    - Quitting with unsaved changes asks too. ctrl+q is Textual's own
      app-wide binding and used to exit on the spot, throwing the text away
      by the one route that never prompted and never appeared in the key
      bar; both spellings of quit now go through the same question.
    - An empty entry is refused.
    - A save that fails keeps the user on the screen with their text, and
      leaves the diary able to retry.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from textual.widgets import Input, Label, ListView, TextArea

from zecret.app import ZecretApp
from zecret.models import Entry
from zecret.screens.base import DIARY_CHANGED, format_day_long
from zecret.screens.confirm import ConfirmScreen
from zecret.screens.editor import EMPTY_ENTRY, SAVED, EditorScreen
from zecret.screens.entry_list import EntryListScreen
from zecret.screens.unlock import UnlockScreen
from zecret.storage import DiaryFile

PASSWORD = "correct horse battery staple"

TODAY = dt.date.today()
YESTERDAY = TODAY - dt.timedelta(days=1)
LAST_WEEK = TODAY - dt.timedelta(days=7)


# Argon2 at test cost, and no pause after a failed unlock: this suite
# opens diaries constantly (see tests/conftest.py).
pytestmark = pytest.mark.usefixtures("cheap_kdf")


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


async def type_body(pilot, body: str) -> None:
    """Fill the open editor's text."""
    pilot.app.screen.query_one("#body", TextArea).text = body
    await pilot.pause()


def row_labels(app: ZecretApp) -> list[str]:
    return [
        str(item.query_one(Label).content)
        for item in app.screen.query_one("#entries", ListView).children
    ]


def ciphertexts(path: Path) -> dict[str, str]:
    document = json.loads(path.read_bytes())
    return {rec["date"]: rec["ciphertext"] for rec in document["entries"]}


# --- opening the editor ----------------------------------------------------


async def test_n_opens_today_empty_when_the_day_is_unwritten(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        assert app.screen.date == TODAY
        assert app.screen.creating is True
        assert app.screen.body_text == ""


async def test_n_opens_todays_existing_entry_rather_than_a_second_one(diary_path):
    """One entry per day: coming back to today continues what is there."""
    seed(diary_path, Entry.new(TODAY, "Written this morning."))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        assert app.screen.creating is False
        assert app.screen.body_text == "Written this morning."


async def test_enter_opens_the_selected_day_prefilled(diary_path):
    seed(diary_path, Entry.new(LAST_WEEK, "A body\nover two lines"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        assert app.screen.date == LAST_WEEK
        assert app.screen.creating is False
        assert app.screen.body_text == "A body\nover two lines"


async def test_the_header_names_the_day_being_written(diary_path):
    seed(diary_path, Entry.new(LAST_WEEK, "Body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.sub_title == format_day_long(LAST_WEEK)


async def test_the_text_is_focused_so_writing_can_start_immediately(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        assert app.screen.focused is app.screen.query_one("#body", TextArea)


# --- writing ---------------------------------------------------------------


async def test_saving_a_new_entry_persists_it_under_today(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        await type_body(pilot, "It was cold.")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()

        assert isinstance(app.screen, EntryListScreen), "should return to the list"
        assert len(app.diary.entries) == 1

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    saved = reopened.entry_for(TODAY)
    assert saved is not None
    assert saved.body == "It was cold."


async def test_a_new_entry_appears_in_the_list(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        await type_body(pilot, "Morning walk. It was cold.")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()
        assert "Morning walk. It was cold." in " ".join(row_labels(app))


async def test_writing_today_twice_edits_the_same_entry(diary_path):
    """The end-to-end version of one-entry-per-day: two rounds of writing
    on the same day leave one entry, not two."""
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        for text in ("First thoughts.", "First thoughts. And more."):
            await pilot.press("n")
            await pilot.pause()
            await type_body(pilot, text)
            await pilot.press("ctrl+s")
            await pilot.pause()
            await pilot.pause()

        assert set(app.diary.entries) == {TODAY}

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entry_for(TODAY).body == "First thoughts. And more."


async def test_an_empty_entry_is_refused(diary_path):
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


async def test_an_entry_of_only_whitespace_is_refused(diary_path):
    """The list renders a body of spaces and newlines as "(empty)", so
    letting one through would file a day under nothing anyone wrote."""
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        app.screen.query_one("#body", TextArea).text = "   \n\n\t  \n"
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen), "must not leave"
        assert str(app.screen.query_one("#editor-error", Label).content) == EMPTY_ENTRY
        assert app.diary.entries == {}


async def test_surrounding_whitespace_is_kept_on_a_body_that_has_text(diary_path):
    """Only the question of whether there is any text is asked with the
    whitespace off; what gets stored is what was typed."""
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        app.screen.query_one("#body", TextArea).text = "  indented thought\n"
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.diary.entry_for(TODAY).body == "  indented thought\n"


# --- editing ---------------------------------------------------------------


async def test_saving_an_edit_updates_the_entry_in_place(diary_path):
    entry = Entry.new(YESTERDAY, "Original body")
    seed(diary_path, entry)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_body(pilot, "Edited body")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()
        assert len(app.diary.entries) == 1, "an edit must not add a second entry"

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    saved = reopened.entries[YESTERDAY]
    assert saved.body == "Edited body"
    assert saved.date == entry.date
    assert saved.created_at == entry.created_at
    assert saved.updated_at > entry.updated_at


async def test_editing_one_day_leaves_other_ciphertexts_alone(diary_path):
    """The UI path must preserve the per-entry independence that storage
    guarantees (CLAUDE.md requirement 6)."""
    seed(diary_path, Entry.new(YESTERDAY, "Edit me"), Entry.new(LAST_WEEK, "Leave me"))
    before = ciphertexts(diary_path)

    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        # Yesterday sorts above last week, so it is the first row.
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.date == YESTERDAY
        await type_body(pilot, "Edited body")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()

    after = ciphertexts(diary_path)
    assert after[LAST_WEEK.isoformat()] == before[LAST_WEEK.isoformat()]
    assert after[YESTERDAY.isoformat()] != before[YESTERDAY.isoformat()]


# --- backing out -----------------------------------------------------------


async def test_escape_with_no_changes_returns_immediately(diary_path):
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
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
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_body(pilot, "Changed")
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)


async def test_cancelling_the_discard_keeps_you_editing(diary_path):
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_body(pilot, "Changed")
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("escape")  # dismisses the modal as "cancel"
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        assert app.screen.body_text == "Changed", "the edit must survive"


async def test_confirming_the_discard_drops_the_changes(diary_path):
    entry = Entry.new(YESTERDAY, "A body")
    seed(diary_path, entry)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_body(pilot, "Changed")
        await pilot.press("escape")
        await pilot.pause()
        await pilot.click("#confirm-yes")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen)
        assert app.diary.entries == {entry.date: entry}, "nothing may be persisted"

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entries[YESTERDAY].body == "A body"


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


async def test_saving_says_so_over_the_list_it_returns_to(diary_path, notifications):
    """The editor pops on save, and an edited day looks the same in the
    list as it did before -- so nothing on the screen distinguished a save
    that worked from one that never happened."""
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_body(pilot, "Changed")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen)
        assert SAVED in notifications(app)


async def test_the_saved_message_does_not_follow_you_into_the_next_day(diary_path, notifications):
    """Textual keeps a notification for its timeout and redraws the live
    ones onto whichever screen is current, so this one went away with the
    editor it was raised in, arrived over the list -- which is wanted --
    and then turned up again over the next empty editor, announcing a save
    that had nothing to do with the day now on the screen."""
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_body(pilot, "Changed")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()
        assert SAVED in notifications(app), "wanted on the list"

        await pilot.press("n")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        assert notifications(app) == [], "not wanted over the next day"


async def test_a_refused_save_does_not_claim_to_have_saved(diary_path, notifications):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        await type_body(pilot, "   \n  ")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        assert SAVED not in notifications(app)


# --- quitting --------------------------------------------------------------


async def test_ctrl_q_with_unsaved_changes_asks_before_quitting(diary_path):
    """The hole this closes: escape asks, and the idle lock refuses to fire,
    but ctrl+q used to exit outright -- and being Textual's own binding it
    is not in the key bar to warn anyone that it would."""
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_body(pilot, "Changed")
        await pilot.press("ctrl+q")
        await pilot.pause()
        assert app.is_running, "quitting must not have happened yet"
        assert isinstance(app.screen, ConfirmScreen)


async def test_cancelling_the_quit_keeps_you_editing(diary_path):
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_body(pilot, "Changed")
        await pilot.press("ctrl+q")
        await pilot.pause()
        await pilot.press("escape")  # dismisses the modal as "cancel"
        await pilot.pause()
        await pilot.pause()
        assert app.is_running
        assert isinstance(app.screen, EditorScreen)
        assert app.screen.body_text == "Changed", "the edit must survive"


async def test_confirming_the_quit_leaves(diary_path):
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_body(pilot, "Changed")
        await pilot.press("ctrl+q")
        await pilot.pause()
        await pilot.click("#confirm-yes")
        await pilot.pause()
        assert not app.is_running

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entries[YESTERDAY].body == "A body", "nothing may be persisted"


async def test_ctrl_q_over_the_discard_question_does_not_ask_twice(diary_path):
    """Escape has already put the question on the screen. A second copy of
    it on top would hide the first and ask the same thing again."""
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_body(pilot, "Changed")
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        modals = [s for s in app.screen_stack if isinstance(s, ConfirmScreen)]
        await pilot.press("ctrl+q")
        await pilot.pause()
        assert app.is_running
        assert [s for s in app.screen_stack if isinstance(s, ConfirmScreen)] == modals


async def test_quitting_with_nothing_unsaved_does_not_ask(diary_path):
    """The guard is about unsaved writing, not about quitting. A list with
    no editor over it has nothing to lose, so 'q' still just leaves."""
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert isinstance(app.screen, EntryListScreen)
        await pilot.press("q")
        await pilot.pause()
        assert not app.is_running


async def test_an_unmodified_editor_quits_without_asking(diary_path):
    """Opening a day and reading it is not unsaved work."""
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        await pilot.press("ctrl+q")
        await pilot.pause()
        assert not app.is_running


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
        await type_body(pilot, "Do not lose this.")

        def boom(*_args, **_kwargs):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(type(app.diary), "save", boom)
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert isinstance(app.screen, EditorScreen)
        assert app.screen.body_text == "Do not lose this."
        assert "No space left" in str(app.screen.query_one("#editor-error", Label).content)


async def test_a_diary_changed_underneath_refuses_the_save_and_says_so(diary_path):
    """A second Zecret saved while this one was writing. The text stays on
    screen, and nothing of the other session's is overwritten."""
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        await type_body(pilot, "Written here.")

        # Stand in for the other session: same file, its own DiaryFile.
        other, other_key = DiaryFile.unlock(diary_path, PASSWORD)
        other.add_entry(Entry.new(YESTERDAY, "Written by the other session"))
        other.save(other_key)
        after_other = diary_path.read_bytes()

        await pilot.press("ctrl+s")
        await pilot.pause()

        assert isinstance(app.screen, EditorScreen), "must not leave"
        assert app.screen.body_text == "Written here."
        assert DIARY_CHANGED in str(app.screen.query_one("#editor-error", Label).content)
        assert app.diary.entries == {}, "the refused entry must not linger in memory"

    assert diary_path.read_bytes() == after_other


async def test_saving_again_after_a_failure_succeeds(diary_path, monkeypatch):
    """The failed attempt must leave the diary as it was: with the day's
    entry already added in memory, the retry would hit 'an entry already
    exists for today' instead of saving."""
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        await type_body(pilot, "Do not lose this.")

        real_save = type(app.diary).save

        def boom(*_args, **_kwargs):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(type(app.diary), "save", boom)
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.diary.entries == {}, "a failed save must not linger in memory"

        monkeypatch.setattr(type(app.diary), "save", real_save)
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen)

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entry_for(TODAY).body == "Do not lose this."


async def test_a_failed_save_of_an_edit_restores_the_previous_text(diary_path, monkeypatch):
    """The rollback has two halves. This is the one for a day that already
    had an entry: memory must go back to what is still on disk, not to
    nothing."""
    original = Entry.new(YESTERDAY, "What was there before")
    seed(diary_path, original)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_body(pilot, "An edit that will not land")

        def boom(*_args, **_kwargs):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(type(app.diary), "save", boom)
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert isinstance(app.screen, EditorScreen)
        assert app.screen.body_text == "An edit that will not land", "the text stays"
        assert app.diary.entries[YESTERDAY].body == "What was there before"

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entries[YESTERDAY].body == "What was there before"
