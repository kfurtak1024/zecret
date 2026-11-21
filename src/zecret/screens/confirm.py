"""The modal that asks before something cannot be undone.

Used for deleting an entry (the list and the calendar), leaving a day with
unsaved writing (editor), quitting over that writing (app), and choosing
whose version of a day to keep when another Zecret saved it too (editor).

Confirm and cancel are always offered. Save is a third answer, offered
where there is something to save. Deleting never has it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label

from zecret.screens.base import plain
from zecret.screens.header import DiaryFooter


class Choice(StrEnum):
    """What was answered.

    A dismissal with no answer (escape, or a modal torn down by a lock)
    also means CANCEL, so checking for CONFIRM and SAVE covers every way
    of saying no.
    """

    CONFIRM = "confirm"
    SAVE = "save"
    CANCEL = "cancel"


#: The button each answer is, for a caller that says which starts focused.
BUTTONS = {
    Choice.SAVE: "#confirm-save",
    Choice.CONFIRM: "#confirm-yes",
    Choice.CANCEL: "#confirm-no",
}

#: The answer each button stands for, keyed by id since the labels are the
#: caller's to word.
ANSWERS = {
    "confirm-save": Choice.SAVE,
    "confirm-yes": Choice.CONFIRM,
    "confirm-no": Choice.CANCEL,
}


class ConfirmScreen(ModalScreen[Choice]):
    """A question with two answers, or three where saving is one of them."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("ctrl+l", "app.lock", "Lock", priority=True),
    ]

    def __init__(
        self,
        question: str,
        *,
        confirm_label: str = "Delete",
        save_label: str | None = None,
        focus: Choice | None = None,
    ) -> None:
        """Args:
        question: What is being asked, as one line.
        confirm_label: The word on the button that goes through with it.
        save_label: The word on the button that saves first, or None
            where there is nothing to save.
        focus: The answer whose button starts focused, for a question
            where saving throws something away too. None for the usual
            rule in on_mount.
        """
        super().__init__()
        self.question = question
        self.confirm_label = confirm_label
        self.save_label = save_label
        self.focus_on = focus

    @property
    def offers_save(self) -> bool:
        return self.save_label is not None

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(plain(self.question), id="confirm-question")
            # Left to right: keep the writing, go ahead without it, way out.
            with Horizontal(id="confirm-buttons"):
                if self.save_label is not None:
                    yield Button(self.save_label, variant="success", id="confirm-save")
                yield Button(self.confirm_label, variant="error", id="confirm-yes")
                yield Button("Cancel", variant="primary", id="confirm-no")
        # A modal renders over the screen beneath, whose key bar would
        # otherwise show through with every key on it dead.
        yield DiaryFooter()

    def on_mount(self) -> None:
        # Never the destructive button: a stray Enter must not confirm
        # something irreversible. Save gets the focus where it is offered,
        # being the answer that throws nothing away; otherwise Cancel.
        if self.focus_on is not None:
            first = BUTTONS[self.focus_on]
        else:
            first = "#confirm-save" if self.offers_save else "#confirm-no"
        self.query_one(first, Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(ANSWERS[str(event.button.id)])

    def action_cancel(self) -> None:
        self.dismiss(Choice.CANCEL)
