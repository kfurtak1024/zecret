"""Tests for DatePromptScreen: choosing which day to write about.

Required coverage:
    - The field starts on today, or on a caller-supplied default, and has
      focus: typing a date you already know must not have got slower for
      the calendar being there.
    - Submitting a valid past-or-present date dismisses with that date.
    - Escape dismisses with None, choosing nothing.
    - A half-typed, impossible, or future date is refused inline and the
      modal stays open.
    - The calendar starts where the field does, and the two follow each
      other afterwards: the grid moves to the month at the keystroke that
      names it and to the day as the day is typed, moving the grid
      rewrites the field, and neither sets the other going in circles.
    - Typing is never completed for the typist: a field halfway through a
      date still reads as what was typed, not as the day the grid is
      showing.
    - Down from the field reaches the calendar, and enter there answers
      the question the same way enter in the field does.
    - The days the caller says are written are the days the grid marks.
"""

from __future__ import annotations

import datetime as dt

import pytest
from textual.app import App
from textual.widgets import Label, MaskedInput

from zecret.screens.calendar import MonthCalendar
from zecret.screens.date_prompt import (
    IN_THE_FUTURE,
    NOT_A_DATE,
    DatePromptScreen,
    typed_date,
)

TODAY = dt.date.today()
YESTERDAY = TODAY - dt.timedelta(days=1)
TOMORROW = TODAY + dt.timedelta(days=1)

#: Distinguishes "not dismissed yet" from "dismissed with None".
PENDING = object()


class PromptHarness(App[None]):
    """Bare app that shows the modal and records what it dismisses with."""

    def __init__(
        self,
        default: dt.date | None = None,
        written: frozenset[dt.date] = frozenset(),
    ) -> None:
        super().__init__()
        self.default = default
        self.written = written
        self.result: object = PENDING

    def on_mount(self) -> None:
        self.push_screen(DatePromptScreen(self.default, self.written), self.record)

    def record(self, value: dt.date | None) -> None:
        self.result = value


def field(app: PromptHarness) -> MaskedInput:
    return app.screen.query_one("#date", MaskedInput)


def error(app: PromptHarness) -> str:
    return str(app.screen.query_one("#date-error", Label).content)


def grid(app: PromptHarness) -> MonthCalendar:
    return app.screen.query_one("#date-calendar", MonthCalendar)


# --- starting value --------------------------------------------------------


async def test_field_starts_on_today():
    app = PromptHarness()
    async with app.run_test():
        assert field(app).value == TODAY.isoformat()


async def test_field_starts_on_a_supplied_default():
    day = dt.date(2019, 4, 1)
    app = PromptHarness(day)
    async with app.run_test():
        assert field(app).value == day.isoformat()


async def test_field_is_focused_so_the_date_can_be_typed_straight_away():
    app = PromptHarness()
    async with app.run_test():
        assert app.screen.focused is field(app)


# --- accepting a date ------------------------------------------------------


async def test_submitting_the_default_dismisses_with_today():
    app = PromptHarness()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        assert app.result == TODAY


async def test_today_is_accepted_at_the_boundary():
    """Today is not the future, however the comparison is written."""
    app = PromptHarness(YESTERDAY)
    async with app.run_test() as pilot:
        field(app).value = TODAY.isoformat()
        await pilot.press("enter")
        await pilot.pause()
        assert app.result == TODAY


async def test_a_typed_past_date_is_dismissed_with():
    app = PromptHarness()
    async with app.run_test() as pilot:
        field(app).value = ""
        await pilot.press("2", "0", "1", "9", "0", "4", "0", "1")
        await pilot.pause()
        assert field(app).value == "2019-04-01", "the mask should insert the dashes"
        await pilot.press("enter")
        await pilot.pause()
        assert app.result == dt.date(2019, 4, 1)


async def test_the_modal_closes_once_a_date_is_chosen():
    app = PromptHarness()
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, DatePromptScreen)


# --- cancelling ------------------------------------------------------------


async def test_escape_dismisses_with_none():
    app = PromptHarness()
    async with app.run_test() as pilot:
        await pilot.press("escape")
        await pilot.pause()
        assert app.result is None


# --- refusals --------------------------------------------------------------


@pytest.mark.parametrize(
    "typed",
    ["", "2026-08-", "2026-02-30", "0000-00-00"],
    ids=["empty", "half-typed", "no-such-day", "all-zeros"],
)
async def test_an_unusable_date_is_refused_inline(typed):
    app = PromptHarness()
    async with app.run_test() as pilot:
        field(app).value = typed
        await pilot.press("enter")
        await pilot.pause()
        assert app.result is PENDING, "the modal must not dismiss"
        assert isinstance(app.screen, DatePromptScreen)
        assert error(app) == NOT_A_DATE


async def test_a_future_date_is_refused_inline():
    app = PromptHarness()
    async with app.run_test() as pilot:
        field(app).value = TOMORROW.isoformat()
        await pilot.press("enter")
        await pilot.pause()
        assert app.result is PENDING
        assert error(app) == IN_THE_FUTURE


async def test_a_corrected_date_is_accepted_after_a_refusal():
    app = PromptHarness()
    async with app.run_test() as pilot:
        field(app).value = TOMORROW.isoformat()
        await pilot.press("enter")
        await pilot.pause()
        field(app).value = YESTERDAY.isoformat()
        await pilot.press("enter")
        await pilot.pause()
        assert app.result == YESTERDAY


# --- reading a date that is still being typed ------------------------------

#: Where the cursor is while the typing happens, for the cases where a
#: part-typed date has to borrow a day from somewhere.
NEAR = dt.date(2026, 8, 31)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Nothing to go on yet: a year on its own could still become any
        # year, and the grid stays where it is.
        ("", None),
        ("2", None),
        ("201", None),
        ("2019-", None),
        ("2019-0", None),
        # A month, and no day yet: the cursor keeps the day it is on,
        # clamped to a month that is shorter than that day.
        ("2019-04-", dt.date(2019, 4, 30)),
        ("2019-04", dt.date(2019, 4, 30)),
        ("2019-12-", dt.date(2019, 12, 31)),
        # The day, as it is typed.
        ("2019-04-1", dt.date(2019, 4, 1)),
        ("2019-04-15", dt.date(2019, 4, 15)),
        # Nowhere at all.
        ("2019-13-", None),
        ("2019-00-", None),
        ("2019-04-0", None),
        ("2019-04-31", None),
        ("2019-02-30", None),
        ("0000-01-01", None),
        ("nonsense", None),
    ],
    ids=[
        "empty",
        "one-digit",
        "part-of-a-year",
        "a-year",
        "a-year-and-a-digit",
        "a-month",
        "a-month-without-its-separator",
        "a-month-with-31-days",
        "the-first-digit-of-a-day",
        "a-whole-date",
        "a-thirteenth-month",
        "a-zeroth-month",
        "a-zeroth-day",
        "a-day-past-the-end-of-the-month",
        "the-30th-of-february",
        "the-year-zero",
        "not-a-date-at-all",
    ],
)
def test_what_a_part_typed_field_points_at(raw, expected):
    assert typed_date(raw, NEAR) == expected


# --- the calendar and the field, following each other ----------------------


async def test_the_calendar_starts_where_the_field_does():
    day = dt.date(2019, 4, 1)
    app = PromptHarness(day)
    async with app.run_test():
        assert grid(app).date == day


async def test_typing_a_whole_date_moves_the_calendar():
    app = PromptHarness()
    async with app.run_test() as pilot:
        field(app).value = ""
        await pilot.press("2", "0", "1", "9", "0", "4", "0", "1")
        await pilot.pause()
        assert grid(app).date == dt.date(2019, 4, 1)


async def test_the_month_arrives_as_it_is_typed():
    """The keystroke that names a month is the one that shows it, rather
    than the last digit of the day two keystrokes later."""
    app = PromptHarness(dt.date(2026, 8, 15))
    async with app.run_test() as pilot:
        field(app).value = ""
        await pilot.press("2", "0", "1", "9", "0", "4")
        await pilot.pause()
        assert grid(app).date == dt.date(2019, 4, 15), "April 2019, cursor kept"


async def test_the_day_follows_as_the_day_is_typed():
    app = PromptHarness(dt.date(2026, 8, 15))
    async with app.run_test() as pilot:
        field(app).value = ""
        await pilot.press("2", "0", "1", "9", "0", "4", "1")
        await pilot.pause()
        assert grid(app).date == dt.date(2019, 4, 1), "the 1st, on its way to the 1x"
        await pilot.press("5")
        await pilot.pause()
        assert grid(app).date == dt.date(2019, 4, 15)


async def test_the_year_alone_leaves_the_calendar_where_it_was():
    """Otherwise the grid would flick through the years 2, 20 and 201 on
    the way to 2019."""
    app = PromptHarness(dt.date(2019, 4, 1))
    async with app.run_test() as pilot:
        field(app).value = ""
        await pilot.press("2", "0", "2")
        await pilot.pause()
        assert grid(app).date == dt.date(2019, 4, 1)


async def test_the_field_is_not_finished_for_whoever_is_typing_it():
    """The grid moving writes the date into the field. Following the
    typing must not, or the month you just typed would complete itself
    into a date under your cursor and the rest of what you type would land
    somewhere else."""
    app = PromptHarness(dt.date(2026, 8, 15))
    async with app.run_test() as pilot:
        field(app).value = ""
        await pilot.press("2", "0", "1", "9", "0", "4")
        for _ in range(4):
            await pilot.pause()
        assert field(app).value == "2019-04-"


async def test_moving_the_calendar_rewrites_the_field():
    app = PromptHarness(dt.date(2019, 4, 10))
    async with app.run_test() as pilot:
        grid(app).focus()
        await pilot.press("left")
        await pilot.pause()
        assert field(app).value == "2019-04-09"


async def test_the_two_do_not_set_each_other_going_in_circles():
    """Each update makes the other a no-op, which is what stops the loop.
    A single move should leave both on the same day and settle."""
    app = PromptHarness(dt.date(2019, 4, 10))
    async with app.run_test() as pilot:
        grid(app).focus()
        await pilot.press("up")
        for _ in range(4):
            await pilot.pause()
        assert grid(app).date == dt.date(2019, 4, 3)
        assert field(app).value == "2019-04-03"


# --- answering from the grid -----------------------------------------------


async def test_down_from_the_field_reaches_the_calendar():
    app = PromptHarness()
    async with app.run_test() as pilot:
        await pilot.press("down")
        await pilot.pause()
        assert app.screen.focused is grid(app)


async def test_enter_on_the_calendar_dismisses_with_the_day_it_is_on():
    app = PromptHarness(dt.date(2019, 4, 10))
    async with app.run_test() as pilot:
        await pilot.press("down")
        await pilot.press("left")
        await pilot.press("enter")
        await pilot.pause()
        assert app.result == dt.date(2019, 4, 9)


async def test_escape_still_cancels_from_the_calendar():
    """The screen's own binding, which the grid having focus must not
    swallow -- backing out is the one thing every screen answers to."""
    app = PromptHarness()
    async with app.run_test() as pilot:
        await pilot.press("down")
        await pilot.press("escape")
        await pilot.pause()
        assert app.result is None


# --- what the grid marks ---------------------------------------------------


async def test_the_written_days_reach_the_calendar():
    """The caller has the diary; the modal only draws what it is handed."""
    written = frozenset({dt.date(2019, 4, 2), dt.date(2019, 4, 20)})
    app = PromptHarness(dt.date(2019, 4, 10), written)
    async with app.run_test():
        assert grid(app).written == written
        assert grid(app).style_for(dt.date(2019, 4, 2)) == "month-calendar--written"
