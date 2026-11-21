"""Months laid out, with the days already written marked.

Textual ships no calendar, so these are Zecret's own. The mark against
each written day is the point: it shows which days were missed.

MonthCalendar is one month, inside the which-day modal. YearCalendar is
twelve of them and is the whole of the calendar view. They draw a month
through the same module functions and share every key but the arrows. In
the year the arrows move to the cell drawn in that direction
(spatial_step); in the single month, by day and week.

They are widgets, and their keys are their own: the help popup and the key
bar are built from screen bindings and do not list arrow keys.

Three things neither will do:

- Land on a day that has not happened. A move in time clamps to today, so
  no such key is dead. A move across the year's grid, and a click in
  either calendar, refuses instead: clamping there would send the cursor
  to a cell nobody pointed at. The exception is MonthCalendar.show, for a
  date typed into the field, which the field itself refuses.
- Change the month shown on its own. The month is wherever the cursor is.
- Own the date. The widget posts what it is on and the screen decides.

Weeks start on Monday, matching ISO dates.
"""

from __future__ import annotations

import calendar
import datetime as dt
from functools import cache
from typing import ClassVar

from rich.text import Text
from textual import events
from textual.app import ComposeResult, RenderResult
from textual.binding import Binding, BindingType
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from zecret.screens.base import format_month, today

#: Columns a day takes: three for the number, one for the mark. The mark
#: is inside the cell so every day is the same width.
CELL = 4

#: Rows of days, always six, so the grid does not change height from one
#: month to the next.
WEEKS = 6

#: Days in a week, which is also how wide the grid is in cells.
DAYS = 7

#: Drawn beside a written day. A glyph, not colour alone, so the marks
#: survive where the accent colour does not.
WRITTEN = "•"

#: Said under the grid by CalendarLegend, beside a sample of today's mark.
LEGEND = f"{WRITTEN} a day you have written"

#: Between the two halves of the legend.
LEGEND_GAP = "   "


def day_in(year: int, month: int, day: int) -> dt.date:
    """That day of that month, or the month's last day where it is shorter."""
    return dt.date(year, month, min(day, calendar.monthrange(year, month)[1]))


def shift_month(date: dt.date, months: int) -> dt.date:
    """`date` moved `months` months, keeping the day of the month where it
    can and clamping to the end of a shorter month."""
    index = date.year * 12 + (date.month - 1) + months
    year, month = divmod(index, 12)
    if not dt.MINYEAR <= year <= dt.MAXYEAR:
        # Past the range of a date: stay put.
        return date
    return day_in(year, month + 1, date.day)


def month_weeks(year: int, month: int) -> list[list[int]]:
    """A month as six rows of day numbers, 0 where the month is not.

    Monday first, padded to WEEKS rows.
    """
    rows = calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)
    return rows + [[0] * DAYS for _ in range(WEEKS - len(rows))]


def day_role(date: dt.date, cursor: dt.date, written: frozenset[dt.date], now: dt.date) -> str:
    """Which component class a day is drawn in, where `now` is today.

    Most specific first: the cursor beats everything, and a day that
    cannot be chosen beats being written.

    Today is not a role. It is laid over whichever role applies; see
    draw_month.

    `now` is passed in so a whole month is drawn against one reading of
    the clock.
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

    `widget` is where the colours are read from and must carry the
    month-calendar component classes. `cell` is how many columns a day
    takes, the last of them for the mark.
    """
    # Looked up once, not per cell.
    ink = {name: widget.get_component_rich_style(name) for name in COMPONENT_CLASSES}
    # Partial, so today's style adds only what its rule sets and leaves the
    # role's colour alone.
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
                # A neighbouring month's day: left blank.
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
    """`date`, or today if `date` is later."""
    return min(date, today())


def stepped(date: dt.date, days: int) -> dt.date:
    """`date` moved `days` days, clamped at both ends of what can be chosen.

    The far end is today. The near end is date.min, where subtracting a
    timedelta raises OverflowError.
    """
    try:
        target = date + dt.timedelta(days=days)
    except OverflowError:
        target = dt.date.min
    return reachable(target)


def day_at(first: dt.date, x: int, y: int, cell: int) -> dt.date | None:
    """The day drawn at a point in the month `first` falls in, if any.

    `y` includes the two heading rows; `x` is in columns, `cell` to a day.
    The headings and the blank padding answer None.
    """
    row = y - 2
    column = x // cell
    if not (0 <= row < WEEKS and 0 <= column < DAYS):
        return None
    day = month_weeks(first.year, first.month)[row][column]
    return None if day == 0 else first.replace(day=day)


#: The component classes both calendars share, so one set of rules in
#: app.tcss paints both.
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
    """What both calendars share: a cursor, and the keys that walk it.

    A day, a week, a month and the ends of a month, each clamped by
    stepped() and reachable(). YearCalendar replaces the four arrows.
    Textual merges BINDINGS down the class hierarchy, so a subclass lists
    only what it adds or replaces.
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
        """Put the cursor on `date`, clamped to today."""
        self.date = reachable(date)

    def step(self, days: int) -> None:
        """Move `days` days, clamped at both ends."""
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


class CalendarLegend(Widget):
    """What the marks on a calendar mean: the written days, and today.

    Today is shown by drawing its own date with the same component class
    the grids use, so the legend cannot drift from the grid.
    """

    COMPONENT_CLASSES: ClassVar[set[str]] = {"month-calendar--today"}

    DEFAULT_CSS = """
    CalendarLegend {
        height: auto;
    }
    """

    def render(self) -> RenderResult:
        landmark = self.get_component_rich_style("month-calendar--today", partial=True)
        text = Text(LEGEND + LEGEND_GAP)
        text.append(str(today().day), landmark)
        text.append(" today")
        return text


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
        written: Every day the diary holds an entry for. The whole set,
            since the month on show changes and the widget does not ask
            the diary.
        id: The widget's id.
        """
        super().__init__(id=id)
        self.written = written
        if date is not None:
            # set_reactive, not assignment: before mounting, a watcher
            # would post a DateChanged nobody is listening for.
            self.set_reactive(MonthCalendar.date, reachable(date))

    # --- what it draws -----------------------------------------------------

    def render(self) -> RenderResult:
        return draw_month(self, self.date, self.date, self.written, CELL, format_month(self.date))

    def watch_date(self, date: dt.date) -> None:
        self.refresh()
        self.post_message(self.DateChanged(date))

    def show(self, date: dt.date) -> None:
        """Move the cursor there without announcing it.

        For the field above, which is part way through being typed into.
        DateChanged is answered by writing the date into the field, which
        would complete a half-typed date under the writer's cursor.

        Not clamped, unlike every other move. A future date typed into the
        field is the field's to refuse, and showing it keeps the day
        highlighted and the day refused the same day.
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

        It does not choose the day; Enter does. A day not yet come is
        refused rather than clamped to today.
        """
        offset = event.get_content_offset(self)
        if offset is None:
            return
        date = self.date_at(offset.x - self.grid_left, offset.y)
        if date is not None and date <= today():
            self.focus()
            self.move_to(date)

    @property
    def grid_left(self) -> int:
        """Columns from the widget's left edge to where the month is drawn.

        app.tcss centres the month in a widget as wide as the card, so a
        click's offset into the widget is not an offset into the month.
        Read from the widget's own alignment so it follows the stylesheet.
        Textual puts the odd column of a centring on the right, which
        floor division matches.
        """
        spare = max(0, self.content_region.width - CELL * DAYS)
        align = self.styles.content_align_horizontal
        if align == "center":
            return spare // 2
        return spare if align == "right" else 0

    def date_at(self, x: int, y: int) -> dt.date | None:
        """The day drawn at a point in the month, `x` counted from the
        month's own left edge."""
        return day_at(self.date, x, y, CELL)


# --- a year ----------------------------------------------------------------

#: Columns a day takes in the year view: two for the number and one for the
#: mark. One fewer than the modal's, which is what fits three months across
#: an 80-column terminal.
YEAR_CELL = 3

#: How wide one month is in the year view. app.tcss sizes the grid columns
#: to it and CalendarScreen counts how many fit across.
MONTH_WIDTH = YEAR_CELL * DAYS


#: (x, y) on the year's grid of days. x counts day columns across every
#: month in a row of months; y counts week rows down every row of months.
Cell = tuple[int, int]


@cache
def year_layout(year: int, across: int) -> tuple[dict[dt.date, Cell], dict[Cell, dt.date]]:
    """Where every day of `year` sits with `across` months side by side.

    The arrangement app.tcss draws: months fill rows of `across`, each
    seven columns wide and WEEKS deep. The gutters between months take no
    cells.

    Returned both ways round. Cached, since every arrow press asks.
    """
    cells: dict[dt.date, Cell] = {}
    for month in range(1, 13):
        band, column = divmod(month - 1, across)
        for row, week in enumerate(month_weeks(year, month)):
            for weekday, day in enumerate(week):
                if day:
                    cells[dt.date(year, month, day)] = (
                        column * DAYS + weekday,
                        band * WEEKS + row,
                    )
    return cells, {cell: date for date, cell in cells.items()}


def spatial_step(date: dt.date, dx: int, dy: int, across: int, now: dt.date) -> dt.date | None:
    """The day in the next cell that way from `date`, as the year is drawn.

    One of `dx` and `dy` is 1 or -1 and the other 0. Blank cells are passed
    over, so the move lands on the nearest day in that direction: right
    from a month's last day continues into the month beside it, and down
    from its last week into the month below.

    None means stay put: the edge of the year is in the way, or the day
    there has not happened yet.
    """
    cells, days = year_layout(date.year, across)
    x, y = cells[date]
    if dx:
        candidates = [cx for (cx, cy) in days if cy == y and (cx - x) * dx > 0]
        if not candidates:
            return None
        target = days[(min(candidates, key=lambda cx: abs(cx - x)), y)]
    else:
        candidates = [cy for (cx, cy) in days if cx == x and (cy - y) * dy > 0]
        if not candidates:
            return None
        target = days[(x, min(candidates, key=lambda cy: abs(cy - y)))]
    return None if target > now else target


class MonthGrid(Widget):
    """One month of the twelve in a YearCalendar. Draws; owns nothing.

    The cursor, the year and the written days belong to the YearCalendar,
    which hands them down with show(). One cursor walks the year, so focus
    never changes hands at the end of a month.
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
        # Titled with the month alone; the year is the screen's heading.
        return draw_month(
            self, self.first, self.cursor, self.written, YEAR_CELL, f"{self.first:%B}"
        )

    def on_click(self, event: events.Click) -> None:
        """Say which day was clicked, if a day was."""
        offset = event.get_content_offset(self)
        if offset is None:
            return
        date = day_at(self.first, offset.x, offset.y, YEAR_CELL)
        if date is not None:
            self.post_message(self.DayClicked(date))


class YearCalendar(WalkableCalendar):
    """A year of months, one cursor walking through all of them.

    A grid of twelve MonthGrids. How many sit side by side is app.tcss's
    decision, from the `-months-N` class CalendarScreen sets; nothing here
    measures the terminal.

    The arrows are spatial: each moves to the cell drawn in that
    direction, so down from the last week of January is the month drawn
    below it, whatever month that is at this width. They stop at the edge
    of the year and refuse a day not yet come; see spatial_step. How many
    months are across is read from the grid's resolved style, so the
    arrows walk what the stylesheet drew.

    The other keys are WalkableCalendar's and move in time. The year keys
    are CalendarScreen's.
    """

    #: The arrows, replacing WalkableCalendar's day-and-week moves.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left", "move_left", "Left", show=False),
        Binding("right", "move_right", "Right", show=False),
        Binding("up", "move_up", "Up", show=False),
        Binding("down", "move_down", "Down", show=False),
    ]

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
        written: Every day the diary holds an entry for; see set_written
            for when that changes.
        id: The widget's id.
        """
        super().__init__(id=id)
        self.written = written
        # set_reactive, as in MonthCalendar: nothing is listening yet.
        self.set_reactive(YearCalendar.date, reachable(today() if date is None else date))

        # Kept rather than queried: the months are fixed for the widget's
        # life.
        self.months = [
            MonthGrid(self.date.replace(month=month, day=1), self.date, self.written)
            for month in range(1, 13)
        ]

    def compose(self) -> ComposeResult:
        yield from self.months

    def redraw(self, *months: MonthGrid) -> None:
        """Hand `months` (all of them, if none is named) what they need to
        draw themselves now."""
        for grid in months or self.months:
            first = self.date.replace(month=grid.first.month, day=1)
            grid.show(first, self.date, self.written)

    def set_written(self, written: frozenset[dt.date]) -> None:
        """Mark a new set of written days."""
        self.written = written
        self.redraw()

    def watch_date(self, old: dt.date, new: dt.date) -> None:
        """Redraw what the move changed, and say where the cursor is now.

        Within a year only the month the cursor left and the one it
        entered are redrawn. A new year redraws all twelve. A month the
        cursor is not in may hold a stale cursor date, which is harmless:
        a month only draws its own days.
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

    @property
    def across(self) -> int:
        """How many months the stylesheet has laid side by side."""
        return max(1, self.styles.grid_size_columns)

    def move(self, dx: int, dy: int) -> None:
        """One cell that way, or nowhere; see spatial_step."""
        target = spatial_step(self.date, dx, dy, self.across, today())
        if target is not None:
            self.date = target

    def action_move_left(self) -> None:
        self.move(-1, 0)

    def action_move_right(self) -> None:
        self.move(1, 0)

    def action_move_up(self) -> None:
        self.move(0, -1)

    def action_move_down(self) -> None:
        self.move(0, 1)

    def previous_year(self) -> None:
        """The same day a year earlier, or the 28th from a 29 February."""
        self.move_to(shift_month(self.date, -12))

    def next_year(self) -> None:
        """The same day a year later, or today if that has not come yet."""
        self.move_to(shift_month(self.date, 12))

    def on_month_grid_day_clicked(self, event: MonthGrid.DayClicked) -> None:
        """Go to the day clicked, unless it has not happened yet.

        Refused rather than clamped, as the arrows refuse.
        """
        event.stop()
        if event.date > today():
            return
        self.focus()
        self.move_to(event.date)
