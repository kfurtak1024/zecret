"""Full-text search over decrypted entries already held in memory.

Since app.diary.entries are already decrypted for the session, search is a
simple in-memory substring/case-insensitive filter over the entry text as
the query changes (live filtering, no separate "submit" step needed). No
plaintext is ever written to disk as part of search.

Selecting a result opens it in the editor, so search is a way into an entry
rather than a dead end; the results refresh on return, since the entry may
have been edited or its text may no longer match. That refresh keeps the
cursor on the day it was on where that day is still a result, so coming
back from an entry does not cost you the one you were reading.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import Input, Label, ListItem, ListView

from zecret.models import Entry
from zecret.screens.base import ZecretScreen, entry_summary
from zecret.screens.editor import EditorScreen
from zecret.screens.header import DiaryFooter, DiaryHeader

NO_MATCHES = "No entries match."


def matches(entry: Entry, query: str) -> bool:
    """Case-insensitive substring match over an entry's text."""
    # casefold() rather than lower(): correct for non-ASCII text, which
    # diary entries are as likely to contain as anything else.
    return query in entry.body.casefold()


class SearchScreen(ZecretScreen):
    """Live full-text search over the in-memory decrypted entries."""

    SUB_TITLE = "Search"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.results: list[Entry] = []
        # See EntryListScreen: resume and query-changed can both rebuild the
        # list, and interleaved rebuilds duplicate rows.
        self.refresh_lock = asyncio.Lock()

    def compose(self) -> ComposeResult:
        yield DiaryHeader()
        yield Input(placeholder="Search entries", id="query")
        yield Label(NO_MATCHES, id="search-empty")
        yield ListView(id="results")
        yield DiaryFooter()

    def on_mount(self) -> None:
        self.query_one("#query", Input).focus()

    async def on_screen_resume(self) -> None:
        """Re-filter on return from the editor: the entry may have changed.

        Skipped when the app is locking, which pops this screen too -- see
        EntryListScreen.
        """
        if not self.zecret.is_unlocked:
            return
        await self.refresh_results()

    async def on_input_changed(self, _event: Input.Changed) -> None:
        """Live filtering -- no submit step."""
        await self.refresh_results()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        """Enter in the query box moves to the results to pick one."""
        if self.results:
            self.query_one("#results", ListView).focus()

    async def refresh_results(self) -> None:
        diary, _ = self.zecret.unlocked

        async with self.refresh_lock:
            # Read inside the lock, like the entry list does: whoever gets
            # to render last then renders what is in the box now, with no
            # reasoning needed about the order refreshes were queued in.
            query = self.query_one("#query", Input).value.strip().casefold()
            # An empty query lists everything, so opening search shows the
            # whole diary rather than a blank screen.
            self.results = sorted(
                (entry for entry in diary.entries.values() if not query or matches(entry, query)),
                key=lambda entry: entry.date,
                reverse=True,
            )

            results = self.query_one("#results", ListView)
            was_on = self.highlighted_date
            await results.clear()
            # One mount pass, not one per result: see EntryListScreen, where
            # appending row by row made a long diary take a minute to draw.
            await results.extend(ListItem(Label(entry_summary(entry))) for entry in self.results)

            found = bool(self.results)
            self.query_one("#search-empty", Label).display = not found
            results.display = found
            if found:
                results.index = self.row_for(was_on)

    @property
    def highlighted_date(self) -> dt.date | None:
        """The day the cursor is on, or None if there is nothing under it."""
        index = self.query_one("#results", ListView).index
        if index is None or not 0 <= index < len(self.results):
            return None
        return self.results[index].date

    def row_for(self, date: dt.date | None) -> int:
        """Where to leave the cursor once the results have been rebuilt.

        On the same day, if it is still a result: returning from the editor
        should not lose the reader's place, and narrowing a query that still
        matches what they were reading should not either. Otherwise the top,
        which is what a new set of results deserves.
        """
        if date is None:
            return 0
        return next((row for row, entry in enumerate(self.results) if entry.date == date), 0)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        index = event.list_view.index
        if index is not None and 0 <= index < len(self.results):
            self.app.push_screen(EditorScreen(self.results[index].date))

    def action_back(self) -> None:
        self.dismiss()
