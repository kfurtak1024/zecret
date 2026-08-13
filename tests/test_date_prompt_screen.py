"""Tests for DatePromptScreen: choosing which day to write about.

Required coverage:
    - The field starts on today, or on a caller-supplied default.
    - Submitting a valid past-or-present date dismisses with that date.
    - Escape dismisses with None, choosing nothing.
    - A half-typed, impossible, or future date is refused inline and the
      modal stays open.
"""

from __future__ import annotations

import datetime as dt

import pytest
from textual.app import App
from textual.widgets import Label, MaskedInput

from zecret.screens.date_prompt import (
    IN_THE_FUTURE,
    NOT_A_DATE,
    DatePromptScreen,
)

TODAY = dt.date.today()
YESTERDAY = TODAY - dt.timedelta(days=1)
TOMORROW = TODAY + dt.timedelta(days=1)

#: Distinguishes "not dismissed yet" from "dismissed with None".
PENDING = object()


class PromptHarness(App[None]):
    """Bare app that shows the modal and records what it dismisses with."""

    def __init__(self, default: dt.date | None = None) -> None:
        super().__init__()
        self.default = default
        self.result: object = PENDING

    def on_mount(self) -> None:
        self.push_screen(DatePromptScreen(self.default), self.record)

    def record(self, value: dt.date | None) -> None:
        self.result = value


def field(app: PromptHarness) -> MaskedInput:
    return app.screen.query_one("#date", MaskedInput)


def error(app: PromptHarness) -> str:
    return str(app.screen.query_one("#date-error", Label).content)


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
