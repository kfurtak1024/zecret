"""Tests for MonthCalendar: the month grid inside the which-day modal.

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
      today rather than refusing, so no key is dead.
    - Paging a month keeps the day of the month where the month it lands
      in is long enough, and stops at that month's last day where it is
      not. Paging off the ends of what a date can be leaves it alone.
    - Moving posts DateChanged; enter posts DatePicked. Moving through
      show() posts nothing, which is what lets the field above drive the
      grid while it is being typed into.
    - A click lands the cursor on the day under it, and a click on the
      headings or on the blank around a month does nothing.
"""

from __future__ import annotations

import calendar
import datetime as dt

import pytest
from textual.app import App, ComposeResult

from zecret.screens.calendar import DAYS, WEEKS, MonthCalendar, day_in, shift_month

TODAY = dt.date.today()
YESTERDAY = TODAY - dt.timedelta(days=1)
TOMORROW = TODAY + dt.timedelta(days=1)

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
        grid = MonthCalendar(dt.date(2026, month, 1)).weeks
        assert len(grid) == WEEKS
        assert {len(row) for row in grid} == {DAYS}


def test_every_day_of_the_month_appears_once():
    grid = MonthCalendar(AUGUST).weeks
    days = [day for row in grid for day in row if day]
    assert days == list(range(1, 32))


def test_weeks_start_on_monday():
    """August 2020 opens on a Saturday, so its first row is five blanks."""
    first = MonthCalendar(AUGUST).weeks[0]
    assert first == [0, 0, 0, 0, 0, 1, 2]


# --- how a day is drawn ----------------------------------------------------


def test_a_written_day_is_drawn_differently_from_an_empty_one():
    written = frozenset({dt.date(2020, 8, 12)})
    grid = MonthCalendar(AUGUST, written)
    assert grid.style_for(dt.date(2020, 8, 12)) == "month-calendar--written"
    assert grid.style_for(dt.date(2020, 8, 11)) == "month-calendar--day"


def test_the_cursor_outranks_everything_it_sits_on():
    """Losing the cursor in a month of marked days would leave the arrow
    keys with nothing to show for themselves."""
    written = frozenset({AUGUST})
    assert MonthCalendar(AUGUST, written).style_for(AUGUST) == "month-calendar--cursor"


def test_a_day_that_has_not_happened_is_drawn_as_unavailable():
    grid = MonthCalendar(YESTERDAY, frozenset({TOMORROW}))
    assert grid.style_for(TOMORROW) == "month-calendar--unavailable"


def test_today_is_not_a_style_of_its_own():
    """It is laid over whatever the day already is -- see render. A day
    that is both today and written is still drawn as written."""
    grid = MonthCalendar(YESTERDAY, frozenset({TODAY}))
    assert grid.style_for(TODAY) == "month-calendar--written"


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
