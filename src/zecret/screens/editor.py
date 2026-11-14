"""Screen for writing one day's entry.

Opened on a date, never on an entry: the screen looks up whether that day
has been written, so callers never choose between "new" and "edit".

- **Saving is immediate and does not leave.** ctrl+s writes the whole
  diary atomically and stays in the day. There is no draft state.
- **Leaving asks.** Escape over unsaved text offers three answers: save
  and go back, discard, or stay. A save that fails keeps you here.
- **A conflict is not a dead end.** If another Zecret saved meanwhile, the
  editor re-reads the diary. If this day is unchanged there, it is filed
  on top of what the other session wrote. If the other session changed
  this day too, nothing is written until ctrl+s has asked whose version
  to keep.
- **Locking saves.** ctrl+l saves the day and then locks, rather than
  leaving a question on the screen with the diary open behind it.

The screen's keys are about the diary: save, cover, back, lock. Everything
about the text itself belongs to DiaryTextArea (text_area.py).
"""

from __future__ import annotations

import datetime as dt
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.widgets import Label

from zecret.crypto import ZecretDecryptError
from zecret.models import Entry
from zecret.screens.base import (
    REKEYED_ELSEWHERE,
    UNSAVED_CHANGES,
    FormScreen,
    format_day_long,
    reread_error,
    save_error,
)
from zecret.screens.confirm import Choice, ConfirmScreen
from zecret.screens.header import DiaryFooter, DiaryHeader
from zecret.screens.text_area import DiaryTextArea
from zecret.storage import DiaryFile, ZecretConflictError

#: The answer to the unsaved-changes question that keeps the writing.
SAVE_AND_GO_BACK = "Save and go back"
#: Shown for a body that is empty or only whitespace.
EMPTY_ENTRY = "Nothing to save — write something first."
#: ctrl+s changes nothing on screen, so the save is said.
SAVED = "Saved."
SAVED_AND_LOCKED = "Saved, and locked."
#: A save that first had to pick up what another Zecret wrote.
SAVED_WITH_THEIRS = "Saved, with what another Zecret wrote meanwhile."
#: On the error row when the other session changed this very day. Only
#: ctrl+s asks the question; locking and quitting have nobody to answer it.
DAY_CHANGED_ELSEWHERE = "Another Zecret saved this day too — ctrl+s to choose whose to keep."
#: The question ctrl+s then asks, its answers, and what is said after each.
WHOSE_DAY = "Another Zecret saved this day while you were writing it. Keep which?"
SAVE_MINE = "Save mine"
TAKE_THEIRS = "Take theirs"
SAVED_OVER_THEIRS = "Saved yours over the other Zecret's."
TOOK_THEIRS = "Showing the other Zecret's version of this day."


class EditorScreen(FormScreen):
    """Write or revise the entry for a single day."""

    ERROR_ID = "editor-error"

    #: This screen's own actions, the way out, then Lock, as on every bar.
    #: All priority, so they win over the text area's own bindings.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s", "save", "Save", priority=True),
        # Declared on the screen, unlike the text-editing keys, so it
        # appears in the key bar and the help popup. "Cover" is the
        # writer's word; the code calls it the mask.
        Binding("ctrl+r", "toggle_mask", "Cover", priority=True),
        Binding("escape", "back", "Back", priority=True),
        Binding("ctrl+l", "save_and_lock", "Lock", priority=True),
    ]

    def __init__(self, date: dt.date) -> None:
        """Args:
        date: The day to write about.
        """
        super().__init__()
        self.date = date
        self.entry: Entry | None = None
        # The diary as another Zecret left it, held while the question of
        # whose version of this day to keep is open.
        self.theirs: DiaryFile | None = None

    @property
    def creating(self) -> bool:
        return self.entry is None

    def compose(self) -> ComposeResult:
        # Looked up here, not in __init__: the app is only reachable once
        # the screen is mounted.
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
        self.show_title()
        # The mask belongs to the session, not to the day.
        self.body.masked = self.zecret.masked
        self.body.focus()

    def show_title(self) -> None:
        """Name the day in the header, and say if it is not written yet.

        Called again after every save, since the first one is what makes
        a new day written.
        """
        day = format_day_long(self.date)
        self.sub_title = f"{day} — new" if self.creating else day

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
        """What the day held when last opened or saved; empty if unwritten."""
        return "" if self.entry is None else self.entry.body

    @property
    def modified(self) -> bool:
        """Whether the text differs from what was opened or last saved."""
        return self.body_text != self.original_body

    @property
    def blocks_lock(self) -> bool:
        """Unsaved text holds the idle lock off."""
        return self.modified

    # --- actions -----------------------------------------------------------

    def action_save(self) -> None:
        """ctrl+s: file the day and carry on writing it.

        The one key that asks whose version of the day to keep when
        another Zecret saved it too; see _save_onto_reread.
        """
        before = self.zecret.diary
        if self._save():
            self.set_error("")
            self.notify(SAVED if self.zecret.diary is before else SAVED_WITH_THEIRS)
        elif self.theirs is not None:
            self.app.push_screen(
                ConfirmScreen(
                    WHOSE_DAY,
                    confirm_label=TAKE_THEIRS,
                    save_label=SAVE_MINE,
                    # Both other answers throw a version of the day away,
                    # so a stray Enter must do neither.
                    focus=Choice.CANCEL,
                ),
                self.settle_whose,
            )

    def _save(self) -> bool:
        """Persist the day's text, and say whether it reached disk.

        On False the caller stays put: the reason is on the error line and
        the text is still only in the widget.
        """
        # Nothing changed since the last save, so nothing is written. A
        # write per reflexive ctrl+s would restamp updated_at and turn
        # another Zecret's save into a conflict over a day nobody edited.
        # A never-written day is not "unmodified"; it is empty, and
        # refused below.
        if not self.modified and self.entry is not None:
            return True

        body = self.body_text
        # Whitespace-only counts as blank: the list would show it as
        # "(empty)". The text is otherwise stored exactly as typed.
        if not body.strip():
            self.set_error(EMPTY_ENTRY)
            return False

        # Anything found in another Zecret last time is stale by now.
        self.theirs = None
        diary, key = self.zecret.unlocked
        try:
            self._file(diary, key, body, self.entry)
        except ZecretConflictError:
            return self._save_onto_reread(key, body)
        except OSError as error:
            return self._refuse(save_error(error))
        return True

    def _file(self, diary: DiaryFile, key: bytes, body: str, existing: Entry | None) -> None:
        """Make `body` this day's entry in `diary`, on top of `existing`, and save.

        On success `diary` is the session's diary and this screen holds
        the new entry. On failure nothing has changed: saving() puts the
        diary back.

        Raises:
            ZecretConflictError, OSError: as DiaryFile.save() does.
        """
        entry = Entry.new(self.date, body) if existing is None else existing.edited(body)
        with diary.saving(key):
            if existing is None:
                diary.add_entry(entry)
            else:
                diary.update_entry(entry)
        self.zecret.diary = diary
        self.entry = entry
        self.show_title()

    def _save_onto_reread(self, key: bytes, body: str) -> bool:
        """Another Zecret saved meanwhile: file the day on top of what it wrote.

        Re-reads the diary. If this day there is what this screen opened,
        the other session changed only other days: the day is filed into
        the re-read diary, which becomes the session's. Nothing of either
        session's is lost.

        If the other session wrote, edited or deleted this day too,
        nothing is written and the re-read diary is held for ctrl+s to
        ask about. Nothing is adopted until then, so a save by any other
        road is refused again rather than writing over the other version.

        Compared by value: a re-read builds new objects for every day.
        """
        diary, _ = self.zecret.unlocked
        try:
            theirs = DiaryFile.reopen(diary.path, key)
        except ZecretDecryptError:
            return self._refuse(REKEYED_ELSEWHERE)
        except (OSError, ValueError) as error:
            return self._refuse(reread_error(error))
        if theirs.entry_for(self.date) != self.entry:
            self.theirs = theirs
            return self._refuse(DAY_CHANGED_ELSEWHERE)
        try:
            self._file(theirs, key, body, self.entry)
        except (OSError, ZecretConflictError) as error:
            # One attempt per keypress: the next ctrl+s re-reads afresh.
            return self._refuse(save_error(error))
        return True

    def _refuse(self, reason: str) -> bool:
        """Say why the day was not saved, and stay put. Always False."""
        self.set_error(reason)
        self.notify("The entry was not saved.", severity="error")
        return False

    def settle_whose(self, choice: Choice | None) -> None:
        """Act on whose version of the day to keep.

        Mine: filed over theirs, into the diary as the other session left
        it, so every other day of theirs survives. Theirs: the re-read
        diary becomes the session's and their version of the day (or an
        empty day, if theirs was a deletion) replaces the editor's text.
        Anything else writes nothing.
        """
        theirs, self.theirs = self.theirs, None
        if theirs is None or choice not in (Choice.SAVE, Choice.CONFIRM):
            return
        if choice is Choice.SAVE:
            _, key = self.zecret.unlocked
            try:
                self._file(theirs, key, self.body_text, theirs.entry_for(self.date))
            except (OSError, ZecretConflictError) as error:
                self._refuse(save_error(error))
                return
            self.set_error("")
            self.notify(SAVED_OVER_THEIRS)
            return
        self.zecret.diary = theirs
        self.entry = theirs.entry_for(self.date)
        self.body.text = self.original_body
        self.show_title()
        self.set_error("")
        self.notify(TOOK_THEIRS)

    def action_toggle_mask(self) -> None:
        """ctrl+r: cover the writing, or uncover it.

        The state lives on the app so it survives opening another day,
        and is never persisted.
        """
        self.zecret.masked = not self.zecret.masked
        self.body.masked = self.zecret.masked

    def action_save_and_lock(self) -> None:
        """ctrl+l: save the day, then lock.

        Saves rather than asks: a question would leave the diary open
        behind it. An untouched editor locks straight away. A day that
        will not save keeps you here with the reason.
        """
        if not self.modified:
            self.zecret.lock()
            return
        if self._save():
            self.zecret.lock(SAVED_AND_LOCKED)

    def action_back(self) -> None:
        """Leave the day, asking first if that would throw writing away."""
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

        Anything but the two answers that leave stays here with the text
        untouched.
        """
        if choice is Choice.CONFIRM:
            self.dismiss()
        elif choice is Choice.SAVE:
            before = self.zecret.diary
            if self._save():
                # Notified before the dismiss; it outlives this screen and
                # is read over the list.
                self.notify(SAVED if self.zecret.diary is before else SAVED_WITH_THEIRS)
                self.dismiss()

    def save_pending(self) -> bool:
        """Write the day out for someone who is quitting or locking over it."""
        return self._save()
