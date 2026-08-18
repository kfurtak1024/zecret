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
    - Delete asks for confirmation first; cancelling changes nothing.
    - Confirmed delete removes the entry from memory AND from disk, and
      leaves the other entries intact.
    - The list refreshes from app.diary whenever the screen is resumed.
    - That refresh keeps the reader where they were: on the day they had
      highlighted, or -- when that day was the one just deleted -- on the
      next older day, which has moved up into its place.
    - A row carries the entry's whole first line rather than a fixed slice
      of it, and is clipped to the window at render time. This is what lets
      a wide terminal show more of a day without any of it being recomputed
      when the window is resized.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from textual.widgets import Input, Label, ListView, MaskedInput

from zecret.app import ZecretApp
from zecret.models import Entry
from zecret.screens.base import EMPTY_BODY, format_day, format_day_short, format_month
from zecret.screens.date_prompt import DatePromptScreen
from zecret.screens.editor import EditorScreen
from zecret.screens.entry_list import (
    EMPTY_MESSAGE,
    HEADING_CLASS,
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


def row_labels(app: ZecretApp) -> list[str]:
    """Every row, month headings included, in display order."""
    return [
        str(item.query_one(Label).content)
        for item in app.screen.query_one("#entries", ListView).children
    ]


def entry_labels(app: ZecretApp) -> list[str]:
    """Only the rows that are entries."""
    return [
        str(item.query_one(Label).content)
        for item in app.screen.query_one("#entries", ListView).children
        if not item.has_class(HEADING_CLASS)
    ]


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
        assert app.screen.query_one("#entries", ListView).index == 1
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
    """Pressing enter is already swallowed by the focused (empty) ListView,
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
    the ListView, so this covers the action the binding names."""
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
        row, day = app.screen.query_one("#entries", ListView).index, app.screen.selected_entry.date
        assert day == FEBRUARY[1]

        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()

        assert app.screen.query_one("#entries", ListView).index == row
        assert app.screen.selected_entry.date == day


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
        assert screen.query_one("#entries", ListView).index == len(screen.rows) - 1
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
    return app.screen.query_one("#entries", ListView).index


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
        rows = [
            item.query_one(Label)
            for item in app.screen.query_one("#entries", ListView).children
            if not item.has_class(HEADING_CLASS)
        ]
        assert rows
        for label in rows:
            assert label.styles.text_wrap == "nowrap"
            assert label.styles.text_overflow == "ellipsis"
            assert label.size.height == 1, "a day must not become two rows"
