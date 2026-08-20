"""Main screen: the diary, one row per day, most recent first, grouped
into months.

Responsibilities:
    - Render entries from app.diary.entries, sorted by date descending,
      under a heading per month ("August 2026 · 12 entries"). Because the
      heading names the month, the rows under it need only the weekday and
      day of the month.
    - Keybindings: 'n' write today -> EditorScreen, 'a' pick another day
      -> DatePromptScreen -> EditorScreen, 'enter' open selected day
      -> EditorScreen, 'd' delete selected (with confirmation modal),
      'r' re-read the file, '/' -> SearchScreen, 's' -> SettingsScreen,
      'L' lock, 'q' quit. Plus getting around a long diary: j/k, g/G,
      home/end and the page keys, none of which reach the footer.
    - After returning from EditorScreen/SearchScreen, refresh the list from
      the current in-memory app.diary state (no re-read from disk needed,
      since app.diary is the source of truth during the session), leaving
      the cursor on the day it was on -- a refresh is a redraw, not a
      reason to send a reader of a years-long diary back to the top.

'n' and 'g' both land on a date rather than on a new entry: the editor
opens whatever that day holds, so writing more about today just continues
today's entry instead of starting a second one.

Grouping is presentation only -- nothing about it reaches models.py or
storage.py, which know only about individual dated entries. The month
headings share the ListView with the entries as disabled rows, which
Textual's cursor navigation steps over and its clicks ignore. That leaves
one thing to get right: a row index is no longer an index into the
entries, so everything that maps a selection back to an entry goes through
self.rows.

The delete confirmation uses the shared ConfirmScreen modal (screens/
confirm.py), as does discarding unsaved edits in the editor.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Callable
from itertools import groupby
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import Label, ListItem, ListView

from zecret.crypto import ZecretDecryptError
from zecret.models import Entry
from zecret.screens.base import (
    ZecretScreen,
    count_entries,
    day_summary,
    format_day,
    format_month,
    save_error,
    today,
)
from zecret.screens.confirm import ConfirmScreen
from zecret.screens.date_prompt import DatePromptScreen
from zecret.screens.editor import EditorScreen
from zecret.screens.header import DiaryFooter, DiaryHeader
from zecret.screens.help import HelpScreen
from zecret.screens.search import SearchScreen
from zecret.screens.settings import SettingsScreen
from zecret.storage import DiaryFile, ZecretConflictError

EMPTY_MESSAGE = "Nothing written yet. Press 'n' to write about today."

#: A reload that cannot use the key this session holds. The only other
#: session that could cause it is one that changed the password.
RELOAD_REKEYED = "The password was changed elsewhere. Quit and unlock again."

#: Marks the rows that are month headings rather than entries.
HEADING_CLASS = "group-heading"


class EntryListScreen(ZecretScreen):
    """Lists the days written and routes to write/edit/search/settings."""

    #: `show` decides what goes in the footer and nothing else -- the help
    #: popup lists every binding here regardless. The bar holds about eighty
    #: columns and these eight fill seventy-two of them, so the room that
    #: was spare is now spent; everything below them is no less real for
    #: being found through '?' instead.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("n", "today", "Today"),
        Binding("a", "another_day", "Another day"),
        Binding("d", "delete_entry", "Delete"),
        Binding("slash", "search", "Search", key_display="/"),
        Binding("s", "settings", "Settings"),
        # A chord rather than a letter, and the same chord the editor
        # carries: locking is the one thing you want to press without first
        # working out which screen you are on, and a bare letter cannot be
        # bound where there is text to type into. ctrl+l is what a password
        # manager locks with, and Textual leaves it free -- no widget in
        # this app binds it, and the terminal's own clear-screen meaning
        # belongs to a shell prompt, which is not what is running here.
        #
        # Shown, which the rest of this group's weight of use would not
        # earn it. Whether someone can find this key is a security property
        # and not a convenience: a writer stepping away who does not know
        # it either quits, losing where they were, or leaves the diary open
        # on the screen. That is not true of 'r' or of the movement keys.
        Binding("ctrl+l", "lock", "Lock"),
        # Bound here rather than app-wide on purpose: a '?' typed into the
        # editor, the search box or a password field must stay a '?'.
        Binding("question_mark", "help", "Help", key_display="?"),
        # "app.quit", not "quit": a binding's action is dispatched on the
        # node that declares it, and a Screen has no action_quit -- an
        # unqualified "quit" here silently does nothing. The app's is
        # Zecret's own override, so this key and ctrl+q ask the same
        # question about unsaved writing rather than one of them not.
        Binding("q", "app.quit", "Quit"),
        # --- real, but not worth the width -------------------------------
        # ListView has focus and handles Enter itself, posting Selected --
        # which on_list_view_selected turns into the same call. The action
        # behind this binding is a second door onto the same room rather
        # than the one you walk through, and guards its own selection
        # accordingly. Hidden because the ListView's own enter binding
        # shadows it in the bar anyway: it never rendered there.
        Binding("enter", "open_entry", "Open", show=False),
        Binding("r", "reload", "Reload", show=False),
        # --- getting around ----------------------------------------------
        # A diary kept for years is a long list, and arrow keys alone make
        # its far end hundreds of presses away. j/k/g/G are what a terminal
        # reader will try first; home/end/page are what everyone else will.
        # j/k/g/G are ours alone. home, end and the page keys are not:
        # ListView inherits them from ScrollView, which scrolls the view
        # without moving the highlight -- leaving the cursor somewhere off
        # screen. `priority` takes them back, which is safe here because
        # this screen has no text field for them to mean anything else in.
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
        # One element per row of the ListView, in display order: the entry
        # that row shows, or None where the row is a month heading. This is
        # the only thing that maps a highlighted row back to a day.
        self.rows: list[Entry | None] = []
        # Rebuilding the list is a sequence of awaits, and two rebuilds can
        # be in flight at once -- deleting an entry refreshes, and popping
        # the confirmation modal resumes this screen, which also refreshes.
        # Interleaved, they duplicate rows; serialized, the last one wins.
        self.refresh_lock = asyncio.Lock()

    def compose(self) -> ComposeResult:
        yield DiaryHeader()
        yield Label(EMPTY_MESSAGE, id="entries-empty")
        yield ListView(id="entries")
        yield DiaryFooter()

    async def on_screen_resume(self) -> None:
        """Fires when this screen is shown, including after returning from
        the editor or search -- so the list always reflects app.diary.

        Also fires on the way out, as locking pops the screens above this
        one. There is no diary to draw from by then, and nothing to draw
        it onto.
        """
        if not self.zecret.is_unlocked:
            return
        await self.refresh_entries()

    async def refresh_entries(self) -> None:
        """Rebuild the list from the in-memory diary, most recent day first,
        with a heading above each month."""
        async with self.refresh_lock:
            diary, _ = self.zecret.unlocked
            entries = sorted(diary.entries.values(), key=lambda entry: entry.date, reverse=True)

            list_view = self.query_one("#entries", ListView)
            # Read before clearing: rebuilding is what loses the reader's
            # place, so where they were has to be taken down first.
            was_on = self.highlighted_date
            await list_view.clear()
            self.rows = []
            items: list[ListItem] = []
            # Sorted by date, so each month's entries are already adjacent.
            for first_of_month, group in groupby(
                entries, key=lambda entry: entry.date.replace(day=1)
            ):
                month = list(group)
                self.rows.append(None)
                heading = f"{format_month(first_of_month)} · {count_entries(len(month))}"
                # Disabled, so the cursor steps over it and clicks on it do
                # nothing -- it is a signpost, not somewhere to be.
                items.append(ListItem(Label(heading), disabled=True, classes=HEADING_CLASS))
                for entry in month:
                    self.rows.append(entry)
                    items.append(ListItem(Label(day_summary(entry))))

            # Mounted in one pass. Appending row by row re-lays-out every row
            # already mounted, which is quadratic: a decade of entries took
            # over a minute to draw, on every return to this screen.
            await list_view.extend(items)

            self.sub_title = "no entries" if not entries else count_entries(len(entries))

            has_entries = bool(entries)
            self.query_one("#entries-empty", Label).display = not has_entries
            list_view.display = has_entries
            if has_entries:
                # Never left at 0: that is a month heading, and assigning an
                # index is not filtered by the skip-disabled rule that
                # cursor movement follows -- Enter would then open nothing.
                list_view.index = self.row_for(was_on)
                list_view.focus()

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
        """The row to put the cursor on to leave the reader where they were.

        `date` is the day highlighted before the rebuild. Usually it still
        has a row and the cursor simply lands back on it -- returning from
        the editor should not cost someone their place halfway down a diary
        of years. When the day is gone, it was just deleted, and the next
        older day has moved up into the space it left, which is where the
        eye already is. Rows run newest first, so that is the first row not
        newer than `date`.
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
        # Nothing that old is left: the deleted day was the oldest one, so
        # the cursor was at the foot of the list and belongs there still.
        return self.last_entry_row if same_or_older is None else same_or_older

    def entry_at(self, row: int | None) -> Entry | None:
        """The entry a row shows, or None for a heading or a missing row."""
        if row is None or not 0 <= row < len(self.rows):
            return None
        return self.rows[row]

    @property
    def selected_entry(self) -> Entry | None:
        """The highlighted entry, or None when the list is empty."""
        return self.entry_at(self.query_one("#entries", ListView).index)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Enter (or a click) on a row opens it."""
        entry = self.entry_at(event.list_view.index)
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
        """Write about a day other than today -- one you missed, or one you
        want to add to."""
        self.app.push_screen(DatePromptScreen(), self.open_chosen_day)

    def action_search(self) -> None:
        self.app.push_screen(SearchScreen())

    def action_settings(self) -> None:
        self.app.push_screen(SettingsScreen())

    def action_help(self) -> None:
        # This screen's own keys are handed over: HelpScreen cannot import
        # the list it is opened from without closing an import cycle.
        self.app.push_screen(HelpScreen(self.BINDINGS))

    def action_lock(self) -> None:
        """Put the diary away without leaving the app."""
        self.zecret.lock()

    def action_reload(self) -> None:
        """Pick up what another Zecret wrote.

        The way out of a refused save: once the file has changed underneath
        this session, every save is a conflict until the diary in memory is
        the one on disk again. Nothing is lost by doing it -- every save
        here is immediate, so there is no unsaved state to overwrite.
        """
        diary, key = self.zecret.unlocked
        try:
            reopened = DiaryFile.reopen(diary.path, key)
        except ZecretDecryptError:
            # A re-key elsewhere. The session's key opens nothing in the
            # file now, and the password to derive a new one was not kept.
            self.notify(RELOAD_REKEYED, severity="error")
            return
        except (OSError, ValueError) as error:
            detail = error.strerror if isinstance(error, OSError) and error.strerror else error
            self.notify(f"Could not re-read the diary: {detail}.", severity="error")
            return

        self.zecret.diary = reopened
        self.notify(f"Reloaded — {count_entries(len(reopened.entries))}.")
        self.run_worker(self.refresh_entries())

    def action_delete_entry(self) -> None:
        entry = self.selected_entry
        if entry is None:
            return
        question = f"Delete the entry for {format_day(entry.date)}? This cannot be undone."
        self.app.push_screen(ConfirmScreen(question), self.confirm_delete(entry))

    # --- getting around ----------------------------------------------------

    def action_cursor_down(self) -> None:
        """j, handed to the ListView, which already steps over headings."""
        self.query_one("#entries", ListView).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#entries", ListView).action_cursor_up()

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
        """A screenful, less a row, so the jump keeps something in view."""
        return max(1, self.query_one("#entries", ListView).size.height - 1)

    def move_cursor(self, rows: int) -> None:
        """Move the highlight `rows` rows, landing on a day.

        Assigning an index is not filtered by the skip-disabled rule that
        arrow keys follow, so a jump that lands on a month heading has to
        walk off it -- onwards first, since that is the way the reader was
        already going.
        """
        list_view = self.query_one("#entries", ListView)
        here = list_view.index
        if here is None:
            return
        target = min(max(here + rows, 0), len(self.rows) - 1)
        onwards = 1 if rows > 0 else -1
        landing = self.entry_row_from(target, onwards)
        if landing is None:
            # Ran out of list that way: the top of the diary is always a
            # heading, so paging up lands on one with nothing above it.
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
            self.query_one("#entries", ListView).index = row

    # --- helpers -----------------------------------------------------------

    def open_day(self, date: dt.date) -> None:
        """Open a day for writing. The editor decides whether that means a
        new entry or the existing one, and the list refreshes on resume, so
        no callback is needed to pick up the change."""
        self.app.push_screen(EditorScreen(date))

    def open_chosen_day(self, date: dt.date | None) -> None:
        """Callback for DatePromptScreen; None means the user backed out."""
        if date is not None:
            self.open_day(date)

    def confirm_delete(self, entry: Entry) -> Callable[[bool | None], None]:
        """Build the callback ConfirmScreen dismisses into."""

        def on_confirmed(confirmed: bool | None) -> None:
            if confirmed:
                self.delete_entry(entry)

        return on_confirmed

    def delete_entry(self, entry: Entry) -> None:
        """Remove the day's entry and persist immediately."""
        diary, key = self.zecret.unlocked
        diary.delete_entry(entry.date)
        try:
            diary.save(key)
        except (OSError, ZecretConflictError) as error:
            # The file still holds the entry, so put it back in memory too
            # rather than let the user believe the deletion stuck.
            diary.add_entry(entry)
            self.notify(save_error(error), severity="error")
        self.run_worker(self.refresh_entries())
