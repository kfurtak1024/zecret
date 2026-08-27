"""The modal that asks before something cannot be undone.

Shared by the three places that need one: deleting an entry (entry_list),
leaving a day with unsaved writing (editor), and quitting over that same
writing (app).

Two of its answers are always there -- confirm and cancel. The third,
save, is offered wherever there is something to save, which is the two
questions about unsaved writing and never the delete one: deleting has no
third road between going and staying, while "discard it or stay put" is a
choice between two things nobody wanted.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label

from zecret.screens.header import DiaryFooter


class Choice(StrEnum):
    """What was answered.

    CANCEL is also what a dismissal with no answer means, so a caller that
    checks for CONFIRM and SAVE has covered every way of saying no --
    including the escape key and a modal torn down by the idle lock.
    """

    CONFIRM = "confirm"
    SAVE = "save"
    CANCEL = "cancel"


#: The answer each button stands for. Keyed by id rather than by label,
#: since the labels are the caller's to word.
ANSWERS = {
    "confirm-save": Choice.SAVE,
    "confirm-yes": Choice.CONFIRM,
    "confirm-no": Choice.CANCEL,
}


class ConfirmScreen(ModalScreen[Choice]):
    """A question with two answers, or three where saving is one of them."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(
        self,
        question: str,
        *,
        confirm_label: str = "Delete",
        save_label: str | None = None,
    ) -> None:
        """Args:
        question: What is being asked, as one line.
        confirm_label: The word on the button that goes through with it.
        save_label: The word on the button that saves first, or None
            where there is nothing to save -- which leaves the modal the
            two-answer question it has always been.
        """
        super().__init__()
        self.question = question
        self.confirm_label = confirm_label
        self.save_label = save_label

    @property
    def offers_save(self) -> bool:
        return self.save_label is not None

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(self.question, id="confirm-question")
            # Left to right: the answer that keeps your writing, the one
            # that goes ahead without it, then the way out.
            with Horizontal(id="confirm-buttons"):
                if self.save_label is not None:
                    yield Button(self.save_label, variant="success", id="confirm-save")
                yield Button(self.confirm_label, variant="error", id="confirm-yes")
                yield Button("Cancel", variant="primary", id="confirm-no")
        # The screen underneath keeps rendering its own bar, and every
        # key on it is dead while this question has focus -- so without
        # one of our own the terminal advertises eight keys that do
        # nothing and hides the one that does. See CLAUDE.md on `show`
        # being a layout decision: it is only a decision where there is a
        # footer for it to decide about.
        yield DiaryFooter()

    def on_mount(self) -> None:
        # Never the destructive button: a stray Enter must not confirm
        # something irreversible. Where saving is on offer that is what
        # gets the focus rather than Cancel -- it keeps the writing, which
        # is the whole reason the question is being asked, and it is the
        # one answer that throws nothing away.
        first = "#confirm-save" if self.offers_save else "#confirm-no"
        self.query_one(first, Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(ANSWERS[str(event.button.id)])

    def action_cancel(self) -> None:
        self.dismiss(Choice.CANCEL)
