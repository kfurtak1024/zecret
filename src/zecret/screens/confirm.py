"""A yes/no confirmation modal, shared by the screens that need one.

Used before anything destructive: deleting an entry (entry_list) and
discarding unsaved edits (editor).
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConfirmScreen(ModalScreen[bool]):
    """Yes/no modal. Dismisses True to confirm, False to cancel."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, question: str, *, confirm_label: str = "Delete") -> None:
        super().__init__()
        self.question = question
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(self.question, id="confirm-question")
            with Horizontal(id="confirm-buttons"):
                yield Button(self.confirm_label, variant="error", id="confirm-yes")
                yield Button("Cancel", variant="primary", id="confirm-no")

    def on_mount(self) -> None:
        # Focus Cancel, not the destructive button: a stray Enter should not
        # confirm something irreversible.
        self.query_one("#confirm-no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")

    def action_cancel(self) -> None:
        self.dismiss(False)
