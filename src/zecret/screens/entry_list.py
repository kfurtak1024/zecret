"""Main screen: the diary, one row per day, most recent first.

Responsibilities:
    - Render entries from app.diary.entries, sorted by date descending.
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

The delete confirmation uses the shared ConfirmScreen modal (screens/
confirm.py), as does discarding unsaved edits in the editor.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Callable
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import Footer, Header, Label, ListItem, ListView

from zecret.models import Entry
from zecret.screens.base import ZecretScreen, entry_summary, format_day, today
from zecret.screens.confirm import ConfirmScreen
from zecret.screens.date_prompt import DatePromptScreen
from zecret.screens.editor import EditorScreen
from zecret.screens.search import SearchScreen
from zecret.screens.settings import SettingsScreen

EMPTY_MESSAGE = "Nothing written yet. Press 'n' to write about today."


class EntryListScreen(ZecretScreen):
    """Lists the days written and routes to write/edit/search/settings."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("n", "today", "Today"),
        Binding("g", "another_day", "Another day"),
        # ListView handles Enter itself and posts Selected; this binding is
        # what puts "Open" in the footer, and covers the empty-list case.
        Binding("enter", "open_entry", "Open"),
        Binding("d", "delete_entry", "Delete"),
        Binding("slash", "search", "Search", key_display="/"),
        Binding("s", "settings", "Settings"),
        # "app.quit", not "quit": a binding's action is dispatched on the
        # node that declares it, and a Screen has no action_quit -- an
        # unqualified "quit" here silently does nothing.
        Binding("q", "app.quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        # Entries in display order, so a list index maps back to an entry.
        self.ordered: list[Entry] = []
        # Rebuilding the list is a sequence of awaits, and two rebuilds can
        # be in flight at once -- deleting an entry refreshes, and popping
        # the confirmation modal resumes this screen, which also refreshes.
        # Interleaved, they duplicate rows; serialized, the last one wins.
        self.refresh_lock = asyncio.Lock()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(EMPTY_MESSAGE, id="entries-empty")
        yield ListView(id="entries")
        yield Footer()

    async def on_screen_resume(self) -> None:
        """Fires when this screen is shown, including after returning from
        the editor or search -- so the list always reflects app.diary."""
        await self.refresh_entries()

    async def refresh_entries(self) -> None:
        """Rebuild the list from the in-memory diary, most recent day first."""
        async with self.refresh_lock:
            diary, _ = self.zecret.unlocked
            self.ordered = sorted(
                diary.entries.values(), key=lambda entry: entry.date, reverse=True
            )

            list_view = self.query_one("#entries", ListView)
            await list_view.clear()
            for entry in self.ordered:
                await list_view.append(ListItem(Label(entry_summary(entry))))

            count = len(self.ordered)
            self.sub_title = (
                "no entries" if not count else f"{count} entr{'y' if count == 1 else 'ies'}"
            )

            has_entries = bool(self.ordered)
            self.query_one("#entries-empty", Label).display = not has_entries
            list_view.display = has_entries
            if has_entries:
                list_view.index = 0
                list_view.focus()

    @property
    def selected_entry(self) -> Entry | None:
        """The highlighted entry, or None when the list is empty."""
        index = self.query_one("#entries", ListView).index
        if index is None or not 0 <= index < len(self.ordered):
            return None
        return self.ordered[index]

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Enter (or a click) on a row opens it."""
        self.open_day(self.ordered[event.list_view.index or 0].date)

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
        except OSError as error:
            # The file still holds the entry, so put it back in memory too
            # rather than let the user believe the deletion stuck.
            diary.add_entry(entry)
            self.notify(
                f"Could not save: {error.strerror or error}.",
                severity="error",
            )
        self.run_worker(self.refresh_entries())
