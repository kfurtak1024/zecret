"""The calendar view: a year of the diary laid out, the days written marked.

The second way of looking at the diary, beside the entry list -- 'c' on
the list opens it, and 'c' or escape here goes back. The list answers
"what did I write"; this answers "when did I write", which no list of the
days that *were* written can show, since what it is for is the days that
were not. A whole year at once is the span the gaps in a diary show over:
a missed week is a hole in a month, and a missed month is a hole in a year.

It is a screen pushed over the list rather than a mode beside it, so that
the list stays where the diary opens and locking pops this along with
everything else. Which day the cursor is on is read off it by the list on
the way back -- see EntryListScreen.action_calendar.

Responsibilities:
    - Lay out the year the cursor is in, three to six months across as the
      terminal allows (app.tcss, keyed on the breakpoint classes below).
    - 'e' or enter opens the day under the cursor in the editor, whether
      or not it has been written -- the editor decides which it is, as it
      does from everywhere else.
    - '[' and ']' go to the same day a year either side. The day, week and
      month keys are the YearCalendar's own, and cross into the next year
      by themselves.
    - On every return from the editor, re-read which days are written, so
      a day just written has its mark.
"""

from __future__ import annotations

import datetime as dt
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Center
from textual.widgets import Label

from zecret.screens.base import ZecretScreen, card, count_entries, today
from zecret.screens.calendar import LEGEND, MONTH_WIDTH, YearCalendar, reachable
from zecret.screens.editor import EditorScreen
from zecret.screens.header import DiaryFooter, DiaryHeader

#: Columns between two months side by side, matching grid-gutter in
#: app.tcss.
MONTH_GAP = 2

#: Columns around the year that are not months: the card's margin and
#: padding (2 a side each, the gutter every full-width screen shares) and
#: the two its scrollbar takes. Those are counted whether or not the year
#: needs scrolling, because the card always reserves them -- see
#: `scrollbar-gutter` on #year-box in app.tcss. A scrollbar that came and
#: went would make the right count depend on the terminal's height, which
#: a width breakpoint cannot see, and would nudge the centred year sideways
#: as it appeared.
CHROME = 2 * 2 + 2 * 2 + 2


def needs(months: int) -> int:
    """The narrowest terminal that holds `months` months side by side."""
    return months * MONTH_WIDTH + (months - 1) * MONTH_GAP + CHROME


class CalendarScreen(ZecretScreen):
    """A year at a time, walked by day, week, month and year."""

    #: Which months-across class the screen wears at a given width. Five is
    #: skipped: twelve months in rows of five leave a ragged last row of two,
    #: and the extra width is better spent waiting for six, which is the
    #: year in two even rows. Three is what an 80-column terminal gets.
    #:
    #: Unannotated, and ruff's ClassVar rule waived: Textual declares this
    #: as an instance attribute on Screen, so the ClassVar ruff asks for is
    #: one mypy refuses as an override.
    HORIZONTAL_BREAKPOINTS = [  # noqa: RUF012
        (0, "-months-1"),
        (needs(2), "-months-2"),
        (needs(3), "-months-3"),
        (needs(4), "-months-4"),
        (needs(6), "-months-6"),
    ]

    #: Reading order, as everywhere: what this view is for, how to leave it,
    #: then the keys every main screen shares, then getting around.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("e", "edit_day", "Edit"),
        # The list opens a day with enter, so this one does too. 'e' is the
        # one in the bar: enter is what a calendar is expected to answer to
        # and needs no advertising, while 'e' is the key this view adds.
        Binding("enter", "edit_day", "Edit", show=False),
        Binding("c", "back", "List"),
        Binding("escape", "back", "List", show=False),
        # Shown, for the same reason as on the list -- see EntryListScreen.
        Binding("ctrl+l", "lock", "Lock"),
        # The app's rather than this screen's, so the popup is opened from
        # one place for both main views -- see ZecretApp.action_help.
        Binding("question_mark", "app.help", "Help", key_display="?"),
        Binding("q", "app.quit", "Quit"),
        # --- getting around ----------------------------------------------
        # On the screen rather than the widget, unlike the day and month
        # keys: an arrow key in a calendar needs no explaining, a bracket
        # does, and the help popup and the bar are built from screen
        # bindings. In the bar as well, since it has the room -- these make
        # seven keys in 63 columns, where the list's eight take 69 -- and a
        # year key nobody finds leaves the arrows to walk there instead.
        Binding("left_square_bracket", "previous_year", "Previous year", key_display="["),
        Binding("right_square_bracket", "next_year", "Next year", key_display="]"),
    ]

    def __init__(self, date: dt.date | None = None) -> None:
        """Args:
        date: The day to start on -- the one highlighted in the list, so
            the view opens on the year being read. Today, if not given.
        """
        super().__init__()
        self.start = date
        #: The day the cursor is on, which the list lands near on the way
        #: back. A plain copy rather than a look into the YearCalendar: the
        #: list reads it as this screen is being torn down, and by then the
        #: widget may already be gone from the DOM -- Textual removes a
        #: popped screen in a task of its own, unordered against the list's
        #: resume. Set properly on mount; this is only until then.
        self.date = reachable(today() if date is None else date)
        # The year the header was last worded for, so that a move within
        # it does not recount the diary -- see show_year.
        self.shown_year: int | None = None

    def compose(self) -> ComposeResult:
        yield DiaryHeader()
        with card("year-box"):
            yield Label("", id="year-title")
            # Centred in a container of its own rather than by the card:
            # Textual does not align the children of a container that
            # scrolls, and in most terminals this one does.
            with Center():
                yield YearCalendar(self.start, self.written, id="year")
            yield Label(LEGEND, id="year-legend")
        yield DiaryFooter()

    def on_mount(self) -> None:
        # Without the scroll: focusing a widget brings it into view, and
        # the top of the year is the row *under* the year's own title, so
        # the view opened with its heading scrolled off. Where the view
        # sits is reveal_cursor's to decide, once the grid has a layout.
        self.calendar.focus(scroll_visible=False)
        self.date = self.calendar.date
        self.show_year()
        self.call_after_refresh(self.reveal_cursor)

    def on_screen_resume(self) -> None:
        """Back from the editor: mark whatever was written there.

        Also fires as the screen is first shown, a moment after compose
        drew the year from this same diary -- so the year is redrawn only
        when the written days actually differ from what it holds, which
        rules out the first showing and a day that was opened and left
        alone. Comparing the sets is a pass over the diary; drawing twelve
        months for nothing was the cost worth avoiding.

        Skipped while locking, which pops this screen with the diary
        already on its way out -- see EntryListScreen.
        """
        if not self.zecret.is_unlocked:
            return
        written = self.written
        if written != self.calendar.written:
            self.calendar.set_written(written)
            self.show_year(recount=True)

    @property
    def calendar(self) -> YearCalendar:
        return self.query_one("#year", YearCalendar)

    @property
    def written(self) -> frozenset[dt.date]:
        """Every day the diary holds an entry for, as of now."""
        diary, _ = self.zecret.unlocked
        return frozenset(diary.entries)

    def show_year(self, recount: bool = False) -> None:
        """Name the year on show, and how much of it is written.

        Counting is a pass over every day the diary holds, and the count
        only changes with the year or with the diary -- so a move within
        the year, which is nearly every keypress, leaves the header alone
        unless `recount` says the diary changed.
        """
        year = self.date.year
        if year == self.shown_year and not recount:
            return
        self.shown_year = year
        count = sum(1 for date in self.calendar.written if date.year == year)
        self.query_one("#year-title", Label).update(str(year))
        self.sub_title = f"Calendar · {year} · {count_entries(count)}"

    def on_year_calendar_date_changed(self, event: YearCalendar.DateChanged) -> None:
        self.date = event.date
        self.show_year()
        self.reveal_cursor()

    def reveal_cursor(self) -> None:
        """Scroll the month the cursor is in into sight.

        In a terminal too short for the whole year, walking down out of the
        months on show would otherwise leave the cursor drawn where nobody
        can see it. Done here rather than in the widget because the card is
        this screen's, and so is what sits around the year inside it: in
        the top row of months the view goes right to the top, so the
        year's title comes with it, and in the bottom row right to the
        foot, so the legend does. Anywhere between, just far enough.
        """
        months = self.calendar.months
        month = self.calendar.cursor_month
        box = self.query_one("#year-box")
        if month.region.y <= months[0].region.y:
            box.scroll_home(animate=False, immediate=True)
        elif month.region.y >= months[-1].region.y:
            box.scroll_end(animate=False, immediate=True)
        else:
            box.scroll_to_widget(month, animate=False, immediate=True)

    # --- actions -----------------------------------------------------------

    def action_edit_day(self) -> None:
        """Open the day under the cursor -- written or not, the editor knows."""
        self.app.push_screen(EditorScreen(self.date))

    def action_back(self) -> None:
        self.dismiss()

    def action_lock(self) -> None:
        self.zecret.lock()

    def action_previous_year(self) -> None:
        self.calendar.previous_year()

    def action_next_year(self) -> None:
        self.calendar.next_year()
