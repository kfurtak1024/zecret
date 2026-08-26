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

Saving does not leave, though. ctrl+s writes the day and hands the cursor
straight back, because an entry is written over an evening rather than in
one keystroke; escape is what leaves.

Because there is no draft state, leaving with unsaved changes would lose
them outright, so backing out of a modified entry asks first — which a
saved day no longer is, so escape after ctrl+s just goes. The question has
three answers, not two: save and go back, discard, or stay. Escape is
pressed to reach the list, and offering only to throw the last paragraph
away or to stay put made an ordinary key into a small trap. A save that
fails keeps you on the screen with your text intact, whichever key asked
for it.

Locking is the exception to that asking. ctrl+l saves the day and then
locks, rather than putting a question on the screen and leaving the diary
open behind it while it waits for an answer -- see action_save_and_lock.

Those three keys are the screen's whole keymap, and they are about the
diary rather than about the text: save it, lock it, go back. Everything to
do with the writing itself belongs to DiaryTextArea below.
"""

from __future__ import annotations

import datetime as dt
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.widgets import Label, TextArea

from zecret.models import Entry
from zecret.screens.base import UNSAVED_CHANGES, FormScreen, format_day_long, save_error
from zecret.screens.confirm import Choice, ConfirmScreen
from zecret.screens.header import DiaryFooter, DiaryHeader
from zecret.storage import ZecretConflictError

#: The way out of the unsaved-changes question that keeps the writing.
#: Names where it puts you, because the other two answers go to the same
#: place and only this one takes the day with it.
SAVE_AND_GO_BACK = "Save and go back"
#: Shown for an empty body and for one that is only whitespace, which
#: amounts to the same thing and reads the same way in the list.
EMPTY_ENTRY = "Nothing to save — write something first."
#: Said over the day you are still writing. ctrl+s leaves the text exactly
#: where it was, so nothing on the screen changes to mark the save -- and
#: without a word for it the keypress would be indistinguishable from one
#: the app never received.
SAVED = "Saved."
#: Said after ctrl+l, because the saving is the part you would not
#: otherwise know happened -- the lock screen speaks for itself.
SAVED_AND_LOCKED = "Saved, and locked."


class DiaryTextArea(TextArea):
    """Textual's text area with the editing keys it is missing.

    Bound on the widget rather than on the screen, which is what keeps
    them out of the help popup and the key bar: those two document what
    Zecret does with a *diary* -- save it, lock it, go back -- and a
    reader who has used any other editor already knows what ctrl+home
    does. It is the same reason the popup does not list ctrl+z, ctrl+k or
    the arrow keys, which are Textual's and equally real.

    The keys themselves are ordinary. What is not ordinary is that
    Textual leaves them out, so they are put back rather than invented.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        # TextArea has home and end for the line, and the page keys for a
        # screenful, but nothing for the two ends of the text itself --
        # so a day written at length had its top hundreds of presses from
        # its bottom.
        Binding("ctrl+home", "document_start", "Start of the entry", show=False),
        Binding("ctrl+end", "document_end", "End of the entry", show=False),
        # Overrides TextArea's own ctrl+a, which is readline's "start of
        # line" -- a pairing with ctrl+e that made sense when a text field
        # was one line long. Selecting the whole entry is what the chord
        # means everywhere else, and it was reachable only on f7, which
        # nobody finds. Nothing is lost: home still goes to the start of
        # the line, and is the key most people reach for anyway.
        Binding("ctrl+a", "select_all", "Select all", show=False),
    ]

    def action_document_start(self) -> None:
        """ctrl+home: to the first character of the day's text."""
        self.move_cursor((0, 0))

    def action_document_end(self) -> None:
        """ctrl+end: to the last character of the day's text."""
        self.move_cursor(self.document.end)


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
            yield DiaryTextArea(
                "" if self.entry is None else self.entry.body,
                soft_wrap=True,
                id="body",
            )
            yield Label("", id="editor-error")
        yield DiaryFooter()

    def on_mount(self) -> None:
        day = format_day_long(self.date)
        self.sub_title = f"{day} — new" if self.creating else day
        self.body.focus()

    # --- current state -----------------------------------------------------

    @property
    def body(self) -> DiaryTextArea:
        """The widget the day is written in."""
        return self.query_one("#body", DiaryTextArea)

    @property
    def body_text(self) -> str:
        return self.body.text

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
        """ctrl+s: file the day and carry on writing it.

        Saving does not leave. Every editor spells "write what I have so
        far" this way, and a diary entry is written over an evening rather
        than in one keystroke -- being returned to the list for it meant
        pressing 'n' and finding your place again to add the next line, so
        the safe habit cost more than not having it.

        Leaving is escape's job, and it no longer asks anything once this
        has run: there is nothing unsaved left to discard.
        """
        if self._save():
            self.set_error("")
            self.notify(SAVED)

    def _save(self) -> bool:
        """Persist the day's text, and say whether it reached disk.

        Split out of action_save because locking needs the same work
        without the leaving: a caller that gets False back should stay
        where it is, since the error is already on the screen and the text
        is still only in the widget.
        """
        # Nothing typed since the last save, so there is nothing to write.
        # Worth the check now that ctrl+s stays here: the reflex is to
        # press it every few sentences, and each press would otherwise
        # rewrite the whole file, restamp a day nobody edited, and turn
        # another Zecret's saving into a conflict over an entry this one
        # was not changing. A day that has never been written is not
        # unmodified in this sense -- it is empty, and refused below.
        if not self.modified and self.entry is not None:
            return True

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
        """Leave the day -- asking first if that would throw writing away.

        The question offers to save rather than only to discard: escape is
        pressed to get back to the list, and being told the only ways to do
        that were to lose the last paragraph or to stay put made a routine
        key into a small trap.
        """
        if not self.modified:
            self.dismiss()
            return
        self.app.push_screen(
            ConfirmScreen(
                UNSAVED_CHANGES,
                confirm_label="Discard",
                save_label=SAVE_AND_GO_BACK,
            ),
            self.leave,
        )

    def leave(self, choice: Choice | None) -> None:
        """Act on the answer to the unsaved-changes question.

        Anything other than the two answers that leave -- Cancel, escape,
        a modal torn down from under it -- stays here with the text
        untouched, which is what makes the question safe to raise on a key
        as ordinary as escape.
        """
        if choice is Choice.CONFIRM:
            self.dismiss()
        elif choice is Choice.SAVE and self._save():
            # Before the dismiss and outliving it: a notification belongs
            # to the app, so this one is still there to be read over the
            # list. A save that refuses keeps you here instead, with its
            # reason already on the error line.
            self.notify(SAVED)
            self.dismiss()

    def save_pending(self) -> bool:
        """Write the day out for someone who is quitting over it.

        The editor is the one screen that ever holds something unsaved --
        see blocks_lock, which is what puts this question on the screen in
        the first place.
        """
        return self._save()
