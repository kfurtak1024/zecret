"""Screen for writing one day's entry.

Opened on a date, never on an entry: a day holds at most one entry, so the
date is the whole question and the screen looks up whether that day has
been written yet.
    - Unwritten day: on save, build Entry.new(date, body), call
      app.diary.add_entry(...), then app.diary.save(app.key).
    - Written day: on save, build entry.edited(body), call
      app.diary.update_entry(...), then app.diary.save(app.key).

Every save persists immediately (writes the full diary file atomically) —
there is no separate "unsaved draft" state to manage across screens.

Because there is no draft state, leaving with unsaved changes would lose
them outright, so backing out of a modified entry asks for confirmation
first. A save that fails keeps you on the screen with your text intact.

Locking is the exception to that asking. ctrl+l saves the day and then
locks, rather than putting a question on the screen and leaving the diary
open behind it while it waits for an answer -- see action_save_and_lock.
"""

from __future__ import annotations

import datetime as dt
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.widgets import Label, TextArea

from zecret.models import Entry
from zecret.screens.base import FormScreen, format_day_long, save_error
from zecret.screens.confirm import ConfirmScreen
from zecret.screens.header import DiaryFooter, DiaryHeader
from zecret.storage import ZecretConflictError

DISCARD_QUESTION = "Discard your unsaved changes?"
#: Shown for an empty body and for one that is only whitespace, which
#: amounts to the same thing and reads the same way in the list.
EMPTY_ENTRY = "Nothing to save — write something first."
#: Said after ctrl+l, because the saving is the part you would not
#: otherwise know happened -- the lock screen speaks for itself.
SAVED_AND_LOCKED = "Saved, and locked."


class EditorScreen(FormScreen):
    """Write or revise the entry for a single day."""

    ERROR_ID = "editor-error"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("escape", "back", "Back", priority=True),
        # Reachable here, unlike the old shift-L on the entry list, because
        # a chord means something of its own inside a text field. What it
        # does with half-written text is the question that kept locking off
        # this screen; action_save_and_lock answers it.
        Binding("ctrl+l", "save_and_lock", "Lock", priority=True),
    ]

    def __init__(self, date: dt.date) -> None:
        """Args:
        date: The day to write about. Whether it already has an entry is
            looked up from the diary, so callers never have to decide
            between "new" and "edit".
        """
        super().__init__()
        self.date = date
        self.entry: Entry | None = None

    @property
    def creating(self) -> bool:
        return self.entry is None

    def compose(self) -> ComposeResult:
        # Resolved here rather than in __init__ because the diary is
        # reached through the running app, which a screen only has once it
        # is mounted.
        diary, _ = self.zecret.unlocked
        self.entry = diary.entry_for(self.date)

        yield DiaryHeader()
        with Vertical(id="editor-box"):
            yield TextArea(
                "" if self.entry is None else self.entry.body,
                soft_wrap=True,
                id="body",
            )
            yield Label("", id="editor-error")
        yield DiaryFooter()

    def on_mount(self) -> None:
        day = format_day_long(self.date)
        self.sub_title = f"{day} — new" if self.creating else day
        self.query_one("#body", TextArea).focus()

    # --- current state -----------------------------------------------------

    @property
    def body_text(self) -> str:
        return self.query_one("#body", TextArea).text

    @property
    def original_body(self) -> str:
        """What the day held when the screen opened -- nothing, if unwritten."""
        return "" if self.entry is None else self.entry.body

    @property
    def modified(self) -> bool:
        """Whether the text differs from what was opened."""
        return self.body_text != self.original_body

    @property
    def blocks_lock(self) -> bool:
        """Unsaved text is exactly what the idle lock must not discard.

        Backing out asks before throwing this away; a timer must not do
        silently what a keypress is made to confirm.
        """
        return self.modified

    # --- actions -----------------------------------------------------------

    def action_save(self) -> None:
        if self._save():
            self.dismiss()

    def _save(self) -> bool:
        """Persist the day's text, and say whether it reached disk.

        Split out of action_save because locking needs the same work
        without the leaving: a caller that gets False back should stay
        where it is, since the error is already on the screen and the text
        is still only in the widget.
        """
        body = self.body_text
        # Blank means blank, not just zero-length: a body of spaces and
        # newlines is what the list already renders as "(empty)", so
        # accepting it here would file a day under text nobody wrote. The
        # text is stored as typed -- only the question of whether there is
        # any is asked with the whitespace taken off.
        if not body.strip():
            self.set_error(EMPTY_ENTRY)
            return False

        diary, key = self.zecret.unlocked
        existing = self.entry
        if existing is None:
            entry = Entry.new(self.date, body)
            diary.add_entry(entry)
        else:
            entry = existing.edited(body)
            diary.update_entry(entry)

        try:
            diary.save(key)
        except (OSError, ZecretConflictError) as error:
            # Put the in-memory diary back as it was, so it still matches
            # the file and pressing save again is a clean second attempt --
            # otherwise the retry would hit "an entry already exists".
            if existing is None:
                diary.delete_entry(self.date)
            else:
                diary.update_entry(existing)
            # Stay put: popping now would throw away text that never
            # reached disk.
            self.set_error(save_error(error))
            self.notify("The entry was not saved.", severity="error")
            return False

        # Now the edit is the day's entry, so leaving is no longer "unsaved".
        self.entry = entry
        return True

    def action_save_and_lock(self) -> None:
        """Put the day away, and the diary with it.

        Saves rather than asking. Lock is what you press on the way out of
        the room, so it must not stop to put a question on the screen and
        then leave the diary open behind it while it waits to be answered
        -- which is what backing out does, correctly, since backing out is
        not a promise about who can read this.

        Nothing typed yet means nothing to save: an untouched editor locks
        straight away rather than refusing over an empty day. A day that
        will not save -- blank, or a diary that changed underneath this one
        -- keeps you here with the reason, because a lock that quietly threw
        the text away would be the very thing this avoids.
        """
        if not self.modified:
            self.zecret.lock()
            return
        if self._save():
            self.zecret.lock(SAVED_AND_LOCKED)

    def action_back(self) -> None:
        if not self.modified:
            self.dismiss()
            return
        self.app.push_screen(ConfirmScreen(DISCARD_QUESTION, confirm_label="Discard"), self.discard)

    def discard(self, confirmed: bool | None) -> None:
        if confirmed:
            self.dismiss()
