"""Tests for the calendar widgets: MonthCalendar, the month grid inside the
which-day modal, and YearCalendar, the twelve of them the calendar view is.

The widget is Zecret's own -- Textual ships no calendar -- so everything
about it is worth guarding, including the parts a calendar library would
normally have got right for us.

Required coverage:
    - A month is laid out Monday-first, always six rows deep whatever
      shape the month is, with every day of it in the grid exactly once.
    - Days the diary has an entry for are drawn differently from days it
      does not, and today is drawn over whatever else it happens to be.
    - The cursor moves by day, by week and by month, and reaches the two
      ends of the month.
    - It never lands on a day that has not happened: movement clamps to
      today rather than refusing, so no key is dead. The other end clamps
      too: a day or a week back from the first day a date can be stops
      there instead of overflowing, which used to crash the app.
    - Paging a month keeps the day of the month where the month it lands
      in is long enough, and stops at that month's last day where it is
      not. Paging off the ends of what a date can be leaves it alone.
    - Moving posts DateChanged; enter posts DatePicked. Moving through
      show() posts nothing, which is what lets the field above drive the
      grid while it is being typed into.
    - A click lands the cursor on the day under it, and a click on the
      headings or on the blank around a month does nothing.

    YearCalendar, over and above what the two share:
    - It draws the twelve months of the year the cursor is in, each named
      without the year, at three columns a day so that three of them fit
      an 80-column terminal.
    - The arrows move to the cell drawn in that direction, however many
      months sit across: across the edge of a month into the one beside or
      below it, over the blank cells around a month, and nowhere at all at
      the edge of the year or into a day not yet come. Within a month that
      is the same as a day or a week. The page, home and end keys still
      move in time, and the year on show follows the cursor.
    - A year either way keeps the day, clips 29 February to the 28th, and
      clamps to today going forward like every other move.
    - It never starts, or lands, on a day that has not happened.
    - A new set of written days is drawn as soon as it is handed over.
    - A click on a day in any month moves the cursor there; a click on a
      day not yet come does nothing, as the arrows do nothing there.
    - A move within the year redraws only the months it touched; a move
      into another year redraws all twelve.
    - Both calendars share one key map, WalkableCalendar's, and the year
      replaces only its arrows.
    - The year's cursor is drawn solid while the year has focus and soft
      while it does not. The rule is keyed on the year and the cursor is
      painted by a month inside it, so this checks what reaches the screen
      rather than trusting the stylesheet.
"""

from __future__ import annotations

import calendar
import datetime as dt
from pathlib import Path

import pytest
from textual.app import App, ComposeResult

import zecret
from zecret.screens.calendar import (
    DAYS,
    MONTH_WIDTH,
    WEEKS,
    MonthCalendar,
    MonthGrid,
    WalkableCalendar,
    YearCalendar,
    day_in,
    day_role,
    month_weeks,
    shift_month,
    spatial_step,
    year_layout,
)

TODAY = dt.date.today()
YESTERDAY = TODAY - dt.timedelta(days=1)
TOMORROW = TODAY + dt.timedelta(days=1)
#: Far enough back that a year forward is still in the past for most of
#: it -- but not this one, whose year forward is a few days from now.
LAST_YEAR_AND_A_BIT = shift_month(TODAY, -12) + dt.timedelta(days=3)

#: A month in the past with a known shape: August 2020 starts on a
#: Saturday and runs 31 days, so its grid needs six rows and its first row
#: is nearly all padding.
AUGUST = dt.date(2020, 8, 13)


class CalendarHarness(App[None]):
    """Bare app holding one calendar, and recording what it says."""

    def __init__(
        self,
        date: dt.date | None = None,
        written: frozenset[dt.date] = frozenset(),
    ) -> None:
        super().__init__()
        self.calendar = MonthCalendar(date, written, id="cal")
        self.changes: list[dt.date] = []
        self.picked: list[dt.date] = []

    def compose(self) -> ComposeResult:
        yield self.calendar

    def on_mount(self) -> None:
        self.calendar.focus()

    def on_month_calendar_date_changed(self, event: MonthCalendar.DateChanged) -> None:
        self.changes.append(event.date)

    def on_month_calendar_date_picked(self, event: MonthCalendar.DatePicked) -> None:
        self.picked.append(event.date)


# --- the shape of a month --------------------------------------------------


def test_a_month_is_always_six_rows_of_seven():
    """Whatever the month, so that paging does not resize the modal."""
    for month in range(1, 13):
        grid = month_weeks(2026, month)
        assert len(grid) == WEEKS
        assert {len(row) for row in grid} == {DAYS}


def test_every_day_of_the_month_appears_once():
    grid = month_weeks(AUGUST.year, AUGUST.month)
    days = [day for row in grid for day in row if day]
    assert days == list(range(1, 32))


def test_weeks_start_on_monday():
    """August 2020 opens on a Saturday, so its first row is five blanks."""
    first = month_weeks(AUGUST.year, AUGUST.month)[0]
    assert first == [0, 0, 0, 0, 0, 1, 2]


# --- how a day is drawn ----------------------------------------------------


def test_a_written_day_is_drawn_differently_from_an_empty_one():
    written = frozenset({dt.date(2020, 8, 12)})
    assert day_role(dt.date(2020, 8, 12), AUGUST, written, TODAY) == "month-calendar--written"
    assert day_role(dt.date(2020, 8, 11), AUGUST, written, TODAY) == "month-calendar--day"


def test_the_cursor_outranks_everything_it_sits_on():
    """Losing the cursor in a month of marked days would leave the arrow
    keys with nothing to show for themselves."""
    written = frozenset({AUGUST})
    assert day_role(AUGUST, AUGUST, written, TODAY) == "month-calendar--cursor"


def test_a_day_that_has_not_happened_is_drawn_as_unavailable():
    role = day_role(TOMORROW, YESTERDAY, frozenset({TOMORROW}), TODAY)
    assert role == "month-calendar--unavailable"


def test_today_is_not_a_style_of_its_own():
    """It is laid over whatever the day already is -- see render. A day
    that is both today and written is still drawn as written."""
    assert day_role(TODAY, YESTERDAY, frozenset({TODAY}), TODAY) == "month-calendar--written"


def test_what_has_not_happened_is_judged_against_the_day_given():
    """One reading of the clock per month drawn, handed in -- so a draw
    that runs across midnight cannot judge two days by two clocks."""
    assert day_role(TODAY, YESTERDAY, frozenset(), YESTERDAY) == "month-calendar--unavailable"


# --- paging a month --------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (dt.date(2026, 8, 13), 1, dt.date(2026, 9, 13)),
        (dt.date(2026, 8, 13), -1, dt.date(2026, 7, 13)),
        (dt.date(2026, 1, 13), -1, dt.date(2025, 12, 13)),
        (dt.date(2026, 12, 13), 1, dt.date(2027, 1, 13)),
        # The day of the month is kept where it can be, and clipped where
        # it cannot -- rather than spilling into the following month.
        (dt.date(2026, 1, 31), 1, dt.date(2026, 2, 28)),
        (dt.date(2024, 1, 31), 1, dt.date(2024, 2, 29)),
        (dt.date(2026, 3, 31), -1, dt.date(2026, 2, 28)),
    ],
    ids=[
        "forward",
        "back",
        "back-over-new-year",
        "forward-over-new-year",
        "clipped-to-february",
        "clipped-to-a-leap-february",
        "back-into-a-short-month",
    ],
)
def test_shifting_a_month(start, months, expected):
    assert shift_month(start, months) == expected


@pytest.mark.parametrize(
    ("year", "month", "day", "expected"),
    [
        (2020, 8, 13, dt.date(2020, 8, 13)),
        (2020, 2, 31, dt.date(2020, 2, 29)),
        (2021, 2, 31, dt.date(2021, 2, 28)),
        (2020, 4, 31, dt.date(2020, 4, 30)),
    ],
    ids=["a-day-that-exists", "a-leap-february", "a-short-february", "a-thirty-day-month"],
)
def test_a_day_carried_into_a_shorter_month_lands_on_its_last(year, month, day, expected):
    assert day_in(year, month, day) == expected


@pytest.mark.parametrize(
    ("start", "months"),
    [(dt.date(dt.MINYEAR, 1, 15), -1), (dt.date(dt.MAXYEAR, 12, 15), 1)],
    ids=["before-the-first-year", "after-the-last"],
)
def test_paging_off_the_end_of_time_stays_put(start, months):
    """There is no month to show, and a crash is not a way of saying so."""
    assert shift_month(start, months) == start


# --- getting around --------------------------------------------------------


async def test_the_arrow_keys_move_a_day_and_a_week():
    app = CalendarHarness(AUGUST)
    async with app.run_test() as pilot:
        await pilot.press("left")
        assert app.calendar.date == dt.date(2020, 8, 12)
        await pilot.press("right", "right")
        assert app.calendar.date == dt.date(2020, 8, 14)
        await pilot.press("up")
        assert app.calendar.date == dt.date(2020, 8, 7)
        await pilot.press("down", "down")
        assert app.calendar.date == dt.date(2020, 8, 21)


async def test_the_first_day_there_is_stops_a_day_or_a_week_back():
    """1 January of year 1, where `date - timedelta` overflows. That used
    to raise out of the key handler and take the app down; it stops there
    instead, and a week back from a few days in gets as far as the 1st."""
    app = CalendarHarness(dt.date(1, 1, 3))
    async with app.run_test() as pilot:
        await pilot.press("up")
        assert app.calendar.date == dt.date.min
        await pilot.press("left", "up")
        assert app.calendar.date == dt.date.min
        await pilot.press("right")
        assert app.calendar.date == dt.date(1, 1, 2)


async def test_the_page_keys_move_a_month():
    app = CalendarHarness(AUGUST)
    async with app.run_test() as pilot:
        await pilot.press("pageup")
        assert app.calendar.date == dt.date(2020, 7, 13)
        await pilot.press("pagedown", "pagedown")
        assert app.calendar.date == dt.date(2020, 9, 13)


async def test_home_and_end_reach_the_ends_of_the_month():
    app = CalendarHarness(AUGUST)
    async with app.run_test() as pilot:
        await pilot.press("home")
        assert app.calendar.date == dt.date(2020, 8, 1)
        await pilot.press("end")
        assert app.calendar.date == dt.date(2020, 8, 31)


# --- days that have not happened -------------------------------------------


async def test_the_cursor_stops_at_today():
    app = CalendarHarness(TODAY)
    async with app.run_test() as pilot:
        await pilot.press("right")
        assert app.calendar.date == TODAY, "tomorrow is not a day to write about"


async def test_paging_into_a_future_month_lands_on_today():
    """Clamped rather than refused: the key does something either way, and
    the last day there is is the honest answer."""
    app = CalendarHarness(TODAY - dt.timedelta(days=1))
    async with app.run_test() as pilot:
        await pilot.press("pagedown")
        assert app.calendar.date == TODAY


async def test_end_of_the_current_month_is_today_at_the_latest():
    app = CalendarHarness(TODAY.replace(day=1))
    async with app.run_test() as pilot:
        await pilot.press("end")
        assert app.calendar.date <= TODAY


# --- what it tells the screen ----------------------------------------------


async def test_moving_says_where_the_cursor_now_is():
    app = CalendarHarness(AUGUST)
    async with app.run_test() as pilot:
        await pilot.press("left")
        await pilot.pause()
        assert app.changes == [dt.date(2020, 8, 12)]


async def test_a_move_that_changes_nothing_says_nothing():
    """The field and the grid follow each other, and this is what stops
    that from being a loop -- see DatePromptScreen."""
    app = CalendarHarness(TODAY)
    async with app.run_test() as pilot:
        await pilot.press("right")
        await pilot.pause()
        assert app.changes == []


async def test_show_moves_the_cursor_without_announcing_it():
    """For a caller that already knows -- the field, which is where the
    date being typed came from and must not have written back to it."""
    app = CalendarHarness(AUGUST)
    async with app.run_test() as pilot:
        app.calendar.show(dt.date(2020, 8, 20))
        for _ in range(3):
            await pilot.pause()
        assert app.calendar.date == dt.date(2020, 8, 20)
        assert app.changes == []


async def test_show_still_draws_the_month_it_moved_to():
    app = CalendarHarness(AUGUST)
    async with app.run_test() as pilot:
        app.calendar.show(dt.date(2020, 6, 4))
        await pilot.pause()
        lines = app.calendar.render().plain.splitlines()
        assert lines[0].strip() == "June 2020"


async def test_enter_chooses_the_day_the_cursor_is_on():
    app = CalendarHarness(AUGUST)
    async with app.run_test() as pilot:
        await pilot.press("left")
        await pilot.press("enter")
        await pilot.pause()
        assert app.picked == [dt.date(2020, 8, 12)]


# --- the mouse -------------------------------------------------------------


def test_a_point_in_the_grid_is_the_day_drawn_there():
    grid = MonthCalendar(AUGUST)
    # Two heading rows, then the weeks; four columns to a day. August 2020
    # opens on a Saturday, so the second row runs Monday the 3rd to Sunday
    # the 9th.
    assert grid.date_at(0, 3) == dt.date(2020, 8, 3)
    assert grid.date_at(6 * 4, 3) == dt.date(2020, 8, 9)


def test_the_headings_and_the_blank_around_a_month_are_not_days():
    grid = MonthCalendar(AUGUST)
    assert grid.date_at(0, 0) is None, "the month's name"
    assert grid.date_at(0, 1) is None, "the weekday names"
    assert grid.date_at(0, 2) is None, "August opens on a Saturday"
    assert grid.date_at(0, 2 + WEEKS) is None, "below the last week"


async def test_clicking_a_day_moves_the_cursor_to_it():
    app = CalendarHarness(AUGUST)
    async with app.run_test() as pilot:
        # The 3rd: first column of the first full week.
        await pilot.click("#cal", offset=(0, 3))
        await pilot.pause()
        assert app.calendar.date == dt.date(2020, 8, 3)


async def test_clicking_a_day_does_not_choose_it():
    """A list row is a thing you asked for; a calendar cell is one of
    forty-two an unsteady hand can land on."""
    app = CalendarHarness(AUGUST)
    async with app.run_test() as pilot:
        await pilot.click("#cal", offset=(0, 3))
        await pilot.pause()
        assert app.picked == []


async def test_clicking_the_headings_moves_nothing():
    app = CalendarHarness(AUGUST)
    async with app.run_test() as pilot:
        await pilot.click("#cal", offset=(0, 1))
        await pilot.pause()
        assert app.calendar.date == AUGUST


# --- what it draws ---------------------------------------------------------


async def test_a_written_day_is_marked_in_the_rendered_grid():
    """The mark is a glyph, not only a colour: a reader who cannot pick
    the accent out still needs to see which days are written."""
    written = frozenset({dt.date(2020, 8, 12)})
    app = CalendarHarness(AUGUST, written)
    async with app.run_test():
        drawn = app.calendar.render()
        lines = drawn.plain.splitlines()
        assert any("12•" in line for line in lines)
        assert not any("11•" in line for line in lines)


async def test_the_month_and_the_weekdays_are_named():
    app = CalendarHarness(AUGUST)
    async with app.run_test():
        lines = app.calendar.render().plain.splitlines()
        assert lines[0].strip() == "August 2020"
        assert lines[1].split() == [calendar.day_abbr[day][:2] for day in range(DAYS)]


# --- a year ----------------------------------------------------------------

#: A day in a past year with known edges: 2020 is a leap year, and starts
#: on a Wednesday.
MIDYEAR = dt.date(2020, 6, 17)


class YearHarness(App[None]):
    """Bare app holding one year, recording where its cursor goes.

    Wearing the app's stylesheet, since the grid the months are laid out
    in is defined there -- without it every month is drawn at no size and
    there is nothing to click on.
    """

    CSS_PATH = str(Path(zecret.__file__).with_name("app.tcss"))

    def __init__(
        self,
        date: dt.date | None = None,
        written: frozenset[dt.date] = frozenset(),
    ) -> None:
        super().__init__()
        self.year = YearCalendar(date, written, id="year")
        self.changes: list[dt.date] = []

    def compose(self) -> ComposeResult:
        yield self.year

    def on_mount(self) -> None:
        self.year.focus()

    def on_year_calendar_date_changed(self, event: YearCalendar.DateChanged) -> None:
        self.changes.append(event.date)


def drawn(app: YearHarness) -> list[str]:
    """Every month as drawn, one string each."""
    return [month.render().plain for month in app.year.months]


async def test_a_year_is_twelve_months_of_the_cursors_year():
    app = YearHarness(MIDYEAR)
    async with app.run_test(size=(120, 40)):
        months = app.year.months
        assert [month.first for month in months] == [dt.date(2020, m, 1) for m in range(1, 13)]


async def test_each_month_is_named_without_the_year():
    """The year is the screen's heading. Twelve copies of it would be
    eleven nobody reads, and would not fit three columns a day."""
    app = YearHarness(MIDYEAR)
    async with app.run_test(size=(120, 40)):
        titles = [month.splitlines()[0].strip() for month in drawn(app)]
        assert titles == [calendar.month_name[m] for m in range(1, 13)]


async def test_a_month_of_the_year_is_three_columns_a_day():
    """Four would put three months past eighty columns."""
    app = YearHarness(MIDYEAR)
    async with app.run_test(size=(120, 40)):
        for month in drawn(app):
            assert {len(line) for line in month.splitlines()} == {MONTH_WIDTH}


async def test_written_days_are_marked_in_whichever_month_they_fall():
    written = frozenset({dt.date(2020, 2, 29), dt.date(2020, 11, 3)})
    app = YearHarness(MIDYEAR, written)
    async with app.run_test(size=(120, 40)):
        months = drawn(app)
        assert "29•" in months[1]
        assert " 3•" in months[10]
        assert "•" not in months[5], "June has nothing written"


async def test_a_new_set_of_written_days_is_drawn_at_once():
    """After the editor, which the calendar screen hands over on resume."""
    app = YearHarness(MIDYEAR)
    async with app.run_test(size=(120, 40)):
        app.year.set_written(frozenset({dt.date(2020, 6, 1)}))
        assert " 1•" in drawn(app)[5]


#: 2020 at three months across. January opens on a Wednesday and ends on a
#: Friday; February opens on a Saturday; April opens on a Wednesday.
NOW = dt.date(2026, 10, 1)


@pytest.mark.parametrize(
    ("start", "dx", "dy", "expected"),
    [
        # Inside a month: a day and a week, as they always were.
        (dt.date(2020, 1, 15), 1, 0, dt.date(2020, 1, 16)),
        (dt.date(2020, 1, 15), 0, 1, dt.date(2020, 1, 22)),
        # A Sunday's right is the month beside it, on the same row of weeks
        # -- not the next Monday, a row down at the far left.
        (dt.date(2020, 1, 12), 1, 0, dt.date(2020, 2, 3)),
        # A Monday's left, likewise, is the month to the left.
        (dt.date(2020, 2, 3), -1, 0, dt.date(2020, 1, 12)),
        # Over the blank weekend after 31 January, into February's row.
        (dt.date(2020, 1, 31), 1, 0, dt.date(2020, 2, 24)),
        # Down from the last week is the month below, not the month after.
        (dt.date(2020, 1, 31), 0, 1, dt.date(2020, 4, 3)),
        # And up from April's first week is January's last Wednesday, over
        # the blank row January does not fill.
        (dt.date(2020, 4, 1), 0, -1, dt.date(2020, 1, 29)),
        # Edges of the year: nowhere to go, so nowhere is gone.
        (dt.date(2020, 1, 6), -1, 0, None),
        (dt.date(2020, 3, 31), 1, 0, None),
        (dt.date(2020, 1, 1), 0, -1, None),
        (dt.date(2020, 12, 31), 0, 1, None),
        # A day not yet come is refused, not clamped to.
        (NOW, 1, 0, None),
        (NOW, 0, 1, None),
    ],
    ids=[
        "a-day-right",
        "a-week-down",
        "sunday-right-to-the-month-beside",
        "monday-left-to-the-month-beside",
        "over-blanks-to-the-month-beside",
        "down-to-the-month-below",
        "up-over-a-blank-row",
        "left-edge",
        "right-edge",
        "top-edge",
        "bottom-edge",
        "tomorrow",
        "next-week",
    ],
)
def test_an_arrow_moves_to_the_cell_drawn_that_way(start, dx, dy, expected):
    assert spatial_step(start, dx, dy, 3, NOW) == expected


def test_what_is_below_depends_on_how_many_months_sit_across():
    """The point of the change, not a side effect of it: down from January
    is whichever month is drawn under it."""
    january = dt.date(2020, 1, 31)
    assert spatial_step(january, 0, 1, 3, NOW).month == 4
    assert spatial_step(january, 0, 1, 4, NOW).month == 5
    assert spatial_step(january, 0, 1, 6, NOW).month == 7


def test_every_day_of_a_year_has_one_cell_and_every_cell_one_day():
    for across in (1, 2, 3, 4, 6):
        cells, days = year_layout(2024, across)
        assert len(cells) == len(days) == 366


async def test_the_arrows_walk_the_grid_the_stylesheet_drew():
    """Asked of the grid's own style, so a wider layout is walked as wide."""
    app = YearHarness(dt.date(2020, 1, 31))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("down")
        assert app.year.date == dt.date(2020, 4, 3), "three across: April is below"
        await pilot.press("left")
        assert app.year.date == dt.date(2020, 4, 2)
        await pilot.press("right", "up")
        app.year.styles.grid_size_columns = 4
        await pilot.pause()
        await pilot.press("down")
        assert app.year.date.month == 5, "four across: May is below"


async def test_an_arrow_at_the_edge_of_the_year_stays_put():
    """The year keys cross into the next year; the arrows do not."""
    app = YearHarness(dt.date(2019, 12, 31))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("down", "right")
        assert app.year.date == dt.date(2019, 12, 31)
        assert app.changes == [], "a move that goes nowhere says nothing"


async def test_the_page_and_end_keys_work_as_in_a_month():
    app = YearHarness(MIDYEAR)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("pagedown")
        assert app.year.date == dt.date(2020, 7, 17)
        await pilot.press("home")
        assert app.year.date == dt.date(2020, 7, 1)
        await pilot.press("end")
        assert app.year.date == dt.date(2020, 7, 31)
        # Through June, which has no 31st -- and the clipped day sticks.
        await pilot.press("pageup", "pageup")
        assert app.year.date == dt.date(2020, 5, 30)


async def test_a_year_either_way_keeps_the_day():
    app = YearHarness(MIDYEAR)
    async with app.run_test(size=(120, 40)):
        app.year.previous_year()
        assert app.year.date == dt.date(2019, 6, 17)
        app.year.next_year()
        assert app.year.date == MIDYEAR


async def test_a_year_from_a_leap_day_lands_on_the_28th():
    app = YearHarness(dt.date(2020, 2, 29))
    async with app.run_test(size=(120, 40)):
        app.year.next_year()
        assert app.year.date == dt.date(2021, 2, 28)


async def test_a_year_forward_into_the_future_lands_on_today():
    app = YearHarness(LAST_YEAR_AND_A_BIT)
    async with app.run_test(size=(120, 40)):
        app.year.next_year()
        assert app.year.date == TODAY


async def test_the_year_cursor_stops_at_today():
    app = YearHarness(TODAY)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("right", "down", "pagedown")
        assert app.year.date == TODAY


def test_a_year_never_starts_on_a_day_that_has_not_happened():
    assert YearCalendar(TOMORROW).date == TODAY


async def test_moving_through_the_year_is_announced():
    app = YearHarness(MIDYEAR)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("right")
        await pilot.pause()
        assert app.changes == [dt.date(2020, 6, 18)]


async def test_clicking_a_day_in_any_month_moves_the_cursor_there():
    app = YearHarness(MIDYEAR)
    async with app.run_test(size=(120, 40)) as pilot:
        november = app.year.months[10]
        # 2 November 2020 is a Monday: first column of the first full week.
        await pilot.click(november, offset=(0, 3))
        await pilot.pause()
        assert app.year.date == dt.date(2020, 11, 2)


async def test_clicking_a_month_name_moves_nothing():
    app = YearHarness(MIDYEAR)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.click(app.year.months[10], offset=(5, 0))
        await pilot.pause()
        assert app.year.date == MIDYEAR


def test_a_month_of_the_year_owns_no_focus():
    """One cursor for the year: focus never has to pass between months."""
    assert not MonthGrid(MIDYEAR, MIDYEAR, frozenset()).can_focus


async def test_a_move_within_the_year_redraws_only_the_months_it_touched():
    """Twelve months redrawn per arrow press, held down, was ten times the
    work the move needed."""
    app = YearHarness(MIDYEAR)
    async with app.run_test(size=(120, 40)) as pilot:
        drawn_for: list[int] = []
        for grid in app.year.months:
            original = grid.show

            def recording(*args, grid=grid, original=original):
                drawn_for.append(grid.first.month)
                original(*args)

            grid.show = recording
        await pilot.press("right")
        assert drawn_for == [6, 6], "a day within June touches only June"
        drawn_for.clear()
        app.year.move_to(dt.date(2020, 7, 1))
        assert sorted(drawn_for) == [6, 7], "the month left and the month arrived in"
        drawn_for.clear()
        app.year.previous_year()
        assert sorted(drawn_for) == list(range(1, 13)), "a new year is every month"


def test_both_calendars_walk_by_the_same_keys():
    """One key map, written once: a fix to one calendar is a fix to both.
    The year takes over the arrows and nothing else."""
    for widget in (MonthCalendar, YearCalendar):
        assert issubclass(widget, WalkableCalendar)


def painted_cursor(app: YearHarness) -> str:
    """The background the cursor's day is painted on, read off the screen."""
    month = app.year.cursor_month
    day = f"{app.year.date.day:>2}"
    region = month.region
    for y, strip in enumerate(app.screen._compositor.render_strips()):
        if not region.y <= y < region.bottom:
            continue
        x = 0
        for segment in strip:
            if region.x <= x < region.right and segment.text.strip() == day.strip():
                return str(segment.style.bgcolor if segment.style else None)
            x += len(segment.text)
    raise AssertionError("the cursor's day is not on the screen")


async def test_the_year_cursor_is_solid_only_while_the_year_has_focus():
    app = YearHarness(MIDYEAR)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        focused = painted_cursor(app)
        app.screen.set_focus(None)
        await pilot.pause()
        blurred = painted_cursor(app)
        app.year.focus()
        await pilot.pause()
        assert blurred != focused, "the cursor should soften when the year loses focus"
        assert painted_cursor(app) == focused


async def test_clicking_a_day_not_yet_come_does_nothing():
    """It used to clamp to today, which is a cell in another month."""
    # Not on today, so that a clamp to today would show as a move.
    app = YearHarness(YESTERDAY)
    async with app.run_test(size=(120, 40)) as pilot:
        app.year.post_message(MonthGrid.DayClicked(TOMORROW))
        app.year.post_message(MonthGrid.DayClicked(dt.date(TODAY.year + 1, 1, 1)))
        await pilot.pause()
        assert app.year.date == YESTERDAY
        assert app.changes == []
