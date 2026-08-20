"""A modal asking which day to write about.

The entry list's 'n' goes straight to today, which covers writing in the
evening about the day you are in. This covers the rest: filling in the day
you missed, or going back to a day you want to add to. Dismisses the chosen
date, or None if the user backed out.

Future days are refused. A diary records what happened, and an entry filed
under a day that has not arrived would sit at the top of the list ahead of
everything real.
"""

from __future__ import annotations

import datetime as dt
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, MaskedInput

from zecret.screens.base import today
from zecret.screens.header import DiaryFooter

PROMPT = "Which day?"
HINT = "Enter a date as YYYY-MM-DD."
NOT_A_DATE = "That is not a date. Use YYYY-MM-DD."
IN_THE_FUTURE = "That day has not happened yet."


class DatePromptScreen(ModalScreen[dt.date | None]):
    """Asks for a past-or-present date. Dismisses it, or None if cancelled."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, default: dt.date | None = None) -> None:
        """Args:
        default: The date the field starts on. Defaults to today, since
            the day you most often want is the one you are in.
        """
        super().__init__()
        self.default = today() if default is None else default

    def compose(self) -> ComposeResult:
        with Vertical(id="date-box"):
            yield Label(PROMPT, id="date-title")
            # The mask keeps the field to digits in the right places, so
            # the only thing left to check is whether the day is real.
            yield MaskedInput(
                template="0000-00-00",
                value=self.default.isoformat(),
                id="date",
            )
            yield Label(HINT, id="date-hint")
            yield Label("", id="date-error")
        # The screen underneath keeps rendering its own bar, and every
        # key on it is dead while this question has focus -- so without
        # one of our own the terminal advertises eight keys that do
        # nothing and hides the one that does. See CLAUDE.md on `show`
        # being a layout decision: it is only a decision where there is a
        # footer for it to decide about.
        yield DiaryFooter()

    def on_mount(self) -> None:
        self.query_one("#date", MaskedInput).focus()

    def on_input_submitted(self, _event: MaskedInput.Submitted) -> None:
        self.accept()

    def accept(self) -> None:
        """Validate the typed date and dismiss with it, or explain why not."""
        raw = self.query_one("#date", MaskedInput).value
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
