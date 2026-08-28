"""Tests for EditorScreen: writing and revising a day's entry.

Required coverage:
    - 'n' from the list opens today: empty if the day is unwritten,
      prefilled if it is not -- never a second entry for the same day.
    - Enter opens the selected day prefilled.
    - Saving a new entry persists it to disk under its date and shows it
      in the list once you go back.
    - Saving does not leave: the text, the cursor and the screen all stay
      where they were, so the day can be carried on and saved again. It
      says "Saved." because nothing else on the screen moves to show it.
    - A day that has not changed since the last save is not rewritten --
      ctrl+s is now a reflex, and each press would otherwise restamp an
      entry nobody edited.
    - Escape after a save leaves without asking: nothing is unsaved.
    - A refused save says nothing about having saved, and a save that
      works clears the error the refused one left on the screen.
    - The message does not follow you into the next thing you open. A
      notification is the app's and outlives the screen that raised it, so
      "Saved." used to reappear over the empty editor opened next.
    - ctrl+home and ctrl+end reach the start and end of the entry, and
      count as moving rather than as editing.
    - ctrl+a selects the whole entry, the way it does everywhere else --
      Textual binds it to "start of line", which home still does.
    - A long day is wrapped in the frame it first appears in. Textual
      wraps on the Resize message, which arrives after the paint, so
      opening an entry used to show one frame of unwrapped text.
    - Saving an edit updates the entry in place: same date and created_at,
      refreshed updated_at, and no other entry rewritten.
    - Backing out with unsaved changes asks before discarding; backing out
      unchanged leaves immediately.
    - That question offers to save as well as to discard, and saving is
      what a stray enter lands on -- it is the answer that throws nothing
      away. A save that is refused keeps you in the day rather than
      leaving on the strength of writing that never reached disk.
    - Quitting with unsaved changes asks too, with the same three answers.
      ctrl+q is Textual's own app-wide binding and used to exit on the
      spot, throwing the text away by the one route that never prompted
      and never appeared in the key bar; both spellings of quit now go
      through the same question.
    - An empty entry is refused.
    - A save that fails keeps the user on the screen with their text, and
      leaves the diary able to retry.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from textual.widgets import Button, Input, Label, ListView, TextArea

from zecret.app import SAVE_AND_QUIT, ZecretApp
from zecret.models import Entry
from zecret.screens.base import DIARY_CHANGED, format_day_long
from zecret.screens.confirm import ConfirmScreen
from zecret.screens.editor import (
    EMPTY_ENTRY,
    SAVE_AND_GO_BACK,
    SAVED,
    DiaryTextArea,
    EditorScreen,
)
from zecret.screens.entry_list import EntryListScreen
from zecret.screens.unlock import UnlockScreen
from zecret.storage import DiaryFile

PASSWORD = "correct horse battery staple"

TODAY = dt.date.today()
YESTERDAY = TODAY - dt.timedelta(days=1)
LAST_WEEK = TODAY - dt.timedelta(days=7)

#: One paragraph with no newline in it, far wider than any terminal -- so
#: how many lines it occupies says whether it was wrapped or not.
LONG_PARAGRAPH = (
    "Walked the long way back along the canal, past the yard where they keep "
    "the narrowboats, and stopped at the lock to watch someone work a boat "
    "through it single-handed in the rain."
)


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


async def save_and_leave(pilot) -> None:
    """ctrl+s, then escape -- what writing a day and going back now takes.

    Saving keeps you in the day, so every test that wants the list back
    presses the key that leaves as well.
    """
    await pilot.press("ctrl+s")
    await pilot.pause()
    await pilot.press("escape")
    await pilot.pause()
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
        await save_and_leave(pilot)

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
        await save_and_leave(pilot)
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
            await save_and_leave(pilot)

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


# --- saving without leaving ------------------------------------------------


async def test_saving_keeps_you_in_the_day_with_the_text_and_the_cursor(diary_path):
    """An entry is written over an evening, not in one keystroke: being
    returned to the list on every ctrl+s meant pressing 'n' and finding
    your place again to add the next line."""
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        await type_body(pilot, "Two lines\nof it")
        body = app.screen.query_one("#body", TextArea)
        body.move_cursor((1, 3))
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert isinstance(app.screen, EditorScreen), "saving must not leave"
        assert app.screen.body_text == "Two lines\nof it"
        assert body.cursor_location == (1, 3), "the cursor must not be thrown to the top"
        assert app.diary.entry_for(TODAY).body == "Two lines\nof it"


async def test_carrying_on_after_a_save_and_saving_again(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        await type_body(pilot, "First thought.")
        await pilot.press("ctrl+s")
        await pilot.pause()
        await type_body(pilot, "First thought. And a second.")
        await pilot.press("ctrl+s")
        await pilot.pause()

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entry_for(TODAY).body == "First thought. And a second."
    assert len(reopened.entries) == 1


async def test_escape_after_saving_leaves_without_asking(diary_path):
    """A saved day is not unsaved work, so there is nothing to discard."""
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_body(pilot, "Changed")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.screen.blocks_lock is False, "nothing is unsaved any more"
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen)


async def test_saving_an_unchanged_day_does_not_rewrite_the_file(diary_path):
    """ctrl+s is now pressed every few sentences out of habit. Writing on
    every press would restamp a day nobody edited and turn another Zecret's
    saving into a conflict over an entry this one was not changing."""
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_body(pilot, "Changed")
        await pilot.press("ctrl+s")
        await pilot.pause()
        saved = diary_path.read_bytes()

        await pilot.press("ctrl+s")
        await pilot.pause()
        assert diary_path.read_bytes() == saved, "a second save had nothing to write"
        assert isinstance(app.screen, EditorScreen)


async def test_a_save_clears_the_error_the_last_attempt_left(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        await pilot.press("ctrl+s")  # refused: nothing written yet
        await pilot.pause()
        assert str(app.screen.query_one("#editor-error", Label).content) == EMPTY_ENTRY

        await type_body(pilot, "Something, at last.")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert str(app.screen.query_one("#editor-error", Label).content) == ""


# --- getting around the day ------------------------------------------------


async def test_ctrl_home_and_ctrl_end_reach_both_ends_of_the_entry(diary_path):
    """Textual's TextArea has home and end for the line and the page keys
    for a screenful, but nothing for the two ends of the text itself."""
    body = "\n".join(f"Line {number}" for number in range(60))
    seed(diary_path, Entry.new(YESTERDAY, body))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        text_area = app.screen.query_one("#body", TextArea)
        text_area.move_cursor((30, 2))

        await pilot.press("ctrl+end")
        await pilot.pause()
        assert text_area.cursor_location == (59, len("Line 59"))

        await pilot.press("ctrl+home")
        await pilot.pause()
        assert text_area.cursor_location == (0, 0)


async def test_going_to_either_end_does_not_change_the_text(diary_path):
    """Movement only: a key that quietly counted as an edit would put the
    discard question in front of someone who had merely looked."""
    seed(diary_path, Entry.new(YESTERDAY, "A body\nover two lines"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("ctrl+end")
        await pilot.press("ctrl+home")
        await pilot.pause()
        assert app.screen.body_text == "A body\nover two lines"
        assert app.screen.modified is False


async def test_ctrl_a_selects_the_whole_entry(diary_path):
    """Textual binds ctrl+a to readline's "start of line", and put select-
    all on f7, where nobody finds it."""
    seed(diary_path, Entry.new(YESTERDAY, "A body\nover two lines"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        text_area = app.screen.query_one("#body", TextArea)
        text_area.move_cursor((1, 5))

        await pilot.press("ctrl+a")
        await pilot.pause()
        assert text_area.selected_text == "A body\nover two lines"


async def test_home_still_goes_to_the_start_of_the_line(diary_path):
    """What ctrl+a used to do is not lost -- it is on the key most people
    reach for first."""
    seed(diary_path, Entry.new(YESTERDAY, "A body\nover two lines"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        text_area = app.screen.query_one("#body", TextArea)
        text_area.move_cursor((1, 5))

        await pilot.press("home")
        await pilot.pause()
        assert text_area.cursor_location == (1, 0)
        assert text_area.selected_text == ""


# --- how the day is drawn --------------------------------------------------


async def test_a_long_day_is_wrapped_in_the_frame_it_first_appears_in(diary_path, monkeypatch):
    """Opening an entry used to show it unwrapped for one frame.

    TextArea wraps its text when it handles a Resize, and a message is
    handled after the compositor has already drawn the widget -- so the
    first frame of a day was every paragraph running off the right-hand
    edge, replaced a frame later by the wrapped text. What is asserted is
    the height of the wrapped document at the first line ever painted:
    one line means the paint went out unwrapped.
    """
    seed(diary_path, Entry.new(LAST_WEEK, LONG_PARAGRAPH))

    heights: list[int] = []
    painting = DiaryTextArea.render_line

    def record(self, y):
        heights.append(self.wrapped_document.height)
        return painting(self, y)

    monkeypatch.setattr(DiaryTextArea, "render_line", record)

    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await unlock(pilot)
        # Nothing before this point drew an editor; anything recorded from
        # here on is the day being opened.
        heights.clear()
        await pilot.press("enter")
        await pilot.pause()

        assert heights, "the editor never painted"
        assert heights[0] > 1, "the first frame of the day was drawn unwrapped"


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


async def test_the_question_offers_to_save_and_that_is_what_is_focused(diary_path):
    """Escape is pressed to get back to the list, so being told the only
    ways to do that were to lose the last paragraph or to stay put made an
    ordinary key into a small trap. Saving is also the answer that throws
    nothing away, which is why a stray enter lands on it."""
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
        save = app.screen.query_one("#confirm-save", Button)
        assert str(save.label) == SAVE_AND_GO_BACK
        assert app.screen.focused is save


async def test_saving_from_the_question_keeps_the_writing_and_leaves(diary_path, notifications):
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_body(pilot, "Changed")
        await pilot.press("escape")
        await pilot.pause()
        await pilot.click("#confirm-save")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen)
        assert SAVED in notifications(app)

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entries[YESTERDAY].body == "Changed"


async def test_a_refused_save_from_the_question_keeps_you_in_the_day(diary_path, monkeypatch):
    """Leaving on the strength of a save that did not happen would lose
    exactly the text the answer was trying to keep."""
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_body(pilot, "Changed")

        def boom(*_args, **_kwargs):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(type(app.diary), "save", boom)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.click("#confirm-save")
        await pilot.pause()
        await pilot.pause()

        assert isinstance(app.screen, EditorScreen)
        assert app.screen.body_text == "Changed"
        assert "No space left" in str(app.screen.query_one("#editor-error", Label).content)


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


async def test_saving_says_so_over_the_day_you_are_still_writing(diary_path, notifications):
    """Nothing on the screen moves when a save lands -- the same text is
    still there, in the same place -- so without a word for it the keypress
    is indistinguishable from one the app never received."""
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_body(pilot, "Changed")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen), "saving must not leave"
        assert SAVED in notifications(app)


async def test_the_saved_message_does_not_follow_you_into_the_next_day(diary_path, notifications):
    """Textual keeps a notification for its timeout and redraws the live
    ones onto whichever screen is current, so this one used to turn up
    again over the next empty editor, announcing a save that had nothing to
    do with the day now on the screen."""
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_body(pilot, "Changed")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert SAVED in notifications(app), "wanted over the day just saved"

        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()
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


async def test_quitting_can_save_the_day_on_the_way_out(diary_path):
    """The same third answer the editor's own question offers, worded for
    where this key was heading."""
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_body(pilot, "Changed")
        await pilot.press("ctrl+q")
        await pilot.pause()
        save = app.screen.query_one("#confirm-save", Button)
        assert str(save.label) == SAVE_AND_QUIT
        await pilot.click("#confirm-save")
        await pilot.pause()
        assert not app.is_running

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entries[YESTERDAY].body == "Changed"


async def test_a_refused_save_does_not_quit(diary_path, monkeypatch):
    """Quitting on the strength of a save that did not happen would lose
    the writing by the one road that was chosen to keep it."""
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await type_body(pilot, "Changed")

        def boom(*_args, **_kwargs):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(type(app.diary), "save", boom)
        await pilot.press("ctrl+q")
        await pilot.pause()
        await pilot.click("#confirm-save")
        await pilot.pause()

        assert app.is_running, "the text is still only in the widget"
        assert isinstance(app.screen, EditorScreen)
        assert app.screen.body_text == "Changed"


async def test_a_screen_with_nothing_to_lose_saves_nothing_and_says_it_worked(diary_path):
    """The two halves have to agree: blocks_lock says whether a screen is
    holding anything, save_pending writes it. A screen answering False to
    the first must not answer False to the second, or quitting from a list
    that has nothing to save would refuse to quit."""
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert isinstance(app.screen, EntryListScreen)
        assert app.screen.blocks_lock is False
        assert app.screen.save_pending() is True
        assert app.save_unsaved_work() is True, "nothing to save is not a failure to save"


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
        await save_and_leave(pilot)
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
