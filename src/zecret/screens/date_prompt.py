"""A modal asking which day to write about.

For a day other than today: one that was missed, or one to add to.
Dismisses the chosen date, or None if the user backed out.

There are two ways to answer. The date field has focus when the modal
opens, so a known date is typed and entered. Tab or down moves into the
month grid below, which shows which days are already written. Each
follows the other, and the field is what the answer is read from.

The two directions are deliberately asymmetric. The grid announces its
moves and the field writes them down. The field moves the grid quietly
(`MonthCalendar.show`), as the date is typed: an announcement that way
would come back as "write this date into the field" and finish a date
under the cursor of the person still typing it.

Future days are refused. The calendar will not put its cursor on one, so
the refusal is only met by a typed date.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import Label, MaskedInput

from zecret.screens.base import card, plain, today
from zecret.screens.calendar import CalendarLegend, MonthCalendar, day_in
from zecret.screens.header import DiaryFooter

PROMPT = "Which day?"
HINT = "Type a date, or tab to the calendar."
NOT_A_DATE = "That is not a date. Use YYYY-MM-DD."
IN_THE_FUTURE = "That day has not happened yet."

#: A date being typed, once it names a month. The mask fills in its own
#: separators, so the field reads '2019-04-' then '2019-04-1': the day is
#: one digit or two, and a trailing separator is stripped before matching.
PART_TYPED = re.compile(r"(?P<year>\d{4})-(?P<month>\d{2})(?:-(?P<day>\d{1,2}))?")


def typed_date(raw: str, near: dt.date) -> dt.date | None:
    """The day a part-typed field points at, or None if not yet anywhere.

    Answers as soon as there is a month, so the grid follows the typing.
    Before that it is None, so the grid does not flick through the years
    0002, 0020 and 0201 on the way to 2019.

    `near` is where the cursor is now. A month with no day yet keeps its
    day, clamped to the month's length.
    """
    match = PART_TYPED.fullmatch(raw.rstrip("-"))
    if match is None:
        return None
    year, month = int(match["year"]), int(match["month"])
    if not (dt.MINYEAR <= year <= dt.MAXYEAR and 1 <= month <= 12):
        return None
    if match["day"] is None:
        return day_in(year, month, near.day)
    day = int(match["day"])
    # A single '0' is on its way to 01-09, and day 32 is nowhere.
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


class DateInput(MaskedInput):
    """The date field, with `down` bound to move into the calendar.

    Bound on the widget rather than the screen, so it stays out of the
    help popup and the key bar.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("down", "to_calendar", "To the calendar", show=False),
    ]

    def action_to_calendar(self) -> None:
        self.screen.query_one(MonthCalendar).focus()


class DatePromptScreen(ModalScreen[dt.date | None]):
    """Asks for a past-or-present date. Dismisses it, or None if cancelled."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("ctrl+l", "app.lock", "Lock", priority=True),
    ]

    def __init__(
        self,
        default: dt.date | None = None,
        written: frozenset[dt.date] = frozenset(),
    ) -> None:
        """Args:
        default: The date the field starts on. Today if not given.
        written: The days the diary already holds an entry for, which the
            calendar marks. Passed in: a modal does not reach for storage.
        """
        super().__init__()
        self.default = today() if default is None else default
        self.written = written

    def compose(self) -> ComposeResult:
        # Scrolls, so a short terminal loses the bottom of the calendar
        # rather than the field.
        with card("date-box"):
            yield Label(PROMPT, id="date-title")
            # The mask keeps the field to digits in the right places; what
            # is left to check is whether the day is real.
            yield DateInput(
                template="0000-00-00",
                value=self.default.isoformat(),
                id="date",
            )
            yield Label(HINT, id="date-hint")
            yield MonthCalendar(self.default, self.written, id="date-calendar")
            yield CalendarLegend(id="date-legend")
            yield Label("", id="date-error")
        yield DiaryFooter()

    def on_mount(self) -> None:
        self.field.focus()

    # --- the two halves, kept in step --------------------------------------

    @property
    def field(self) -> DateInput:
        return self.query_one("#date", DateInput)

    @property
    def calendar(self) -> MonthCalendar:
        return self.query_one("#date-calendar", MonthCalendar)

    def on_input_changed(self, event: MaskedInput.Changed) -> None:
        """Move the grid to follow the typing, quietly (see the module
        docstring for why `show` and not assignment)."""
        date = typed_date(event.value, self.calendar.date)
        if date is not None:
            self.calendar.show(date)

    def on_month_calendar_date_changed(self, event: MonthCalendar.DateChanged) -> None:
        """Write the grid's day into the field.

        Only the grid's own moves arrive here. The Changed this raises on
        the field comes back as a date equal to the cursor's, which `show`
        drops.
        """
        self.field.value = event.date.isoformat()

    def on_month_calendar_date_picked(self, _event: MonthCalendar.DatePicked) -> None:
        """Enter on the grid answers through accept(), as enter in the
        field does."""
        self.accept()

    def on_input_submitted(self, _event: MaskedInput.Submitted) -> None:
        self.accept()

    # --- answering ---------------------------------------------------------

    def accept(self) -> None:
        """Validate the typed date and dismiss with it, or explain why not."""
        raw = self.field.value
        try:
            # Rejects a half-typed date as well as an impossible one.
            date = dt.date.fromisoformat(raw)
        except ValueError:
            self.set_error(NOT_A_DATE)
            return
        if date > today():
            self.set_error(IN_THE_FUTURE)
            return
        self.dismiss(date)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def set_error(self, message: str) -> None:
        self.query_one("#date-error", Label).update(plain(message))
