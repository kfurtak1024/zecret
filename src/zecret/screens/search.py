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

import datetime as dt
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import Input, Label

from zecret.models import Entry
from zecret.screens.base import DayList, ZecretScreen, day_row, entry_summary, unchanged
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
        # The diary the results were last filtered from -- see
        # on_screen_resume.
        self.drawn: dict[dt.date, Entry] | None = None

    def compose(self) -> ComposeResult:
        yield DiaryHeader()
        yield Input(placeholder="Search entries", id="query")
        yield Label(NO_MATCHES, id="search-empty")
        # An OptionList for the reason the entry list is one: an empty query
        # lists the whole diary, and a widget per row made opening search on
        # ten years of entries take eight seconds -- and every keystroke
        # that still matched most of them take as long again.
        yield DayList(id="results")
        yield DiaryFooter()

    def on_mount(self) -> None:
        self.query_one("#query", Input).focus()

    def on_screen_resume(self) -> None:
        """Re-filter on return from the editor: the entry may have changed.

        Only if it did. The query cannot have changed while the editor was
        open, so an unchanged diary is unchanged results -- and a day read
        and left alone is the usual way back from a search.

        Skipped when the app is locking, which pops this screen too -- see
        EntryListScreen.
        """
        if not self.zecret.is_unlocked:
            return
        diary, _ = self.zecret.unlocked
        if not unchanged(self.drawn, diary.entries):
            self.refresh_results()
            # Taken here rather than on every refresh: the diary cannot
            # change while this screen is the one in front, only while the
            # editor is, so a keystroke has no reason to copy it.
            self.drawn = dict(diary.entries)

    def on_input_changed(self, _event: Input.Changed) -> None:
        """Live filtering -- no submit step."""
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

        Synchronous, start to finish, so a keystroke's rebuild is over
        before the next keystroke is read: there is no queue of stale
        queries to work through, and nothing to lock. (Rebuilding a
        ListView was a sequence of awaits, which serialised behind a lock
        -- typing four letters over a long diary meant waiting for four
        full rebuilds one after another.)
        """
        diary, _ = self.zecret.unlocked
        query = self.query_one("#query", Input).value.strip().casefold()
        # An empty query lists everything, so opening search shows the
        # whole diary rather than a blank screen.
        found_entries = sorted(
            (entry for entry in diary.entries.values() if not query or matches(entry, query)),
            key=lambda entry: entry.date,
            reverse=True,
        )

        results = self.results_list
        # Read while self.results still describes the rows on screen. Taken
        # after the swap, it looked the old row number up in the new
        # results, so narrowing a query left the cursor on whatever day now
        # sat at that row -- neither the day you were on nor the top.
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
        """Where to leave the cursor once the results have been rebuilt.

        On the same day, if it is still a result: returning from the editor
        should not lose the reader's place, and narrowing a query that still
        matches what they were reading should not either. Otherwise the top,
        which is what a new set of results deserves.
        """
        if date is None:
            return 0
        return next((row for row, entry in enumerate(self.results) if entry.date == date), 0)

    def on_option_list_option_selected(self, event: DayList.OptionSelected) -> None:
        index = event.option_index
        if 0 <= index < len(self.results):
            self.app.push_screen(EditorScreen(self.results[index].date))

    def action_back(self) -> None:
        self.dismiss()
