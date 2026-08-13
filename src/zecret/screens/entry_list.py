"""Main screen: the diary, one row per day, most recent first, grouped
into months.

Responsibilities:
    - Render entries from app.diary.entries, sorted by date descending,
      under a heading per month ("August 2026 · 12 entries"). Because the
      heading names the month, the rows under it need only the weekday and
      day of the month.
    - Keybindings: 'n' write today -> EditorScreen, 'g' pick another day
      -> DatePromptScreen -> EditorScreen, 'enter' open selected day
      -> EditorScreen, 'd' delete selected (with confirmation modal),
      '/' -> SearchScreen, 's' -> SettingsScreen, 'q' quit.
    - After returning from EditorScreen/SearchScreen, refresh the list from
      the current in-memory app.diary state (no re-read from disk needed,
      since app.diary is the source of truth during the session).

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
from textual.widgets import Footer, Label, ListItem, ListView

from zecret.models import Entry
from zecret.screens.base import (
    DIARY_CHANGED,
    ZecretScreen,
    count_entries,
    day_summary,
    format_day,
    format_month,
    today,
)
from zecret.screens.confirm import ConfirmScreen
from zecret.screens.date_prompt import DatePromptScreen
from zecret.screens.editor import EditorScreen
from zecret.screens.header import DiaryHeader
from zecret.screens.help import HelpScreen
from zecret.screens.search import SearchScreen
from zecret.screens.settings import SettingsScreen
from zecret.storage import ZecretConflictError

EMPTY_MESSAGE = "Nothing written yet. Press 'n' to write about today."

#: Marks the rows that are month headings rather than entries.
HEADING_CLASS = "group-heading"


class EntryListScreen(ZecretScreen):
    """Lists the days written and routes to write/edit/search/settings."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("n", "today", "Today"),
        Binding("g", "another_day", "Another day"),
        # ListView has focus and handles Enter itself, posting Selected --
        # which on_list_view_selected turns into the same call. This binding
        # is what puts "Open" in the footer; the action behind it is a
        # second door onto the same room rather than the one you walk
        # through, and guards its own selection accordingly.
        Binding("enter", "open_entry", "Open"),
        Binding("d", "delete_entry", "Delete"),
        Binding("slash", "search", "Search", key_display="/"),
        Binding("s", "settings", "Settings"),
        # Bound here rather than app-wide on purpose: a '?' typed into the
        # editor, the search box or a password field must stay a '?'.
        Binding("question_mark", "help", "Help", key_display="?"),
        # "app.quit", not "quit": a binding's action is dispatched on the
        # node that declares it, and a Screen has no action_quit -- an
        # unqualified "quit" here silently does nothing.
        Binding("q", "app.quit", "Quit"),
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
        yield Footer()

    async def on_screen_resume(self) -> None:
        """Fires when this screen is shown, including after returning from
        the editor or search -- so the list always reflects app.diary."""
        await self.refresh_entries()

    async def refresh_entries(self) -> None:
        """Rebuild the list from the in-memory diary, most recent day first,
        with a heading above each month."""
        async with self.refresh_lock:
            diary, _ = self.zecret.unlocked
            entries = sorted(diary.entries.values(), key=lambda entry: entry.date, reverse=True)

            list_view = self.query_one("#entries", ListView)
            await list_view.clear()
            self.rows = []
            # Sorted by date, so each month's entries are already adjacent.
            for first_of_month, group in groupby(
                entries, key=lambda entry: entry.date.replace(day=1)
            ):
                month = list(group)
                self.rows.append(None)
                heading = f"{format_month(first_of_month)} · {count_entries(len(month))}"
                # Disabled, so the cursor steps over it and clicks on it do
                # nothing -- it is a signpost, not somewhere to be.
                await list_view.append(
                    ListItem(Label(heading), disabled=True, classes=HEADING_CLASS)
                )
                for entry in month:
                    self.rows.append(entry)
                    await list_view.append(ListItem(Label(day_summary(entry))))

            self.sub_title = "no entries" if not entries else count_entries(len(entries))

            has_entries = bool(entries)
            self.query_one("#entries-empty", Label).display = not has_entries
            list_view.display = has_entries
            if has_entries:
                # Not index 0: that is a month heading, and assigning an
                # index is not filtered by the skip-disabled rule that
                # cursor movement follows -- Enter would then open nothing.
                list_view.index = self.first_entry_row
                list_view.focus()

    @property
    def first_entry_row(self) -> int | None:
        """The row of the newest entry, past the heading it sits under."""
        return next((row for row, entry in enumerate(self.rows) if entry is not None), None)

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

    def action_delete_entry(self) -> None:
        entry = self.selected_entry
        if entry is None:
            return
        question = f"Delete the entry for {format_day(entry.date)}? This cannot be undone."
        self.app.push_screen(ConfirmScreen(question), self.confirm_delete(entry))

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
            self.notify(
                DIARY_CHANGED
                if isinstance(error, ZecretConflictError)
                else f"Could not save: {error.strerror or error}.",
                severity="error",
            )
        self.run_worker(self.refresh_entries())
