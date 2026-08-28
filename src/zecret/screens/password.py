"""The dialog that changes the master password.

A dialog rather than a third section of the settings form, because this is
the one thing in Zecret that cannot be undone. Three password fields
sitting under two dropdowns were something you could scroll past, or tab
into by accident, and the warning that goes with them was read as the
small print at the bottom of a form. Opened deliberately from a button,
the warning is the first thing on the screen and the fields are the only
other thing on it.

The flow is unchanged and still the important part: the current password
is re-verified through DiaryFile.verify_password() rather than derive_key(),
which screens may not call. Without that check, anyone at an unattended
unlocked terminal could re-key the diary without knowing the old password,
and there is no recovery mechanism by design.

If the save fails after re-keying, the new KDF params are rolled back. They
would otherwise be left describing a key that never reached disk, and the
next save under the old key would write new params over old ciphertext,
leaving the file unopenable by either password.

On the class: ModalScreen comes first and FormScreen second, and the order
is load-bearing both ways round. FormScreen is what a screen with fields
and an error line inherits -- the typed app, the error line, and emptying
the fields after a rejected attempt, which is a security behaviour and not
a convenience, so it must not be a second copy here. ModalScreen has to
come first because Textual builds a widget's styling by walking the class
hierarchy, and behind FormScreen stands a plain Screen whose opaque
background would otherwise win over the translucent one that makes a modal
read as a dialog over the settings rather than instead of them. This is
only possible because this dialog dismisses nothing: a modal that returns
a value is a Screen of a different type and cannot inherit FormScreen at
all -- see the note in base.py, and DatePromptScreen, which is one.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label

from zecret.screens.base import NO_RECOVERY, FormScreen, save_error
from zecret.screens.header import DiaryFooter
from zecret.storage import ZecretConflictError

TITLE = "Change master password"
WRONG_CURRENT = "That is not your current password."
EMPTY_NEW = "Choose a new password."
MISMATCH = "The new passwords do not match."
CHANGED = "Master password changed."


class PasswordScreen(ModalScreen[None], FormScreen):
    """Ask for the current password and a new one, and re-key the diary."""

    ERROR_ID = "password-error"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def compose(self) -> ComposeResult:
        # The title, the warning and the three fields come to exactly the
        # eighteen rows a twenty-four-row terminal leaves inside this
        # card, which is deliberate: the warning is the reason this dialog
        # exists, and a warning you have to scroll to reach is the thing
        # it was moved out of the settings form to stop being. It still
        # scrolls, for the terminal that is shorter still.
        with VerticalScroll(id="password-box"):
            yield Label(TITLE, id="password-title")
            # Above the fields: it is the thing to know before choosing a
            # password, not a footnote to having chosen one.
            yield Label(NO_RECOVERY, classes="caution")
            yield Input(placeholder="Current password", password=True, id="current")
            yield Input(placeholder="New password", password=True, id="new")
            yield Input(placeholder="Confirm new password", password=True, id="confirm")
            yield Label("", id="password-error")
        # The screen underneath keeps rendering its own bar, and every key
        # on it is dead while this dialog has focus. See CLAUDE.md.
        yield DiaryFooter()

    def on_mount(self) -> None:
        self.query_one("#current", Input).focus()

    def value_of(self, field: str) -> str:
        return self.query_one(f"#{field}", Input).value

    async def on_input_submitted(self, _event: Input.Submitted) -> None:
        """Enter in any of the three fields submits the change.

        The same as the unlock screen, and the reason this dialog carries
        no buttons of its own: a question with two or three answers needs
        them (see ConfirmScreen), and a form has one answer -- what you
        typed -- with escape for the way out.
        """
        await self.change_password()

    async def change_password(self) -> None:
        current, new, confirm = (self.value_of(f) for f in ("current", "new", "confirm"))
        diary, key = self.zecret.unlocked

        # Every failure here clears the fields, as on the unlock screen: a
        # rejected attempt should not leave a password sitting in a widget
        # on an unattended terminal. It costs retyping a password you got
        # wrong anyway.
        if not new:
            self.set_error(EMPTY_NEW)
            self.clear_inputs()
            return
        if new != confirm:
            self.set_error(MISMATCH)
            self.clear_inputs()
            return

        # Argon2id, off the event loop -- once to check the old password and
        # again inside change_password() to derive the new key.
        if not await asyncio.to_thread(diary.verify_password, current, key):
            self.set_error(WRONG_CURRENT)
            self.clear_inputs()
            return

        self.set_error("")
        previous_params = diary.kdf_params
        new_key = await asyncio.to_thread(diary.change_password, new)
        try:
            await asyncio.to_thread(diary.save, new_key)
        except (OSError, ZecretConflictError) as error:
            # Undo the re-key so memory and disk agree again; app.key is
            # deliberately still the old key at this point.
            diary.kdf_params = previous_params
            self.set_error(save_error(error))
            self.notify("Your password was not changed.", severity="error")
            return

        self.zecret.key = new_key
        self.clear_inputs()
        # Said before leaving and outliving the dialog: a notification
        # belongs to the app, so this one is still there to be read over
        # the settings screen underneath.
        self.notify(CHANGED)
        self.dismiss()

    def action_cancel(self) -> None:
        """Escape closes the dialog, changing nothing.

        The fields go with it -- the screen is discarded on dismissal --
        so a password typed here and thought better of does not sit in a
        widget behind the settings form.
        """
        self.dismiss()
