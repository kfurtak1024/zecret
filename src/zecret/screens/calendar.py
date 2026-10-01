"""Months laid out, with the days already written marked.

Textual ships no calendar, so these are Zecret's own: a grid of a month
that can be walked with the arrow keys, pages a month at a time, and draws
a mark against every day the diary already holds an entry for. That mark is
the reason it exists. A date typed into a field answers "which day did I
mean"; only a month laid out can answer "which days have I missed", which
is the question someone filling a diary in actually has.

Two widgets share it. MonthCalendar is one month, inside the which-day
modal. YearCalendar is twelve of them at once, and is the whole of the
calendar view: a year is the span over which the gaps in a diary show. They
draw a month the same way and walk the days by the same rules, which is
why both live here and why the drawing and the walking are functions
rather than methods of either.

They are widgets rather than screens, and their keys are their own for the
same reason DiaryTextArea's are: the help popup and the key bar are built from
*screen* bindings, and they document what Zecret does with a diary -- not
what arrow keys do inside a grid, which anyone who has used a calendar
already knows. See CLAUDE.md on that split.

Three things neither will do:

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
from textual.app import ComposeResult, RenderResult
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


def month_weeks(year: int, month: int) -> list[list[int]]:
    """A month as six rows of day numbers, 0 where the month is not.

    Padded to six rows so the grid is always the same height -- see
    WEEKS. Monday first, matching the ISO dates the field takes.
    """
    rows = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    return rows + [[0] * DAYS for _ in range(WEEKS - len(rows))]


def day_role(date: dt.date, cursor: dt.date, written: frozenset[dt.date], now: dt.date) -> str:
    """Which component class a day is drawn in, where `now` is today.

    Most specific first, and the order is the argument: where the cursor is
    beats everything, because losing it in a month of marked days would
    leave the arrow keys with nothing to show for themselves, and a day
    that cannot be chosen beats how interesting it is, because it is not on
    offer whatever else is true of it.

    Today is not in this list. It is a fact about a day rather than a way
    of drawing one -- today is very often also the day the cursor is on and
    the day you last wrote -- so it is laid over whichever of these applies
    instead of competing with them. See draw_month.

    `now` is passed in rather than asked for, so that a month is drawn
    against one reading of the clock: asked per day, it was two readings a
    cell and a thousand for a year, and a draw that ran across midnight
    could call one day both today and not yet happened.
    """
    if date == cursor:
        return "month-calendar--cursor"
    if date > now:
        return "month-calendar--unavailable"
    if date in written:
        return "month-calendar--written"
    return "month-calendar--day"


def draw_month(
    widget: Widget,
    first: dt.date,
    cursor: dt.date,
    written: frozenset[dt.date],
    cell: int,
    title: str,
) -> Text:
    """The month `first` falls in, as the eight lines of text it is drawn as.

    `widget` is what the colours are read from -- it must carry the
    month-calendar component classes -- and `cell` is how many columns a
    day takes, the last of them for the mark. The modal has room for four;
    the year view has three, because four would put a year's twelve months
    past an eighty-column terminal at any arrangement worth having.
    """
    # Looked up once rather than per cell: there are forty-two of them and
    # six answers between them.
    ink = {name: widget.get_component_rich_style(name) for name in COMPONENT_CLASSES}
    # Today's is laid over whatever else the day is drawn in rather than
    # replacing it -- see day_role. Partial, so it contributes only what its
    # rule actually sets and leaves the colour alone.
    landmark = widget.get_component_rich_style("month-calendar--today", partial=True)
    digits = cell - 1
    now = today()

    lines = [
        Text(title.center(cell * DAYS), style=ink["month-calendar--month"]),
        Text(
            "".join(f"{calendar.day_abbr[day][:2]:>{digits}} " for day in range(DAYS)),
            style=ink["month-calendar--heading"],
        ),
    ]
    for week in month_weeks(first.year, first.month):
        line = Text()
        for day in week:
            if day == 0:
                # A day of the month either side of this one. Left blank
                # rather than greyed in: the grid is read for which days of
                # *this* month are marked, and a neighbour's dates in it are
                # two more things to discount.
                line.append(" " * cell)
                continue
            date = first.replace(day=day)
            mark = WRITTEN if date in written else " "
            style = ink[day_role(date, cursor, written, now)]
            if date == now:
                style = style + landmark
            line.append(f"{day:>{digits}}{mark}", style)
        lines.append(line)
    return Text("\n").join(lines)


def reachable(date: dt.date) -> dt.date:
    """`date`, or today if that is further off.

    Clamped rather than refused, so that no key in a calendar is ever dead:
    the month after this one is a page away whether or not it has happened,
    and the honest answer to paging into it is the last day there is.
    """
    return min(date, today())


def stepped(date: dt.date, days: int) -> dt.date:
    """`date` moved `days` days, stopping at either end of what can be chosen.

    The far end is today, which reachable() holds. This end is 1 January of
    year 1, where a day or a week back is out of range: `date - timedelta`
    raises OverflowError, and on a key handler that took the app down.
    Reaching it means typing year 0001 into the date field, or holding a
    year key down for a very long time, but a key that crashes is worse
    than a key that stops. Clamped rather than left alone, the same as the
    far end, so a week back from the 3rd still gets as far as the 1st.
    """
    try:
        target = date + dt.timedelta(days=days)
    except OverflowError:
        target = dt.date.min
    return reachable(target)


def day_at(first: dt.date, x: int, y: int, cell: int) -> dt.date | None:
    """The day drawn at a point in the month `first` falls in, if any.

    `y` counts the two heading rows the month is drawn under, and `x` is in
    cells of `cell` columns. Padding around the month -- the days of the
    neighbouring months, which the grid leaves blank -- is not a day and
    answers None, as does a click on the headings.
    """
    row = y - 2
    column = x // cell
    if not (0 <= row < WEEKS and 0 <= column < DAYS):
        return None
    day = month_weeks(first.year, first.month)[row][column]
    return None if day == 0 else first.replace(day=day)


#: How a month is drawn, which both widgets share: the class names are the
#: same on each, so one set of rules in app.tcss paints them both.
COMPONENT_CLASSES: frozenset[str] = frozenset(
    {
        "month-calendar--month",
        "month-calendar--heading",
        "month-calendar--day",
        "month-calendar--written",
        "month-calendar--today",
        "month-calendar--cursor",
        "month-calendar--unavailable",
    }
)


class WalkableCalendar(Widget, can_focus=True):
    """What every calendar here shares: a cursor, and the keys that walk it.

    A day, a week, a month and the ends of a month, each clamped the same
    way -- see stepped and reachable. MonthCalendar and YearCalendar both
    walk by these and differ only in what they draw and what they say about
    it, which is why the keys are written once, here, rather than once per
    calendar: two copies of a key map are two places for a fix to miss.

    Textual merges BINDINGS down the class hierarchy, so a subclass lists
    only the keys it adds.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "previous_day", "Previous day", show=False),
        Binding("right", "next_day", "Next day", show=False),
        Binding("up", "previous_week", "Previous week", show=False),
        Binding("down", "next_week", "Next week", show=False),
        Binding("pageup", "previous_month", "Previous month", show=False),
        Binding("pagedown", "next_month", "Next month", show=False),
        Binding("home", "start_of_month", "Start of the month", show=False),
        Binding("end", "end_of_month", "End of the month", show=False),
    ]

    #: The day the cursor is on, and through it what is on show.
    date: reactive[dt.date] = reactive(today)

    def move_to(self, date: dt.date) -> None:
        """Put the cursor on `date`, or on today if that is further off --
        see reachable."""
        self.date = reachable(date)

    def step(self, days: int) -> None:
        """Move `days` days, stopping at either end -- see stepped."""
        self.date = stepped(self.date, days)

    def action_previous_day(self) -> None:
        self.step(-1)

    def action_next_day(self) -> None:
        self.step(1)

    def action_previous_week(self) -> None:
        self.step(-7)

    def action_next_week(self) -> None:
        self.step(7)

    def action_previous_month(self) -> None:
        self.move_to(shift_month(self.date, -1))

    def action_next_month(self) -> None:
        self.move_to(shift_month(self.date, 1))

    def action_start_of_month(self) -> None:
        self.move_to(self.date.replace(day=1))

    def action_end_of_month(self) -> None:
        last = calendar.monthrange(self.date.year, self.date.month)[1]
        self.move_to(self.date.replace(day=last))


class MonthCalendar(WalkableCalendar):
    """One month, walkable, with the written days marked."""

    COMPONENT_CLASSES: ClassVar[set[str]] = set(COMPONENT_CLASSES)

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "pick", "Choose this day", show=False),
    ]

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

    def render(self) -> RenderResult:
        return draw_month(self, self.date, self.date, self.written, CELL, format_month(self.date))

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
        """The day drawn at a point in the grid -- see day_at."""
        return day_at(self.date, x, y, CELL)


# --- a year ----------------------------------------------------------------

#: Columns a day takes in the year view: two for the number and one for the
#: mark. One fewer than the modal's, and that column is the whole reason a
#: year fits an 80-column terminal three months across -- see draw_month.
YEAR_CELL = 3

#: How wide one month is in the year view, which app.tcss sizes the grid
#: columns to and CalendarScreen counts how many fit across in.
MONTH_WIDTH = YEAR_CELL * DAYS


class MonthGrid(Widget):
    """One month of the twelve in a YearCalendar. Draws; owns nothing.

    The cursor, the year and the written days all belong to the
    YearCalendar around it, which hands them down with show(). That is
    what lets the cursor walk off the end of one month and into the next
    without focus changing hands twelve times a year: there is one cursor,
    and this is where a twelfth of it is drawn.
    """

    COMPONENT_CLASSES: ClassVar[set[str]] = set(COMPONENT_CLASSES)

    class DayClicked(Message):
        """A click landed on a day. For the YearCalendar, which moves to it."""

        def __init__(self, date: dt.date) -> None:
            super().__init__()
            self.date = date

    def __init__(self, first: dt.date, cursor: dt.date, written: frozenset[dt.date]) -> None:
        super().__init__()
        self.first = first
        self.cursor = cursor
        self.written = written

    def show(self, first: dt.date, cursor: dt.date, written: frozenset[dt.date]) -> None:
        """Draw this month as `first` names it, with the cursor and marks given."""
        self.first, self.cursor, self.written = first, cursor, written
        self.refresh()

    def render(self) -> RenderResult:
        # The month alone, not the year: the year is the screen's heading,
        # and twelve copies of it would be eleven more than anyone reads.
        return draw_month(
            self, self.first, self.cursor, self.written, YEAR_CELL, f"{self.first:%B}"
        )

    def on_click(self, event: events.Click) -> None:
        """Say which day was clicked, if a day was. See MonthCalendar.on_click
        for why that moves the cursor and stops short of opening the day."""
        offset = event.get_content_offset(self)
        if offset is None:
            return
        date = day_at(self.first, offset.x, offset.y, YEAR_CELL)
        if date is not None:
            self.post_message(self.DayClicked(date))


class YearCalendar(WalkableCalendar):
    """A year of months, one cursor walking through all of them.

    How many months sit side by side is not this widget's business: it is
    a grid of twelve MonthGrids, and app.tcss sizes the grid from the
    `-months-N` class CalendarScreen wears for the terminal's width. Nothing
    here measures the terminal, so nothing here has to be redone when it
    changes size.

    The keys are a calendar's -- WalkableCalendar's, the same as
    MonthCalendar's -- and here they continue across the edges of a month
    and of a year. Up and down move a week rather than to the month drawn
    above, because which month that is depends on how wide the window is,
    and a key whose meaning changes with the window is not a key anyone
    can learn. The year keys are the screen's, since they are what the
    help popup has to tell someone about -- see CalendarScreen.
    """

    class DateChanged(Message):
        """The cursor moved, and perhaps the year with it."""

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
        date: The day to start on, clamped to today. Today, if not given.
        written: Every day the diary holds an entry for -- see
            MonthCalendar, and set_written for when that changes.
        id: The widget's id, as for any other widget.
        """
        super().__init__(id=id)
        self.written = written
        # set_reactive, as in MonthCalendar: nothing is listening yet.
        self.set_reactive(YearCalendar.date, reachable(today() if date is None else date))

        # Kept rather than queried: the months are fixed for the widget's
        # life, and every move asks for one or two of them.
        self.months = [
            MonthGrid(self.date.replace(month=month, day=1), self.date, self.written)
            for month in range(1, 13)
        ]

    def compose(self) -> ComposeResult:
        yield from self.months

    def redraw(self, *months: MonthGrid) -> None:
        """Hand `months` -- every month, if none is named -- what they need
        to draw themselves now."""
        for grid in months or self.months:
            first = self.date.replace(month=grid.first.month, day=1)
            grid.show(first, self.date, self.written)

    def set_written(self, written: frozenset[dt.date]) -> None:
        """Mark a new set of written days -- after an entry was saved, say."""
        self.written = written
        self.redraw()

    def watch_date(self, old: dt.date, new: dt.date) -> None:
        """Redraw what the move changed, and say where the cursor is now.

        Within a year that is two months at most -- the one the cursor
        left and the one it arrived in -- and redrawing all twelve on every
        arrow press, held down, was ten times the work for nothing. A new
        year changes every month's dates, so all twelve are redrawn then.
        A month the cursor is not in keeps whichever cursor it was last
        handed, which is harmless: that day is in another month, and a
        month only draws its own days.
        """
        if old.year != new.year:
            self.redraw()
        else:
            self.redraw(self.months[old.month - 1], self.months[new.month - 1])
        self.post_message(self.DateChanged(new))

    @property
    def cursor_month(self) -> MonthGrid:
        """The month the cursor is in, for whoever scrolls the year."""
        return self.months[self.date.month - 1]

    # --- getting around ----------------------------------------------------

    def previous_year(self) -> None:
        """The same day a year earlier, or the 28th from a 29 February."""
        self.move_to(shift_month(self.date, -12))

    def next_year(self) -> None:
        """The same day a year later -- or today, if that has not come yet."""
        self.move_to(shift_month(self.date, 12))

    def on_month_grid_day_clicked(self, event: MonthGrid.DayClicked) -> None:
        event.stop()
        self.focus()
        self.move_to(event.date)
