"""Full-text search over the decrypted entries already held in memory.

A case-insensitive substring filter, live as the query changes. Nothing
is written to disk.

The entries are casefolded and sorted once, when the screen opens or
returns to a changed diary, and each keystroke only scans that.

Selecting a result opens it in the editor. On return the results refresh
if the diary changed, keeping the cursor on the same day where it is
still a result.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import Input, Label

from zecret.models import Entry
from zecret.screens.base import DayList, ZecretScreen, day_row, entry_summary, unchanged
from zecret.screens.editor import EditorScreen
from zecret.screens.header import DiaryFooter, DiaryHeader

NO_MATCHES = "No entries match."


def searchable(entries: Iterable[Entry]) -> list[tuple[Entry, str]]:
    """The entries newest first, each beside the text a query is matched in."""
    # casefold() rather than lower(): correct for non-ASCII text.
    return [
        (entry, entry.body.casefold())
        for entry in sorted(entries, key=lambda entry: entry.date, reverse=True)
    ]


class SearchScreen(ZecretScreen):
    """Live full-text search over the in-memory decrypted entries."""

    SUB_TITLE = "Search"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", priority=True),
        Binding("ctrl+l", "app.lock", "Lock", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.results: list[Entry] = []
        # The diary the results are filtered from, and that diary folded
        # for matching.
        self.drawn: dict[dt.date, Entry] | None = None
        self.folded: list[tuple[Entry, str]] = []

    def compose(self) -> ComposeResult:
        yield DiaryHeader()
        yield Input(placeholder="Search entries", id="query")
        yield Label(NO_MATCHES, id="search-empty")
        # An empty query lists the whole diary, hence a DayList.
        yield DayList(id="results")
        yield DiaryFooter()

    def on_mount(self) -> None:
        self.query_one("#query", Input).focus()

    def on_screen_resume(self) -> None:
        """Re-filter on return from the editor, if the diary changed.

        Skipped when the app is locking, which pops this screen too.
        """
        if not self.zecret.is_unlocked:
            return
        diary, _ = self.zecret.unlocked
        if not unchanged(self.drawn, diary.entries):
            self.take_in(diary.entries)
            self.refresh_results()

    def take_in(self, entries: Mapping[dt.date, Entry]) -> None:
        """Note the diary to search, folded once for every keystroke after."""
        self.drawn = dict(entries)
        self.folded = searchable(entries.values())

    def on_input_changed(self, _event: Input.Changed) -> None:
        """Live filtering; there is no submit step."""
        self.refresh_results()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        """Enter in the query box moves to the results to pick one."""
        if self.results:
            self.results_list.focus()

    @property
    def results_list(self) -> DayList:
        return self.query_one("#results", DayList)

    def refresh_results(self) -> None:
        """Filter the diary by what is in the box now, and redraw.

        Synchronous, so a keystroke's rebuild is over before the next key
        is read.
        """
        if self.drawn is None:
            # A keystroke before the screen's first resume.
            diary, _ = self.zecret.unlocked
            self.take_in(diary.entries)
        query = self.query_one("#query", Input).value.strip().casefold()
        # An empty query matches everything.
        found_entries = [entry for entry, text in self.folded if query in text]

        results = self.results_list
        # Read while self.results still describes the rows on screen.
        was_on = self.highlighted_date
        self.results = found_entries
        results.set_options(day_row(entry_summary(entry)) for entry in self.results)

        found = bool(self.results)
        self.query_one("#search-empty", Label).display = not found
        results.display = found
        if found:
            results.highlighted = self.row_for(was_on)

    @property
    def highlighted_date(self) -> dt.date | None:
        """The day the cursor is on, or None if there is nothing under it."""
        index = self.results_list.highlighted
        if index is None or not 0 <= index < len(self.results):
            return None
        return self.results[index].date

    def row_for(self, date: dt.date | None) -> int:
        """Where to leave the cursor after a rebuild: on the same day if it
        is still a result, otherwise the top."""
        if date is None:
            return 0
        return next((row for row, entry in enumerate(self.results) if entry.date == date), 0)

    def on_option_list_option_selected(self, event: DayList.OptionSelected) -> None:
        index = event.option_index
        if 0 <= index < len(self.results):
            self.app.push_screen(EditorScreen(self.results[index].date))

    def action_back(self) -> None:
        self.dismiss()
