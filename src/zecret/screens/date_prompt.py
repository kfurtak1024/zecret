"""A modal asking which day to write about.

The entry list's 'n' goes straight to today, which covers writing in the
evening about the day you are in. This covers the rest: filling in the day
you missed, or going back to a day you want to add to. Dismisses the chosen
date, or None if the user backed out.

Two ways to answer it, and the typed one comes first. The field has focus
when the modal opens, so a date that is already known is still four
keystrokes and enter -- that is the fast path and nothing about the
calendar is allowed to slow it down. Tab (or down) moves into the grid
below, which is for the other question: not "which day did I mean" but
"which days have I missed", which no text field can show you. Whichever
one is being used, the other follows it, and the field is what the answer
is finally read from.

Following happens as the date is typed rather than when it is finished:
the month arrives under the cursor at the keystroke that names it, so the
grid is useful while the date is still going in rather than only once
there is nothing left to look up. The two directions are not symmetrical,
though, and that is what keeps them from fighting: the grid announces its
moves and the field writes them down, while the field moves the grid
quietly (`MonthCalendar.show`) -- because a field halfway through a date
must not have that date finished for it.

Future days are refused. A diary records what happened, and an entry filed
under a day that has not arrived would sit at the top of the list ahead of
everything real. The calendar will not put its cursor on one either, so
the refusal is only ever met by someone who typed the date out.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, MaskedInput

from zecret.screens.base import today
from zecret.screens.calendar import LEGEND, MonthCalendar, day_in
from zecret.screens.header import DiaryFooter

PROMPT = "Which day?"
HINT = "Type a date, or tab to the calendar."
NOT_A_DATE = "That is not a date. Use YYYY-MM-DD."
IN_THE_FUTURE = "That day has not happened yet."

#: A date being typed, from the point where it says anything at all. The
#: mask fills its own separators in, so a field on its way to 2019-04-15
#: reads '2019-', '2019-0', '2019-04-', '2019-04-1' and then the date --
#: which is why the day is one digit or two, and why a trailing separator
#: is stripped before this is matched against.
PART_TYPED = re.compile(r"(?P<year>\d{4})-(?P<month>\d{2})(?:-(?P<day>\d{1,2}))?")


def typed_date(raw: str, near: dt.date) -> dt.date | None:
    """The day a part-typed field points at, if it points anywhere yet.

    The calendar follows the typing rather than waiting for it to finish,
    so this answers as soon as there is a month: someone typing a date
    from two years ago should see that month arrive under their fingers,
    not after the last digit. Until then it answers None and the grid
    stays where it was, rather than flicking through the years 0002, 0020
    and 0201 on the way to 2019.

    `near` is where the cursor is now, and is what a month with no day yet
    keeps -- clamped, so typing the month of a February from the 31st
    lands on the 28th rather than raising.
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
    # A single '0' is on its way to being the 1st through the 9th, and
    # '2019-04-32' is nowhere at all. Neither is a day to move to.
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


class DateInput(MaskedInput):
    """The date field, with one key the calendar underneath is worth.

    Down goes to the grid, because that is where the eye is already
    heading -- tab does the same and is what a form is expected to answer
    to, but nobody looking at a calendar below a field reaches for tab
    first. Bound on the widget rather than on the screen so it stays out
    of the help popup and the key bar, which document the diary rather
    than how to get around one modal. Same rule as DiaryTextArea's keys.
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
    ]

    def __init__(
        self,
        default: dt.date | None = None,
        written: frozenset[dt.date] = frozenset(),
    ) -> None:
        """Args:
        default: The date the field starts on. Defaults to today, since
            the day you most often want is the one you are in.
        written: The days the diary already holds an entry for, which the
            calendar marks. Passed in rather than looked up here: the
            caller has the diary open, and a modal that reached for it
            would be the one screen in the app that talks to storage
            without being asked to.
        """
        super().__init__()
        self.default = today() if default is None else default
        self.written = written

    def compose(self) -> ComposeResult:
        # Scrolls, so that a short terminal loses the bottom of the
        # calendar rather than hiding the field the answer is typed into.
        with VerticalScroll(id="date-box"):
            yield Label(PROMPT, id="date-title")
            # The mask keeps the field to digits in the right places, so
            # the only thing left to check is whether the day is real.
            yield DateInput(
                template="0000-00-00",
                value=self.default.isoformat(),
                id="date",
            )
            yield Label(HINT, id="date-hint")
            yield MonthCalendar(self.default, self.written, id="date-calendar")
            yield Label(LEGEND, id="date-legend")
            yield Label("", id="date-error")
        # The screen underneath keeps rendering its own bar, and every
        # key on it is dead while this question has focus -- so without
        # one of our own the terminal advertises eight keys that do
        # nothing and hides the one that does. See CLAUDE.md on `show`
        # being a layout decision: it is only a decision where there is a
        # footer for it to decide about.
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
        """Follow the typing, from the keystroke that names a month.

        Not only on a finished date: someone filling in a day from two
        years ago wants that month to arrive as they type it, and waiting
        for the last digit means the grid is only ever right once there is
        nothing left to look up in it. Before there is a month it stays
        put -- see typed_date.

        `show` rather than assignment, because this is the half that is
        being typed into: a move announced here comes back as a DateChanged
        that writes the date into the field, which would finish a date
        under the cursor of the person still typing it.
        """
        date = typed_date(event.value, self.calendar.date)
        if date is not None:
            self.calendar.show(date)

    def on_month_calendar_date_changed(self, event: MonthCalendar.DateChanged) -> None:
        """Write the grid's day into the field, which is what is read.

        Only the grid's own moves arrive here -- what the field puts into
        the grid goes through `show`, which says nothing -- so this is one
        way round rather than two chasing each other. The Changed it does
        raise on the field comes back as a typed_date equal to where the
        cursor already is, which `show` drops on the spot.
        """
        self.field.value = event.date.isoformat()

    def on_month_calendar_date_picked(self, _event: MonthCalendar.DatePicked) -> None:
        """Enter on the grid answers the question, the same as enter in the
        field does -- through accept(), so the one place that decides what
        is a usable date keeps deciding it."""
        self.accept()

    def on_input_submitted(self, _event: MaskedInput.Submitted) -> None:
        self.accept()

    # --- answering ---------------------------------------------------------

    def accept(self) -> None:
        """Validate the typed date and dismiss with it, or explain why not."""
        raw = self.field.value
        try:
            # Rejects a half-typed date as well as an impossible one:
            # '2026-08-' and '2026-02-30' both fail here.
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
        self.query_one("#date-error", Label).update(message)
