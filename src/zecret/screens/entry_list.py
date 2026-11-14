"""Main screen: the diary, one row per day, newest first, grouped by month.

- Rows come from app.diary.entries, sorted here, under a heading per month
  ("August 2026 · 12 entries"). Grouping is presentation only; storage
  knows nothing of it.
- Month headings share the DayList with the entries as disabled options.
  A row index is therefore not an index into the entries: everything that
  maps a row back to a day goes through self.rows.
- On return from another screen the list is rebuilt only if the diary
  changed, and the cursor lands on the day handed back: the day edited,
  or the calendar's cursor day (or the nearest older one written).
- 'n' and 'a' hand a date to the editor, which decides whether that means
  a new entry or the existing one.

An OptionList, not a ListView: a ListView mounts a widget per row whether
or not it is on screen, which took seconds at ten years of entries.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from itertools import groupby
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import Label
from textual.widgets.option_list import Option

from zecret.crypto import ZecretDecryptError
from zecret.models import Entry
from zecret.screens.base import (
    REKEYED_ELSEWHERE,
    DayList,
    ZecretScreen,
    count_entries,
    day_row,
    day_summary,
    delete_question,
    format_month,
    plain,
    reread_error,
    today,
    unchanged,
)
from zecret.screens.calendar_view import CalendarScreen
from zecret.screens.confirm import Choice, ConfirmScreen
from zecret.screens.date_prompt import DatePromptScreen
from zecret.screens.editor import EditorScreen
from zecret.screens.header import DiaryFooter, DiaryHeader
from zecret.screens.search import SearchScreen
from zecret.screens.settings import SettingsScreen
from zecret.storage import DiaryFile

EMPTY_MESSAGE = "Nothing written yet. Press 'n' to write about today."


#: Lines a month heading takes on screen: a blank line, then the heading.
#: A day takes one. Paging counts lines, not rows; see move_cursor.
HEADING_LINES = 2


def heading_option(first_of_month: dt.date, count: int) -> Option:
    """The row naming a month, with a blank line above it.

    Disabled, so the cursor steps over it and clicks ignore it. The blank
    line is part of the option because an option has no margin.
    """
    heading = f"{format_month(first_of_month)} · {count_entries(count)}"
    return Option(plain("\n" * (HEADING_LINES - 1) + heading), disabled=True)


def entry_option(entry: Entry) -> Option:
    """The row for one day, as plain text."""
    return day_row(day_summary(entry))


class EntryListScreen(ZecretScreen):
    """Lists the days written and routes to write/edit/search/settings."""

    #: `show` decides only what goes in the footer; the help popup lists
    #: every binding. The eight shown fill 69 of 80 columns.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("n", "today", "Today"),
        Binding("c", "calendar", "Calendar"),
        # Hidden to make room for the calendar, which answers the same
        # question.
        Binding("a", "another_day", "Another day", show=False),
        Binding("d", "delete_entry", "Delete"),
        Binding("slash", "search", "Search", key_display="/"),
        Binding("s", "settings", "Settings"),
        # Shown because being able to find the lock key is a security
        # property. The same chord as on every other screen.
        Binding("ctrl+l", "lock", "Lock"),
        # Bound here, not app-wide, so '?' stays typeable in text fields.
        Binding("question_mark", "app.help", "Help", key_display="?"),
        # "app.quit", not "quit": an action is dispatched on the node that
        # declares the binding, and a Screen has no action_quit.
        Binding("q", "app.quit", "Quit"),
        # The DayList handles Enter itself (OptionSelected); this binding
        # is what documents it in the help popup.
        Binding("enter", "open_entry", "Edit", show=False),
        Binding("r", "reload", "Reload", show=False),
        # Getting around. home, end and the page keys are priority so they
        # go through move_cursor rather than OptionList's own handling,
        # which drops the highlight when a page up lands on the top
        # heading.
        Binding("j", "cursor_down", "Down a day", show=False),
        Binding("k", "cursor_up", "Up a day", show=False),
        Binding("pagedown", "page_down", "Down a screenful", show=False, priority=True),
        Binding("pageup", "page_up", "Up a screenful", show=False, priority=True),
        Binding("g", "first_entry", "Newest entry", show=False),
        Binding("home", "first_entry", "Newest entry", show=False, priority=True),
        Binding("G", "last_entry", "Oldest entry", show=False),
        Binding("end", "last_entry", "Oldest entry", show=False, priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        # One element per option, in display order: the entry that row
        # shows, or None for a month heading.
        self.rows: list[Entry | None] = []
        # The diary the rows were last built from; see on_screen_resume.
        self.drawn: dict[dt.date, Entry] | None = None
        # The day open in the editor, and the calendar while it is open
        # over this screen. Both are read in on_screen_resume to decide
        # where the cursor lands.
        self.editing: dt.date | None = None
        self.calendar: CalendarScreen | None = None

    def compose(self) -> ComposeResult:
        yield DiaryHeader()
        yield Label(EMPTY_MESSAGE, id="entries-empty")
        yield DayList(id="entries")
        yield DiaryFooter()

    def on_screen_resume(self) -> None:
        """Redraw if the diary changed, and land the cursor.

        Fires whenever this screen is shown. The list is rebuilt only when
        the diary changed since the rows were drawn. Otherwise the cursor
        just moves, if there is a day to land on.

        Where to land is decided here for both screens that hand a day
        back, because this is the one place certain to run after that
        screen has gone and before the redraw. A dismiss callback is not
        ordered against this handler.

        Returns early while locking (no diary), and when another screen
        is already in front: the date prompt opens the editor from its
        dismiss callback, which can run before this does.
        """
        if not self.zecret.is_unlocked or self.app.screen is not self:
            return
        diary, _ = self.zecret.unlocked
        landing: dt.date | None = None
        if self.calendar is not None:
            landing, self.calendar = self.calendar.date, None
        if self.editing is not None:
            if self.editing in diary.entries:
                landing = self.editing
            self.editing = None
        if not unchanged(self.drawn, diary.entries):
            self.refresh_entries(landing)
        elif landing is not None:
            self.move_cursor_to(self.row_for(landing))

    def refresh_entries(self, landing: dt.date | None = None) -> None:
        """Rebuild the list from the in-memory diary and put the cursor on
        `landing`, or back on the day it was on.

        Synchronous: nothing awaits, so rebuilds cannot interleave.
        """
        diary, _ = self.zecret.unlocked
        entries = sorted(diary.entries.values(), key=lambda entry: entry.date, reverse=True)

        listing = self.entries_list
        # Read before clearing, since rebuilding loses the highlight.
        was_on = landing if landing is not None else self.highlighted_date
        self.drawn = dict(diary.entries)
        self.rows = []
        options: list[Option] = []
        # Sorted by date, so each month's entries are adjacent.
        for first_of_month, group in groupby(entries, key=lambda entry: entry.date.replace(day=1)):
            month = list(group)
            self.rows.append(None)
            options.append(heading_option(first_of_month, len(month)))
            for entry in month:
                self.rows.append(entry)
                options.append(entry_option(entry))
        listing.set_options(options)

        self.sub_title = "no entries" if not entries else count_entries(len(entries))

        has_entries = bool(entries)
        self.query_one("#entries-empty", Label).display = not has_entries
        listing.display = has_entries
        if has_entries:
            # Never row 0, which is a heading: assigning a highlight is
            # not filtered by the skip-disabled rule.
            listing.highlighted = self.row_for(was_on)
            listing.focus()

    @property
    def entries_list(self) -> DayList:
        return self.query_one("#entries", DayList)

    @property
    def first_entry_row(self) -> int | None:
        """The row of the newest entry, past the heading it sits under."""
        return next((row for row, entry in enumerate(self.rows) if entry is not None), None)

    @property
    def last_entry_row(self) -> int | None:
        """The row of the oldest entry, at the bottom of the list."""
        return next(
            (row for row in reversed(range(len(self.rows))) if self.rows[row] is not None), None
        )

    @property
    def highlighted_date(self) -> dt.date | None:
        """The day the cursor is on, or None if it is not on an entry."""
        entry = self.selected_entry
        return None if entry is None else entry.date

    def row_for(self, date: dt.date | None) -> int | None:
        """The row to put the cursor on for `date`.

        The day's own row if it has one. Otherwise the nearest older day:
        after a deletion that is the row that moved up into its place, and
        for an unwritten day from the calendar it is the closest stand-in.
        Rows run newest first, so that is the first row not newer than
        `date`. With nothing that old, the last row.
        """
        if date is None:
            return self.first_entry_row
        same_or_older = next(
            (
                row
                for row, entry in enumerate(self.rows)
                if entry is not None and entry.date <= date
            ),
            None,
        )
        return self.last_entry_row if same_or_older is None else same_or_older

    def entry_at(self, row: int | None) -> Entry | None:
        """The entry a row shows, or None for a heading or a missing row."""
        if row is None or not 0 <= row < len(self.rows):
            return None
        return self.rows[row]

    @property
    def selected_entry(self) -> Entry | None:
        """The highlighted entry, or None when the list is empty."""
        return self.entry_at(self.entries_list.highlighted)

    def on_option_list_option_selected(self, event: DayList.OptionSelected) -> None:
        """Enter (or a click) on a row opens it."""
        entry = self.entry_at(event.option_index)
        if entry is not None:
            self.open_day(entry.date)

    # --- actions -----------------------------------------------------------

    def action_open_entry(self) -> None:
        entry = self.selected_entry
        if entry is not None:
            self.open_day(entry.date)

    def action_today(self) -> None:
        self.open_day(today())

    def action_another_day(self) -> None:
        """Ask which day to write about, marking the days already written."""
        self.app.push_screen(DatePromptScreen(written=self.written_days), self.open_chosen_day)

    def action_calendar(self) -> None:
        """Open the year, on the day the cursor is on here.

        The screen is kept so on_screen_resume can read its cursor's day.
        """
        self.calendar = CalendarScreen(self.highlighted_date)
        self.app.push_screen(self.calendar)

    def action_search(self) -> None:
        self.app.push_screen(SearchScreen())

    def action_settings(self) -> None:
        self.app.push_screen(SettingsScreen())

    def action_lock(self) -> None:
        """Put the diary away without leaving the app."""
        self.zecret.lock()

    def action_reload(self) -> None:
        """Re-read the file, to pick up what another Zecret wrote.

        The way out of a refused save from this screen. Nothing is lost:
        every save is immediate, so there is no unsaved state here.
        """
        diary, key = self.zecret.unlocked
        try:
            reopened = DiaryFile.reopen(diary.path, key)
        except ZecretDecryptError:
            # Re-keyed elsewhere: this session's key opens nothing now.
            self.notify(REKEYED_ELSEWHERE, severity="error")
            return
        except (OSError, ValueError) as error:
            # Not markup: the detail can quote the damaged file.
            self.notify(reread_error(error), severity="error", markup=False)
            return

        self.zecret.diary = reopened
        self.notify(f"Reloaded — {count_entries(len(reopened.entries))}.")
        self.refresh_entries()

    def action_delete_entry(self) -> None:
        entry = self.selected_entry
        if entry is None:
            return
        self.app.push_screen(ConfirmScreen(delete_question(entry.date)), self.confirm_delete(entry))

    # --- getting around ----------------------------------------------------

    def action_cursor_down(self) -> None:
        self.entries_list.action_cursor_down()

    def action_cursor_up(self) -> None:
        self.entries_list.action_cursor_up()

    def action_page_down(self) -> None:
        self.move_cursor(self.page_rows)

    def action_page_up(self) -> None:
        self.move_cursor(-self.page_rows)

    def action_first_entry(self) -> None:
        self.move_cursor_to(self.first_entry_row)

    def action_last_entry(self) -> None:
        self.move_cursor_to(self.last_entry_row)

    @property
    def page_rows(self) -> int:
        """A screenful of lines, less one, so a jump keeps something in view."""
        return max(1, self.entries_list.scrollable_content_region.height - 1)

    def lines_of(self, row: int) -> int:
        """How many lines of the screen a row takes."""
        return HEADING_LINES if self.rows[row] is None else 1

    def move_cursor(self, lines: int) -> None:
        """Move the highlight about `lines` screen lines, landing on a day.

        Lines, not rows: a heading is two lines, so a screenful of rows
        would overshoot and skip days in a sparse diary. At least one row
        is always crossed.

        A jump that lands on a heading walks off it, onwards first and
        back if the list ends that way.
        """
        here = self.entries_list.highlighted
        if here is None:
            return
        onwards = 1 if lines > 0 else -1
        target, travelled = here, 0
        while 0 <= target + onwards < len(self.rows):
            step = self.lines_of(target + onwards)
            if target != here and travelled + step > abs(lines):
                break
            target += onwards
            travelled += step
        landing = self.entry_row_from(target, onwards)
        if landing is None:
            landing = self.entry_row_from(target, -onwards)
        self.move_cursor_to(landing)

    def entry_row_from(self, row: int, step: int) -> int | None:
        """The first row from `row` in the `step` direction showing a day."""
        while 0 <= row < len(self.rows):
            if self.rows[row] is not None:
                return row
            row += step
        return None

    def move_cursor_to(self, row: int | None) -> None:
        """Highlight `row`, or do nothing when there is no day to go to."""
        if row is not None:
            self.entries_list.highlighted = row

    # --- helpers -----------------------------------------------------------

    def open_day(self, date: dt.date) -> None:
        """Open a day in the editor, noting it so the cursor lands there
        on return."""
        self.editing = date
        self.app.push_screen(EditorScreen(date))

    def open_chosen_day(self, date: dt.date | None) -> None:
        """Callback for DatePromptScreen; None means the user backed out."""
        if date is not None:
            self.open_day(date)

    def confirm_delete(self, entry: Entry) -> Callable[[Choice | None], None]:
        """Build the callback ConfirmScreen dismisses into."""

        def on_answered(choice: Choice | None) -> None:
            if choice is Choice.CONFIRM:
                self.delete_entry(entry)

        return on_answered

    def delete_entry(self, entry: Entry) -> None:
        """Remove the day's entry and persist immediately."""
        self.delete_day(entry.date)
        self.refresh_entries()
