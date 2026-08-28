"""A month at a time, with the days already written marked.

Textual ships no calendar, so this is one: a grid of a single month that
can be walked with the arrow keys, pages a month at a time, and draws a
mark against every day the diary already holds an entry for. That mark is
the reason it exists. A date typed into a field answers "which day did I
mean"; only a month laid out can answer "which days have I missed", which
is the question someone filling a diary in actually has.

It is a widget rather than a screen, and its keys are its own for the same
reason DiaryTextArea's are: the help popup and the key bar are built from
*screen* bindings, and they document what Zecret does with a diary -- not
what arrow keys do inside a grid, which anyone who has used a calendar
already knows. See CLAUDE.md on that split.

Three things it will not do:

- Land on a day that has not happened. Zecret refuses a future entry, so a
  cursor that could sit on one would be offering something the screen
  behind it is going to turn down. Movement clamps to today instead of
  refusing, so no key is ever dead: paging into next month lands on today.
- Change the month it shows on its own. The month is wherever the cursor
  is, so the grid only ever moves because someone moved it.
- Own the date. The field above it does; this posts what it is on and lets
  the screen decide, which is what keeps typing and pointing from fighting
  over which of them is right.

Weeks start on Monday, matching the ISO date the field is typed in.
"""

from __future__ import annotations

import calendar
import datetime as dt
from typing import ClassVar

from rich.text import Text
from textual import events
from textual.app import RenderResult
from textual.binding import Binding, BindingType
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from zecret.screens.base import format_month, today

#: Columns a day takes: three for the number, one for the mark beside it.
#: The mark rides in the cell rather than between cells so that every day
#: is the same width whether or not it has been written on.
CELL = 4

#: Rows of days, always six. February from a Monday needs four and a long
#: month from a Sunday needs six; drawing whichever a month happens to
#: want would resize the modal under the reader every time they paged.
WEEKS = 6

#: Days in a week, which is also how wide the grid is in cells.
DAYS = 7

#: Drawn beside a day the diary already holds an entry for. A glyph rather
#: than colour alone: the marked days are the whole point of the grid, and
#: a reader who cannot pick the accent out of the foreground would be left
#: with a plain calendar.
WRITTEN = "•"

#: Said under the grid, because the mark means nothing to someone meeting
#: it for the first time.
LEGEND = f"{WRITTEN} a day you have written"


def day_in(year: int, month: int, day: int) -> dt.date:
    """That day of that month, or its last day where the month is shorter.

    The clamp every caller here wants: a day of the month carried from
    somewhere else -- the month before, or a date half typed into a field
    -- has to land somewhere real, and the end of a short month is where
    the 31st belongs rather than a day into the next one.
    """
    return dt.date(year, month, min(day, calendar.monthrange(year, month)[1]))


def shift_month(date: dt.date, months: int) -> dt.date:
    """`date` moved `months` months, keeping the day of the month it can.

    The 31st of a month moved into a shorter one lands on that month's
    last day rather than overflowing into the next, which is what makes
    paging through a year from the 31st stay on the end of each month
    instead of drifting a day forward every February.
    """
    index = date.year * 12 + (date.month - 1) + months
    year, month = divmod(index, 12)
    if not dt.MINYEAR <= year <= dt.MAXYEAR:
        # Paged past the ends of what a date can even be. Nothing sensible
        # to show, so stay put.
        return date
    return day_in(year, month + 1, date.day)


class MonthCalendar(Widget, can_focus=True):
    """One month, walkable, with the written days marked."""

    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "month-calendar--month",
        "month-calendar--heading",
        "month-calendar--day",
        "month-calendar--written",
        "month-calendar--today",
        "month-calendar--cursor",
        "month-calendar--unavailable",
    }

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "previous_day", "Previous day", show=False),
        Binding("right", "next_day", "Next day", show=False),
        Binding("up", "previous_week", "Previous week", show=False),
        Binding("down", "next_week", "Next week", show=False),
        Binding("pageup", "previous_month", "Previous month", show=False),
        Binding("pagedown", "next_month", "Next month", show=False),
        Binding("home", "start_of_month", "Start of the month", show=False),
        Binding("end", "end_of_month", "End of the month", show=False),
        Binding("enter", "pick", "Choose this day", show=False),
    ]

    #: The day the cursor is on, which is also the month on show. Set from
    #: outside whenever the field above is typed into.
    date: reactive[dt.date] = reactive(today)

    class DateChanged(Message):
        """The cursor moved. Raised for the field, which follows it."""

        def __init__(self, date: dt.date) -> None:
            super().__init__()
            self.date = date

    class DatePicked(Message):
        """Enter on a day: this is the one."""

        def __init__(self, date: dt.date) -> None:
            super().__init__()
            self.date = date

    def __init__(
        self,
        date: dt.date | None = None,
        written: frozenset[dt.date] = frozenset(),
        id: str | None = None,
    ) -> None:
        """Args:
        date: The day to start on. Today, if not given.
        written: Every day the diary already holds an entry for. The whole
            set rather than the month's share of it, because the month on
            show changes and asking the diary again on every page would
            put the screen's business inside the widget.
        id: The widget's id, as for any other widget.
        """
        super().__init__(id=id)
        self.written = written
        if date is not None:
            # set_reactive rather than assignment: this runs before the
            # widget is mounted, and a watcher firing then would post a
            # DateChanged nobody is listening for yet.
            self.set_reactive(MonthCalendar.date, date)

    # --- what it draws -----------------------------------------------------

    @property
    def weeks(self) -> list[list[int]]:
        """The month as six rows of day numbers, 0 where the month is not.

        Padded to six rows so the grid is always the same height -- see
        WEEKS. Monday first, matching the ISO dates the field takes.
        """
        rows = calendar.Calendar(firstweekday=0).monthdayscalendar(self.date.year, self.date.month)
        return rows + [[0] * DAYS for _ in range(WEEKS - len(rows))]

    def render(self) -> RenderResult:
        # Looked up once rather than per cell: there are forty-two of them
        # and six answers between them.
        ink = {name: self.get_component_rich_style(name) for name in self.COMPONENT_CLASSES}
        heading = ink["month-calendar--heading"]
        # Today's is laid over whatever else the day is drawn in rather
        # than replacing it -- see style_for. Partial, so it contributes
        # only what its rule actually sets and leaves the colour alone.
        landmark = self.get_component_rich_style("month-calendar--today", partial=True)

        lines = [
            Text(
                format_month(self.date).center(CELL * DAYS),
                style=ink["month-calendar--month"],
            ),
            Text(
                "".join(f"{calendar.day_abbr[day][:2]:>3} " for day in range(DAYS)),
                style=heading,
            ),
        ]
        for week in self.weeks:
            line = Text()
            for day in week:
                if day == 0:
                    # A day of the month either side of this one. Left
                    # blank rather than greyed in: the grid is read for
                    # which days of *this* month are marked, and a
                    # neighbour's dates in it are two more things to
                    # discount.
                    line.append(" " * CELL)
                    continue
                date = self.date.replace(day=day)
                mark = WRITTEN if date in self.written else " "
                style = ink[self.style_for(date)]
                if date == today():
                    style = style + landmark
                line.append(f"{day:>3}{mark}", style)
            lines.append(line)
        return Text("\n").join(lines)

    def style_for(self, date: dt.date) -> str:
        """Which component class a day is drawn in.

        Most specific first, and the order is the argument: where the
        cursor is beats everything, because losing it in a month of marked
        days would leave the arrow keys with nothing to show for
        themselves, and a day that cannot be chosen beats how interesting
        it is, because it is not on offer whatever else is true of it.

        Today is not in this list. It is a fact about a day rather than a
        way of drawing one -- today is very often also the day the cursor
        is on and the day you last wrote -- so it is laid over whichever
        of these applies instead of competing with them. See render.
        """
        if date == self.date:
            return "month-calendar--cursor"
        if date > today():
            return "month-calendar--unavailable"
        if date in self.written:
            return "month-calendar--written"
        return "month-calendar--day"

    def watch_date(self, date: dt.date) -> None:
        self.refresh()
        self.post_message(self.DateChanged(date))

    def show(self, date: dt.date) -> None:
        """Move the cursor there without announcing it.

        For whoever already knows: the field above posts nothing back to
        itself, and it is mid-way through being typed into. An echo there
        would be worse than redundant -- DateChanged is answered by
        writing the date into the field, which would complete a date
        someone was still halfway through typing, under their cursor.

        Everything else about it is an ordinary move, and it is drawn the
        same way; what is skipped is only the telling.
        """
        if date == self.date:
            return
        self.set_reactive(MonthCalendar.date, date)
        self.refresh()

    # --- getting around ----------------------------------------------------

    def move_to(self, date: dt.date) -> None:
        """Put the cursor on `date`, or on today if that is further off.

        Clamped rather than refused, so that no key here is ever dead: the
        month after this one is a page away whether or not it has happened,
        and the honest answer to paging into it is the last day there is.
        """
        self.date = min(date, today())

    def action_previous_day(self) -> None:
        self.move_to(self.date - dt.timedelta(days=1))

    def action_next_day(self) -> None:
        self.move_to(self.date + dt.timedelta(days=1))

    def action_previous_week(self) -> None:
        self.move_to(self.date - dt.timedelta(weeks=1))

    def action_next_week(self) -> None:
        self.move_to(self.date + dt.timedelta(weeks=1))

    def action_previous_month(self) -> None:
        self.move_to(shift_month(self.date, -1))

    def action_next_month(self) -> None:
        self.move_to(shift_month(self.date, 1))

    def action_start_of_month(self) -> None:
        self.move_to(self.date.replace(day=1))

    def action_end_of_month(self) -> None:
        last = calendar.monthrange(self.date.year, self.date.month)[1]
        self.move_to(self.date.replace(day=last))

    def action_pick(self) -> None:
        self.post_message(self.DatePicked(self.date))

    # --- the mouse ---------------------------------------------------------

    def on_click(self, event: events.Click) -> None:
        """A click moves the cursor to the day under it, and no further.

        Not straight through to opening the day, which is what a click on
        a row of the entry list does: a list row is a thing you asked for,
        and a calendar cell is one of forty-two an unsteady hand can land
        on. Enter is what chooses, from either the grid or the field.
        """
        offset = event.get_content_offset(self)
        if offset is None:
            return
        date = self.date_at(offset.x, offset.y)
        if date is not None:
            self.focus()
            self.move_to(date)

    def date_at(self, x: int, y: int) -> dt.date | None:
        """The day drawn at a point in the grid, if a day is drawn there.

        `y` counts the two heading rows the month is drawn under, and `x`
        is in cells of CELL columns. Padding around the month -- the days
        of the neighbouring months, which this grid leaves blank -- is not
        a day and answers None, as does a click on the headings.
        """
        row = y - 2
        column = x // CELL
        if not (0 <= row < WEEKS and 0 <= column < DAYS):
            return None
        day = self.weeks[row][column]
        return None if day == 0 else self.date.replace(day=day)
