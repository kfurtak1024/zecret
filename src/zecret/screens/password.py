"""The dialog that changes the master password.

A dialog rather than fields on the settings form, because this is the one
thing in Zecret that cannot be undone: the warning is the first thing on
the screen and the fields are the only other thing on it.

The current password is re-verified through DiaryFile.verify_password(),
so nobody at an unattended unlocked terminal can re-key the diary without
it. If the save fails after re-keying, DiaryFile.change_password() rolls
the KDF params back itself.

While the re-key runs the screen is `working`: escape, ctrl+l, ctrl+q and
the idle timer all wait for it, and a lock or quit asked for meanwhile
happens when it ends, saying how it ended.

Class order: ModalScreen first, FormScreen second, and both matter.
FormScreen supplies the error line and clear_inputs. ModalScreen must come
first because Textual builds styling by walking the class hierarchy, and
the plain Screen behind FormScreen would otherwise give this an opaque
background. This only works because the dialog dismisses nothing.
"""

from __future__ import annotations

import asyncio
from enum import Enum, auto
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import Input, Label

from zecret.screens.base import NO_RECOVERY, FormScreen, card, save_error
from zecret.screens.header import DiaryFooter
from zecret.storage import ZecretConflictError

TITLE = "Change master password"
WRONG_CURRENT = "That is not your current password."
EMPTY_NEW = "Choose a new password."
MISMATCH = "The new passwords do not match."
CHANGED = "Master password changed."

#: The last field's placeholder, which is also how the form says it is
#: submitted.
CONFIRM_HINT = "Confirm new password, then press Enter"
NOT_CHANGED = "Your password was not changed."
#: Argon2id could not get the memory it needs to check or derive a key.
OUT_OF_MEMORY = "Not enough free memory to change the password."

#: Said on the error row while the fields are disabled.
CHECKING = "Checking your current password…"
REKEYING = "Re-encrypting the diary under the new password…"


class Outcome(Enum):
    """How a change of password ended."""

    CHANGED = auto()
    #: The current password was wrong.
    REFUSED = auto()
    #: The change could not be made or saved.
    FAILED = auto()


#: What a quit that waited for the change leaves in the terminal, printed
#: after the app has gone.
QUIT_AFTER = {
    Outcome.CHANGED: "Zecret: master password changed.",
    Outcome.REFUSED: "Zecret: your password was not changed.",
    Outcome.FAILED: "Zecret: your password was not changed.",
}

#: What a lock that waited for the change says.
LOCKED_AFTER = {
    Outcome.CHANGED: "Master password changed, and locked.",
    Outcome.REFUSED: "Locked. Your password was not changed.",
    Outcome.FAILED: "Locked. Your password was not changed.",
}


class PasswordScreen(ModalScreen[None], FormScreen):
    """Ask for the current password and a new one, and re-key the diary."""

    ERROR_ID = "password-error"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=True),
        Binding("ctrl+l", "app.lock", "Lock", priority=True),
    ]

    def compose(self) -> ComposeResult:
        # Title, warning and three fields come to exactly the eighteen
        # rows a 24-row terminal leaves inside this card, so the warning
        # never needs scrolling to. Adding a row here breaks that.
        with card("password-box"):
            yield Label(TITLE, id="password-title")
            yield Label(NO_RECOVERY, classes="caution")
            yield Input(placeholder="Current password", password=True, id="current")
            yield Input(placeholder="New password", password=True, id="new")
            # No button (its three rows would push the warning off a
            # 24-row terminal), so the placeholder says Enter submits.
            yield Input(placeholder=CONFIRM_HINT, password=True, id="confirm")
            yield Label("", id="password-error")
        yield DiaryFooter()

    def on_mount(self) -> None:
        self.query_one("#current", Input).focus()

    def value_of(self, field: str) -> str:
        return self.query_one(f"#{field}", Input).value

    def on_input_changed(self, event: Input.Changed) -> None:
        """Rate the new password as it is typed. Only that field: the
        current one is recalled, and the confirmation is a copy."""
        if event.input.id == "new":
            self.advise_on_password(event.value)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter submits once no field is empty, and until then moves to
        the next empty one (see FormScreen.advance)."""
        if self.advance(event.input):
            return
        await self.change_password()

    async def change_password(self) -> None:
        current, new, confirm = (self.value_of(f) for f in ("current", "new", "confirm"))

        # Every failure clears the fields and puts the cursor back in the
        # first one, where retyping starts.
        if not new:
            self.refuse(EMPTY_NEW)
            return
        if new != confirm:
            self.refuse(MISMATCH)
            return

        self.working = True
        inputs = list(self.query(Input))
        for widget in inputs:
            widget.disabled = True
        try:
            outcome = await self.rekey(current, new)
        finally:
            self.working = False
            for widget in inputs:
                widget.disabled = False
        if self.zecret.quit_pending:
            # ctrl+q waited for this. The app is going, so the outcome is
            # left in the terminal.
            self.zecret.exit(message=QUIT_AFTER[outcome])
            return
        if not self.zecret.is_unlocked:
            # Locked by a road that did not wait. Say what became of the
            # password over the lock screen, which now wants the new one.
            if outcome is Outcome.CHANGED:
                self.notify(CHANGED)
            return
        if self.zecret.lock_pending:
            # ctrl+l waited for this. One message for both, since locking
            # clears whatever was said before it.
            self.zecret.lock_pending = False
            self.zecret.lock(LOCKED_AFTER[outcome])
            return
        if outcome is Outcome.CHANGED:
            # Notified before the dismiss; it outlives the dialog and is
            # read over the settings screen.
            self.notify(CHANGED)
            self.dismiss()
            return
        if outcome is Outcome.FAILED:
            self.notify(NOT_CHANGED, severity="error")
        self.query_one("#current", Input).focus()

    async def rekey(self, current: str, new: str) -> Outcome:
        """Check the current password, then re-key the diary under the new one.

        Argon2id runs twice, off the event loop: once to check the old
        password and once inside change_password(). Run with self.working
        set, which holds ctrl+l and the idle timer off until this returns.
        The is_unlocked check before the new key is handed over guards any
        lock that does not go through action_lock: a new key must not be
        given to an app that has just forgotten its old one.
        """
        diary, key = self.zecret.unlocked
        self.set_status(CHECKING)
        try:
            verified = await asyncio.to_thread(diary.verify_password, current, key)
        except MemoryError:
            self.set_error(OUT_OF_MEMORY)
            self.clear_inputs()
            return Outcome.FAILED
        if not verified:
            self.set_error(WRONG_CURRENT)
            self.clear_inputs()
            return Outcome.REFUSED

        self.set_status(REKEYING)
        try:
            new_key = await asyncio.to_thread(diary.change_password, new)
        except MemoryError:
            self.set_error(OUT_OF_MEMORY)
            self.clear_inputs()
            return Outcome.FAILED
        except (OSError, ZecretConflictError) as error:
            # change_password() has put the old KDF params back, so memory
            # and disk agree and app.key is still the old key.
            self.set_error(save_error(error))
            self.clear_inputs()
            return Outcome.FAILED

        if self.zecret.is_unlocked:
            self.zecret.key = new_key
        self.clear_inputs()
        return Outcome.CHANGED

    def refuse(self, message: str) -> None:
        """Say why, empty the fields, and start again from the first one."""
        self.set_error(message)
        self.clear_inputs()
        self.query_one("#current", Input).focus()

    def action_cancel(self) -> None:
        """Escape closes the dialog, changing nothing.

        Not while the diary is being re-encrypted: closing then would not
        stop the change, only the telling of it.
        """
        if not self.working:
            self.dismiss()
