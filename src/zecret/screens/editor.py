"""Screen for creating or editing a single entry (title + multi-line body).

Two modes, selected by whether an existing Entry is passed in:
    - Create mode: on save, build Entry.new(title, body), call
      app.diary.add_entry(...), then app.diary.save(app.key).
    - Edit mode: on save, build entry.edited(title=..., body=...), call
      app.diary.update_entry(...), then app.diary.save(app.key).

Every save persists immediately (writes the full diary file atomically) —
there is no separate "unsaved draft" state to manage across screens.

Because there is no draft state, leaving with unsaved changes would lose
them outright, so backing out of a modified entry asks for confirmation
first. A save that fails keeps you on the screen with your text intact.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, Label, TextArea

from zecret.models import Entry
from zecret.screens.base import ZecretScreen
from zecret.screens.confirm import ConfirmScreen

DISCARD_QUESTION = "Discard your unsaved changes?"
EMPTY_ENTRY = "Nothing to save — write a title or some text first."


class EditorScreen(ZecretScreen):
    """Create or edit a single diary entry."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("escape", "back", "Back", priority=True),
    ]

    def __init__(self, entry: Entry | None = None) -> None:
        """Args:
        entry: The entry to edit, or None to create a new one.
        """
        super().__init__()
        self.entry = entry

    @property
    def creating(self) -> bool:
        return self.entry is None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="editor-box"):
            yield Input(
                value="" if self.entry is None else self.entry.title,
                placeholder="Title",
                id="title",
            )
            yield TextArea(
                "" if self.entry is None else self.entry.body,
                soft_wrap=True,
                id="body",
            )
            yield Label("", id="editor-error")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "New entry" if self.creating else "Editing"
        # New entries start at the title; existing ones at the text, which
        # is what you usually came back to change.
        target = "#title" if self.creating else "#body"
        self.query_one(target).focus()

    # --- current state -----------------------------------------------------

    @property
    def title_text(self) -> str:
        return self.query_one("#title", Input).value

    @property
    def body_text(self) -> str:
        return self.query_one("#body", TextArea).text

    @property
    def modified(self) -> bool:
        """Whether the fields differ from what was opened."""
        if self.entry is None:
            return bool(self.title_text or self.body_text)
        return self.title_text != self.entry.title or self.body_text != self.entry.body

    # --- actions -----------------------------------------------------------

    def action_save(self) -> None:
        title, body = self.title_text, self.body_text
        if not title and not body:
            self.set_error(EMPTY_ENTRY)
            return

        diary, key = self.zecret.unlocked
        if self.entry is None:
            entry = Entry.new(title, body)
            diary.add_entry(entry)
        else:
            entry = self.entry.edited(title=title, body=body)
            diary.update_entry(entry)

        try:
            diary.save(key)
        except OSError as error:
            # Stay put: popping now would throw away text that never
            # reached disk.
            self.set_error(f"Could not save: {error.strerror or error}.")
            self.notify("The entry was not saved.", severity="error")
            return

        # Now the edit is the entry, so leaving is no longer "unsaved".
        self.entry = entry
        self.dismiss()

    def action_back(self) -> None:
        if not self.modified:
            self.dismiss()
            return
        self.app.push_screen(ConfirmScreen(DISCARD_QUESTION, confirm_label="Discard"), self.discard)

    def discard(self, confirmed: bool | None) -> None:
        if confirmed:
            self.dismiss()

    def set_error(self, message: str) -> None:
        self.query_one("#editor-error", Label).update(message)
