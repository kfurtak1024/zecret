"""Settings screen: currently just master password change.

Flow: prompt for current password (re-verify against app.key/derive), new
password, confirm new password. On confirm, call
app.diary.change_password(new_password) to get a new key, update app.key,
then app.diary.save(app.key) to persist everything re-encrypted under the
new key and new KDF salt.

The current password is re-verified via DiaryFile.verify_password() rather
than derive_key(), which screens may not call. Without that check, anyone
at an unattended unlocked terminal could re-key the diary without knowing
the old password, and there is no recovery mechanism by design.

If the save fails after re-keying, the new KDF params are rolled back. They
would otherwise be left describing a key that never reached disk, and the
next save under the old key would write new params over old ciphertext,
leaving the file unopenable by either password.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, Label

from zecret.screens.base import ZecretScreen

WRONG_CURRENT = "That is not your current password."
EMPTY_NEW = "Choose a new password."
MISMATCH = "The new passwords do not match."
CHANGED = "Master password changed."


class SettingsScreen(ZecretScreen):
    """Change the master password."""

    SUB_TITLE = "Settings"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", priority=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="settings-box"):
            yield Label("Change master password", id="settings-title")
            yield Label(
                "Your entries are re-encrypted under the new password. "
                "There is no recovery if you forget it.",
                id="settings-hint",
            )
            yield Input(placeholder="Current password", password=True, id="current")
            yield Input(placeholder="New password", password=True, id="new")
            yield Input(placeholder="Confirm new password", password=True, id="confirm")
            yield Label("", id="settings-error")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#current", Input).focus()

    def value_of(self, field: str) -> str:
        return self.query_one(f"#{field}", Input).value

    async def on_input_submitted(self, _event: Input.Submitted) -> None:
        await self.change_password()

    async def change_password(self) -> None:
        current, new, confirm = (self.value_of(f) for f in ("current", "new", "confirm"))
        diary, key = self.zecret.unlocked

        if not new:
            self.set_error(EMPTY_NEW)
            return
        if new != confirm:
            self.set_error(MISMATCH)
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
        except OSError as error:
            # Undo the re-key so memory and disk agree again; app.key is
            # deliberately still the old key at this point.
            diary.kdf_params = previous_params
            self.set_error(f"Could not save: {error.strerror or error}.")
            self.notify("Your password was not changed.", severity="error")
            return

        self.zecret.key = new_key
        self.clear_inputs()
        self.notify(CHANGED)
        self.dismiss()

    def action_back(self) -> None:
        self.dismiss()

    def set_error(self, message: str) -> None:
        self.query_one("#settings-error", Label).update(message)

    def clear_inputs(self) -> None:
        for widget in self.query(Input):
            widget.value = ""
