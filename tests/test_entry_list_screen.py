"""Tests for EntryListScreen: listing days, selection, and delete.

Required coverage:
    - Unlocking routes to the entry list.
    - Days render most-recent-first, with an empty state when there are
      none.
    - Days are grouped under a heading per month, carrying that month's
      entry count. Headings are rows too, so: the highlight never rests on
      one, the cursor steps over them, and everything that maps a
      selection back to a day (open, delete) lands on the right day.
    - 'a' offers another day to write about and opens the editor on it;
      backing out of the prompt changes nothing.
    - 'c' opens the calendar, and coming back from it lands on the day its
      cursor was on, or the nearest older one written. Those are tested
      with the calendar, in test_calendar_screen.py.
    - Delete asks for confirmation first; cancelling changes nothing.
    - That question has two answers and not three: the modal offers to
      save where there is writing to save, and a deletion has nothing
      between going ahead and leaving the day alone.
    - Confirmed delete removes the entry from memory AND from disk, and
      leaves the other entries intact.
    - The list refreshes from app.diary whenever the screen is resumed and
      the diary has changed -- and only then: closing the help or reading a
      day without writing does not rebuild a list that can be years long.
      unchanged() judges that by identity, so an edit, an addition, a
      deletion and a reload all count, and an untouched diary does not.
    - That refresh keeps the reader where they were: on the day they had
      highlighted, or -- when that day was the one just deleted -- on the
      next older day, which has moved up into its place.
    - Coming back from the editor lands on the day just written, even when
      it had no row before ('n' and 'a'). The cursor used to stay on the
      day it was on, which after the rebuild sat next to the new one --
      usually just below it. That holds on every road out of the editor,
      including "Save and go back", which runs the editor's callback after
      the list's rebuild rather than before it; and the landing is used
      once, never saved up for whatever the list is resumed from next.
      Backing out of a day that was never written leaves the cursor where
      it was.
    - Page keys move a screenful of *lines*, not rows: a month heading is
      two lines, and counting rows made page down step over days in a
      sparse diary without ever showing them.
    - The cursor stops at the ends of the list: down on the oldest day and
      up on the newest stay put rather than wrapping around.
    - A row shows the first line exactly as written: text that looks like
      Textual markup is neither interpreted nor fatal. So does anything else
      that quotes text Zecret did not write -- a reload reporting a damaged
      file shows what the file says, rather than crashing on it, and the
      delete question shows its wording as given.
    - A row carries the entry's whole first line rather than a fixed slice
      of it, and is clipped to the window at render time. This is what lets
      a wide terminal show more of a day without any of it being recomputed
      when the window is resized.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from textual.widgets import Button, Input, Label, MaskedInput, OptionList
from textual.widgets._toast import Toast

from zecret.app import ZecretApp
from zecret.models import Entry
from zecret.screens.base import EMPTY_BODY, format_day, format_day_short, format_month, unchanged
from zecret.screens.confirm import ConfirmScreen as Question
from zecret.screens.date_prompt import DatePromptScreen
from zecret.screens.editor import EditorScreen
from zecret.screens.entry_list import (
    EMPTY_MESSAGE,
    ConfirmScreen,
    EntryListScreen,
)
from zecret.screens.unlock import UnlockScreen
from zecret.storage import DiaryFile

PASSWORD = "correct horse battery staple"

TODAY = dt.date.today()
YESTERDAY = TODAY - dt.timedelta(days=1)
LAST_WEEK = TODAY - dt.timedelta(days=7)
LAST_YEAR = TODAY - dt.timedelta(days=365)

# Two fixed months, so grouping assertions do not depend on where in the
# month the suite happens to run.
MARCH = [dt.date(2026, 3, 4), dt.date(2026, 3, 17), dt.date(2026, 3, 28)]
FEBRUARY = [dt.date(2026, 2, 9), dt.date(2026, 2, 22)]


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
    """Get past UnlockScreen to the entry list."""
    pilot.app.screen.query_one("#password", Input).value = PASSWORD
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()


def entries_list(app: ZecretApp) -> OptionList:
    return app.screen.query_one("#entries", OptionList)


def row_labels(app: ZecretApp) -> list[str]:
    """Every row, month headings included, in display order -- without the
    blank line a heading carries above it."""
    return [str(option.prompt).strip("\n") for option in entries_list(app).options]


def entry_labels(app: ZecretApp) -> list[str]:
    """Only the rows that are entries: headings are the disabled ones."""
    return [str(option.prompt) for option in entries_list(app).options if not option.disabled]


def snippets(app: ZecretApp) -> list[str]:
    return [label.split("   ")[-1] for label in entry_labels(app)]


def month_entries(diary_path: Path) -> None:
    """Five entries across two months, seeded newest last."""
    seed(diary_path, *(Entry.new(day, f"Body for {day}") for day in FEBRUARY + MARCH))


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
        assert snippets(app) == ["Newest", "Middle", "Oldest"]


async def test_rows_show_the_day_then_a_glimpse_of_the_text(diary_path):
    """Short day form: the month heading above already names the month."""
    seed(diary_path, Entry.new(YESTERDAY, "First line\nsecond line"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert entry_labels(app) == [f"{format_day_short(YESTERDAY)}   First line"]


async def test_an_entry_with_no_text_still_shows_its_day(diary_path):
    seed(diary_path, Entry.new(YESTERDAY, ""))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert entry_labels(app) == [f"{format_day_short(YESTERDAY)}   {EMPTY_BODY}"]


# --- grouping by month -----------------------------------------------------


async def test_each_month_gets_a_heading_with_its_count(diary_path):
    month_entries(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert row_labels(app) == [
            f"{format_month(MARCH[0])} · 3 entries",
            f"{format_day_short(MARCH[2])}   Body for {MARCH[2]}",
            f"{format_day_short(MARCH[1])}   Body for {MARCH[1]}",
            f"{format_day_short(MARCH[0])}   Body for {MARCH[0]}",
            f"{format_month(FEBRUARY[0])} · 2 entries",
            f"{format_day_short(FEBRUARY[1])}   Body for {FEBRUARY[1]}",
            f"{format_day_short(FEBRUARY[0])}   Body for {FEBRUARY[0]}",
        ]


async def test_a_single_entry_month_is_counted_in_the_singular(diary_path):
    seed(diary_path, Entry.new(FEBRUARY[0], "Alone"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert row_labels(app)[0] == f"{format_month(FEBRUARY[0])} · 1 entry"


async def test_the_same_month_in_different_years_gets_its_own_heading(diary_path):
    """Grouping is by month *and* year -- March 2026 is not March 2025."""
    seed(
        diary_path,
        Entry.new(dt.date(2025, 3, 4), "Older March"),
        Entry.new(dt.date(2026, 3, 4), "Newer March"),
    )
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert [label for label in row_labels(app) if "·" in label] == [
            "March 2026 · 1 entry",
            "March 2025 · 1 entry",
        ]


async def test_an_empty_diary_has_no_headings(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert row_labels(app) == []


async def test_the_highlight_starts_on_an_entry_not_a_heading(diary_path):
    """Row 0 is always a heading, and assigning an index is not subject to
    the skip-disabled rule that cursor movement follows."""
    month_entries(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert entries_list(app).highlighted == 1
        assert app.screen.selected_entry.date == MARCH[2]


async def test_the_cursor_steps_over_a_heading_between_months(diary_path):
    month_entries(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        for _ in range(3):  # to the last March entry, then across the heading
            await pilot.press("down")
            await pilot.pause()
        assert app.screen.selected_entry.date == FEBRUARY[1]


async def test_enter_opens_the_highlighted_day_after_crossing_a_heading(diary_path):
    """The row index is no longer an index into the entries; a slip here
    would open the wrong day."""
    month_entries(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        for _ in range(4):
            await pilot.press("down")
            await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        assert app.screen.date == FEBRUARY[0]


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


async def test_a_opens_the_date_prompt(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await pilot.press("a")  # ignored: still on the unlock screen
        await unlock(pilot)
        await pilot.press("a")
        await pilot.pause()
        assert isinstance(app.screen, DatePromptScreen)


async def test_choosing_a_day_opens_the_editor_on_it(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("a")
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
        await pilot.press("a")
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
        await pilot.press("a")
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


async def test_the_delete_question_offers_no_third_answer(diary_path):
    """The modal grew a "save first" button for the questions about
    unsaved writing. A deletion has no third road between going through
    with it and leaving the day alone, so it must not sprout one."""
    seed(diary_path, Entry.new(YESTERDAY, "Keep me"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("d")
        await pilot.pause()
        assert not app.screen.query("#confirm-save")
        assert app.screen.focused is app.screen.query_one("#confirm-no", Button), (
            "a stray enter must not delete anything"
        )


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
        assert entry_labels(app) == [f"{format_day_short(YESTERDAY)}   Keep me"]

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
        assert snippets(app) == ["Keep me"]

    # Persisted, not just dropped from memory.
    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert set(reopened.entries) == {LAST_WEEK}


async def test_delete_removes_the_highlighted_day_across_a_heading(diary_path):
    """Deleting by row index rather than by the mapped entry would take out
    the wrong day once headings shift everything down."""
    month_entries(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        for _ in range(3):  # first February entry, one heading down the list
            await pilot.press("down")
            await pilot.pause()
        assert app.screen.selected_entry.date == FEBRUARY[1]
        await pilot.press("d")
        await pilot.pause()
        await pilot.click("#confirm-yes")
        await pilot.pause()
        await pilot.pause()

        assert set(app.diary.entries) == set(MARCH) | {FEBRUARY[0]}
        assert row_labels(app)[-2] == f"{format_month(FEBRUARY[0])} · 1 entry"


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
        assert entry_labels(app) == [f"{format_day_short(YESTERDAY)}   Keep me"]


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


# --- acting on nothing -----------------------------------------------------


async def test_open_on_an_empty_list_does_nothing(diary_path):
    """Pressing enter is already swallowed by the focused (empty) list,
    so the action is invoked directly: its guard is what keeps a stale or
    absent selection from opening the editor on nothing."""
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert app.screen.selected_entry is None

        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen)

        app.screen.action_open_entry()
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen)


async def test_the_open_action_opens_the_highlighted_day(diary_path):
    """The footer advertises enter as Open. The key itself is handled by
    the list itself, so this covers the action the binding names."""
    seed(diary_path, Entry.new(YESTERDAY, "A body"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        app.screen.action_open_entry()
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        assert app.screen.date == YESTERDAY


async def test_entry_at_ignores_a_row_that_is_not_there(diary_path):
    month_entries(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        screen = app.screen
        assert screen.entry_at(None) is None
        assert screen.entry_at(-1) is None
        assert screen.entry_at(len(screen.rows)) is None
        assert screen.entry_at(0) is None, "row 0 is a month heading"


# --- keeping the reader's place --------------------------------------------


async def test_the_cursor_stays_on_the_day_you_opened(diary_path):
    """A rebuild is a redraw. Sending someone back to the newest entry
    every time they read one would make a long diary unreadable."""
    month_entries(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        for _ in range(3):  # down past the March/February heading
            await pilot.press("down")
            await pilot.pause()
        row, day = entries_list(app).highlighted, app.screen.selected_entry.date
        assert day == FEBRUARY[1]

        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()

        assert entries_list(app).highlighted == row
        assert app.screen.selected_entry.date == day


async def test_writing_a_new_day_leaves_the_cursor_on_it(diary_path):
    """Today had no row when 'n' was pressed, so the cursor was on
    yesterday -- which is where it stayed, one row below the day just
    written."""
    seed(diary_path, *(Entry.new(TODAY - dt.timedelta(days=n), f"Day {n}") for n in range(1, 6)))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        await pilot.press("x", "ctrl+s", "escape")
        await pilot.pause()
        await pilot.pause()

        assert isinstance(app.screen, EntryListScreen)
        assert app.screen.selected_entry.date == TODAY


async def test_writing_another_day_leaves_the_cursor_on_it(diary_path):
    """The same through 'a', whose prompt closes -- and resumes the list --
    before the editor is even opened."""
    month_entries(diary_path)
    missed = dt.date(2026, 3, 10)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("a")
        await pilot.pause()
        app.screen.query_one("#date", MaskedInput).value = missed.isoformat()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        await pilot.press("x", "ctrl+s", "escape")
        await pilot.pause()
        await pilot.pause()

        assert app.screen.selected_entry.date == missed


async def test_saving_from_the_question_on_the_way_out_lands_on_the_day(diary_path):
    """escape, then "Save and go back". Leaving through the question runs
    the editor's callback after the list has been rebuilt rather than
    before it, and landing used to depend on the order."""
    seed(diary_path, *(Entry.new(TODAY - dt.timedelta(days=n), f"Day {n}") for n in range(1, 6)))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        await pilot.press("x", "escape")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        await pilot.press("enter")  # focus starts on saving
        await pilot.pause()
        await pilot.pause()

        assert isinstance(app.screen, EntryListScreen)
        assert app.screen.selected_entry.date == TODAY


async def test_landing_on_a_day_does_not_linger_for_the_next_return(diary_path):
    """Moving away from the day and then closing something else -- here
    the help popup -- must leave the cursor where it was moved to. The
    landing used to wait in a field for the next resume to find, and
    went off on whichever one came."""
    seed(diary_path, *(Entry.new(TODAY - dt.timedelta(days=n), f"Day {n}") for n in range(1, 6)))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        await pilot.press("x", "escape")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert app.screen.selected_entry.date == TODAY

        await pilot.press("down", "down")
        await pilot.pause()
        moved_to = app.screen.selected_entry.date
        assert moved_to != TODAY
        await pilot.press("question_mark")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()

        assert app.screen.selected_entry.date == moved_to


async def test_opening_a_written_day_with_n_lands_on_it_on_the_way_back(diary_path):
    """'n' on a day that is already written opens it, and coming back puts
    the cursor on it -- the day you were in -- whether or not a word of it
    changed."""
    month_entries(diary_path)
    seed_today = Entry.new(TODAY, "Already written")
    diary, key = DiaryFile.unlock(diary_path, PASSWORD)
    diary.add_entry(seed_today)
    diary.save(key)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("end")
        await pilot.pause()
        assert app.screen.selected_entry.date != TODAY

        await pilot.press("n")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()

        assert app.screen.selected_entry.date == TODAY


async def test_backing_out_of_an_unwritten_day_leaves_the_cursor_alone(diary_path):
    """Nothing was written, so there is no new row to land on."""
    month_entries(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("down")
        await pilot.pause()
        assert app.screen.selected_entry.date == MARCH[1]

        await pilot.press("n")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()

        assert app.screen.selected_entry.date == MARCH[1]


async def test_deleting_a_day_leaves_the_cursor_on_the_next_older_one(diary_path):
    """The day below has moved up into the gap, which is where the eye is."""
    month_entries(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("down")
        await pilot.pause()
        assert app.screen.selected_entry.date == MARCH[1]

        await pilot.press("d")
        await pilot.pause()
        await pilot.click("#confirm-yes")
        await pilot.pause()
        await pilot.pause()

        assert app.screen.selected_entry.date == MARCH[0]


async def test_deleting_the_oldest_day_leaves_the_cursor_at_the_foot(diary_path):
    """Nothing older is left to fall onto, and the reader was at the bottom
    of the list -- so that is where they stay, not back at the top."""
    month_entries(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        for _ in range(len(app.screen.rows)):
            await pilot.press("down")
            await pilot.pause()
        assert app.screen.selected_entry.date == FEBRUARY[0], "not at the oldest day"

        await pilot.press("d")
        await pilot.pause()
        await pilot.click("#confirm-yes")
        await pilot.pause()
        await pilot.pause()

        screen = app.screen
        assert entries_list(app).highlighted == len(screen.rows) - 1
        assert screen.selected_entry.date == FEBRUARY[1]


# --- reloading -------------------------------------------------------------


async def test_reload_picks_up_another_sessions_writing(diary_path):
    seed(diary_path, Entry.new(YESTERDAY, "Mine"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)

        other, other_key = DiaryFile.unlock(diary_path, PASSWORD)
        other.add_entry(Entry.new(LAST_WEEK, "Theirs"))
        other.save(other_key)

        await pilot.press("r")
        await pilot.pause()
        await pilot.pause()

        assert set(app.diary.entries) == {YESTERDAY, LAST_WEEK}
        assert snippets(app) == ["Mine", "Theirs"]


async def test_reload_unsticks_a_refused_save(diary_path):
    """The whole point: after a conflict every save is refused until the
    diary in memory is the one on disk again."""
    seed(diary_path, Entry.new(YESTERDAY, "Mine"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)

        other, other_key = DiaryFile.unlock(diary_path, PASSWORD)
        other.add_entry(Entry.new(LAST_WEEK, "Theirs"))
        other.save(other_key)

        # Deleting now hits the conflict and rolls back.
        await pilot.press("d")
        await pilot.pause()
        await pilot.click("#confirm-yes")
        await pilot.pause()
        await pilot.pause()
        assert set(app.diary.entries) == {YESTERDAY}, "the delete should have been refused"

        await pilot.press("r")
        await pilot.pause()
        await pilot.pause()

        # And now the same delete lands.
        await pilot.press("d")
        await pilot.pause()
        await pilot.click("#confirm-yes")
        await pilot.pause()
        await pilot.pause()
        assert set(app.diary.entries) == {LAST_WEEK}

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert set(reopened.entries) == {LAST_WEEK}


async def test_reload_reports_a_password_changed_elsewhere(diary_path):
    seed(diary_path, Entry.new(YESTERDAY, "Mine"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        before = dict(app.diary.entries)

        other, _ = DiaryFile.unlock(diary_path, PASSWORD)
        other.save(other.change_password("an entirely different passphrase"))

        await pilot.press("r")
        await pilot.pause()
        await pilot.pause()

        assert app.diary.entries == before, "the diary in hand must be left alone"
        assert isinstance(app.screen, EntryListScreen)


async def test_reload_survives_an_unreadable_file(diary_path):
    seed(diary_path, Entry.new(YESTERDAY, "Mine"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        before = dict(app.diary.entries)

        diary_path.write_bytes(b"not a diary at all")
        await pilot.press("r")
        await pilot.pause()
        await pilot.pause()

        assert app.diary.entries == before
        assert isinstance(app.screen, EntryListScreen)


async def test_reload_reports_a_diary_that_has_gone(diary_path):
    seed(diary_path, Entry.new(YESTERDAY, "Mine"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        diary_path.unlink()

        await pilot.press("r")
        await pilot.pause()
        await pilot.pause()

        assert set(app.diary.entries) == {YESTERDAY}
        assert isinstance(app.screen, EntryListScreen)


# --- getting around --------------------------------------------------------


def long_diary(diary_path: Path, days: int = 90) -> None:
    """Months of consecutive entries, so jumps have somewhere to go."""
    seed(
        diary_path,
        *(
            Entry.new(dt.date(2026, 1, 1) + dt.timedelta(days=offset), f"Day {offset}")
            for offset in range(days)
        ),
    )


def cursor(app: ZecretApp) -> int:
    return entries_list(app).highlighted


async def test_j_and_k_move_a_day_at_a_time(diary_path):
    long_diary(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        start = cursor(app)
        await pilot.press("j", "j", "j")
        await pilot.pause()
        assert cursor(app) == start + 3
        await pilot.press("k")
        await pilot.pause()
        assert cursor(app) == start + 2


async def test_g_and_G_reach_the_ends_of_the_diary(diary_path):
    """The whole point: the far end of a long diary should be one key, not
    three hundred."""
    long_diary(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("G")
        await pilot.pause()
        assert app.screen.selected_entry.date == min(app.diary.entries)

        await pilot.press("g")
        await pilot.pause()
        assert app.screen.selected_entry.date == max(app.diary.entries)


async def test_home_and_end_do_the_same(diary_path):
    long_diary(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("end")
        await pilot.pause()
        assert app.screen.selected_entry.date == min(app.diary.entries)

        await pilot.press("home")
        await pilot.pause()
        assert app.screen.selected_entry.date == max(app.diary.entries)


async def test_the_page_keys_move_a_screenful(diary_path):
    long_diary(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(80, 20)) as pilot:
        await unlock(pilot)
        start = cursor(app)
        await pilot.press("pagedown")
        await pilot.pause()
        moved = cursor(app) - start
        assert moved > 1, "a page should be more than a row"
        assert moved <= app.screen.page_rows + 1, "and not more than a screenful"

        await pilot.press("pageup")
        await pilot.pause()
        assert cursor(app) == start


async def test_a_jump_never_lands_on_a_month_heading(diary_path):
    """Assigning an index is not filtered by the skip-disabled rule that
    the arrow keys follow, so every jump has to step off a heading itself."""
    long_diary(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(80, 20)) as pilot:
        await unlock(pilot)
        for key in ("pagedown", "pagedown", "pagedown", "G", "pageup", "pageup", "g"):
            await pilot.press(key)
            await pilot.pause()
            assert app.screen.rows[cursor(app)] is not None, f"{key} landed on a month heading"


async def test_paging_up_from_the_top_stays_on_the_newest_entry(diary_path):
    """Row 0 is a heading and there is nothing above it, so the walk off it
    has to turn around."""
    long_diary(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(80, 20)) as pilot:
        await unlock(pilot)
        for _ in range(5):
            await pilot.press("pageup")
            await pilot.pause()
        assert cursor(app) == app.screen.first_entry_row
        assert app.screen.selected_entry.date == max(app.diary.entries)


async def test_paging_down_from_the_bottom_stays_on_the_oldest_entry(diary_path):
    long_diary(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(80, 20)) as pilot:
        await unlock(pilot)
        for _ in range(20):
            await pilot.press("pagedown")
            await pilot.pause()
        assert cursor(app) == app.screen.last_entry_row


async def test_getting_around_an_empty_diary_does_nothing(diary_path):
    """Every jump key is live on a diary with no rows to jump between."""
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        for key in ("j", "k", "g", "G", "home", "end", "pageup", "pagedown"):
            await pilot.press(key)
            await pilot.pause()
        assert isinstance(app.screen, EntryListScreen)
        assert app.screen.rows == []


# --- how much of a day a row shows -----------------------------------------


#: Longer than any row was ever given before, and longer than a narrow
#: terminal can show -- so a row carrying all of it proves the length is no
#: longer decided here.
LONG_FIRST_LINE = "The morning was clear and I walked further than I meant to, " * 3


async def test_a_row_carries_the_whole_first_line(diary_path):
    """The row is given the line; the window decides how much of it shows.

    Rows used to be cut to sixty characters whatever the terminal was, so a
    wide window showed a lot of empty space beside a truncated day.
    """
    seed(diary_path, Entry.new(TODAY, f"{LONG_FIRST_LINE}\nand a second line"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(60, 20)) as pilot:
        await unlock(pilot)
        assert snippets(app) == [LONG_FIRST_LINE.strip()], (
            "the row should hold the whole line even when the terminal cannot show it"
        )


async def test_a_row_still_stops_at_the_first_line(diary_path):
    """Wider is not taller: the row is a day, and the rest of the day's
    writing belongs in the editor."""
    seed(diary_path, Entry.new(TODAY, "The first line.\nThe second line."))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(200, 20)) as pilot:
        await unlock(pilot)
        assert snippets(app) == ["The first line."]


async def test_rows_are_clipped_by_the_window_rather_than_wrapped(diary_path):
    """The CSS that makes the whole thing work, and the reason no resize
    handler is needed: the widget trims at render time. A wrapped row would
    also be two rows tall, which would break the alignment of the list."""
    seed(diary_path, Entry.new(TODAY, LONG_FIRST_LINE))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(60, 20)) as pilot:
        await unlock(pilot)
        listing = entries_list(app)
        assert listing.styles.text_wrap == "nowrap"
        assert listing.styles.text_overflow == "ellipsis"
        # The heading's blank line and the heading, then the day on one row
        # -- trimmed with an ellipsis at the edge of the window, not wrapped
        # onto a second.
        lines = [
            "".join(segment.text for segment in strip).rstrip()
            for strip in app.screen._compositor.render_strips()
        ]
        day = [line for line in lines if "The morning was clear" in line]
        assert len(day) == 1, "a day must not become two rows"
        assert day[0].endswith("…")


# --- what is written is what is shown --------------------------------------

#: A first line that Textual would read as markup if it were handed over as
#: a string: tags that would restyle the row and lose their brackets, and a
#: closing tag nobody opened, which raised MarkupError and took the app down
#: every time the list was drawn.
MARKUP_LINE = "Met [bold]Sam[/bold] and [red]Jo[/] -- closing [/i] for no reason"


async def test_a_first_line_that_looks_like_markup_is_shown_as_written(diary_path):
    seed(diary_path, Entry.new(TODAY, MARKUP_LINE))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(120, 20)) as pilot:
        await unlock(pilot)
        assert snippets(app) == [MARKUP_LINE]
        screen = "\n".join(
            "".join(segment.text for segment in strip)
            for strip in app.screen._compositor.render_strips()
        )
        assert MARKUP_LINE in screen


# --- the ends of the list --------------------------------------------------


async def test_down_on_the_oldest_day_stays_there(diary_path):
    """The list Textual offers wraps around; a diary should not jump from
    its first page back to today for one keypress too many."""
    month_entries(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("G")
        await pilot.pause()
        assert app.screen.selected_entry.date == FEBRUARY[0]
        await pilot.press("down", "j")
        await pilot.pause()
        assert app.screen.selected_entry.date == FEBRUARY[0]


async def test_up_on_the_newest_day_stays_there(diary_path):
    """Above it is only the month heading, which cannot be landed on."""
    month_entries(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert app.screen.selected_entry.date == MARCH[-1]
        await pilot.press("up", "k")
        await pilot.pause()
        assert app.screen.selected_entry.date == MARCH[-1]


# --- rebuilding only what changed ------------------------------------------


def rebuilds(app: ZecretApp, monkeypatch) -> list[None]:
    """Count the list's rebuilds from here on."""
    screen = app.screen
    counted: list[None] = []
    original = screen.refresh_entries

    def counting() -> None:
        counted.append(None)
        original()

    monkeypatch.setattr(screen, "refresh_entries", counting)
    return counted


async def test_closing_the_help_does_not_rebuild_the_list(diary_path, monkeypatch):
    month_entries(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        counted = rebuilds(app, monkeypatch)
        await pilot.press("question_mark")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen)
        assert counted == []


async def test_reading_a_day_without_writing_does_not_rebuild(diary_path, monkeypatch):
    month_entries(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        counted = rebuilds(app, monkeypatch)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()
        assert counted == []
        assert app.screen.selected_entry.date == MARCH[-1]


async def test_writing_a_day_does_rebuild(diary_path, monkeypatch):
    month_entries(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        counted = rebuilds(app, monkeypatch)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("x", "ctrl+s", "escape")
        await pilot.pause()
        await pilot.pause()
        assert counted == [None]
        # The row now holds the entry as written, not the one drawn before.
        assert "x" in app.screen.selected_entry.body


def test_unchanged_is_judged_by_identity():
    first = Entry.new(MARCH[0], "One")
    second = Entry.new(MARCH[1], "Two")
    drawn = {first.date: first, second.date: second}
    assert unchanged(drawn, dict(drawn)), "the same objects under the same days"
    assert not unchanged(None, drawn), "nothing drawn yet"
    assert not unchanged(drawn, {first.date: first}), "a day deleted"
    added = Entry.new(MARCH[2], "Three")
    assert not unchanged(drawn, {**drawn, added.date: added}), "a day added"
    assert not unchanged(drawn, {**drawn, first.date: first.edited("One")}), (
        "an edit is a new object even when the text reads the same"
    )


async def test_paging_through_a_sparse_diary_shows_every_day(diary_path):
    """One entry a month, so every other row is a two-line heading. Paged
    by rows, a jump went half again further than the screen and some days
    were never on it at all."""
    days = [dt.date(2020, 1, 15) + dt.timedelta(days=31 * month) for month in range(40)]
    seed(
        diary_path, *(Entry.new(day, f"Day of month {month:02d}") for month, day in enumerate(days))
    )
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await unlock(pilot)
        seen: set[str] = set()
        for _ in range(12):
            for strip in app.screen._compositor.render_strips():
                line = "".join(segment.text for segment in strip)
                if "Day of month" in line:
                    seen.add(line.split("Day of month")[1].split()[0])
            await pilot.press("pagedown")
            await pilot.pause()
        assert seen == {f"{month:02d}" for month in range(40)}


async def test_a_reload_quoting_markup_from_the_file_does_not_crash(diary_path, notifications):
    """The reload error quotes the file, and the file is the thing that is
    damaged: a version field of '[/bold]' reached the notification as
    markup, and Textual raised MarkupError the moment it drew it."""
    seed(diary_path, Entry.new(YESTERDAY, "Mine"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        document = json.loads(diary_path.read_text())
        document["version"] = "[/bold]"
        diary_path.write_text(json.dumps(document))

        await pilot.press("r")
        await pilot.pause()
        await pilot.pause()
        assert any("[/bold]" in message for message in notifications(app)), (
            "the failure should be reported, quoting the file"
        )
        # Drawn the way Textual draws it: a toast built from each live
        # notification. A headless run mounts none of its own, which is
        # why this went unseen.
        for notification in app._notifications:
            drawn = str(Toast(notification).render())
            assert drawn == notification.message


async def test_a_question_shows_its_wording_as_given(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        app.push_screen(Question("Keep [/bold] as typed?"))
        await pilot.pause()
        label = app.screen.query_one("#confirm-question", Label)
        assert str(label.render()) == "Keep [/bold] as typed?"
