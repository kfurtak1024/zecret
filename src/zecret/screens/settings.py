"""Settings screen: appearance, and the master password.

Appearance is a theme picker over a curated set of Textual's themes. It
applies as the selection moves, so you see the diary in it rather than a
swatch, and saves immediately -- there is no "apply" button to forget. The
list is curated rather than Textual's full set: each name here has been
rendered against this app's own styling and checked that the month
headings, the highlighted row and the footer all stay legible. Saving is
best effort; a preferences file that cannot be written costs you the
setting next launch, never the session you are in.

Password flow: prompt for current password (re-verify against
app.key/derive), new password, confirm new password. On confirm, call
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
from textual.containers import VerticalScroll
from textual.widgets import Footer, Input, Label, Select

from zecret.screens.base import DIARY_CHANGED, ZecretScreen
from zecret.screens.header import DiaryHeader
from zecret.storage import ZecretConflictError

WRONG_CURRENT = "That is not your current password."
EMPTY_NEW = "Choose a new password."
MISMATCH = "The new passwords do not match."
CHANGED = "Master password changed."
THEME_NOT_SAVED = "Theme applied, but could not be saved for next time."

#: The themes offered, as (what the user reads, what Textual calls it).
#: A shortlist, not all 21 Textual ships: the ansi ones borrow the
#: terminal's own palette and render this app's accents unpredictably, and
#: a dropdown is a worse place to browse than a diary is to read.
THEMES: list[tuple[str, str]] = [
    ("Dark", "textual-dark"),
    ("Light", "textual-light"),
    ("Nord", "nord"),
    ("Gruvbox", "gruvbox"),
    ("Dracula", "dracula"),
    ("Catppuccin Mocha", "catppuccin-mocha"),
    ("Catppuccin Latte", "catppuccin-latte"),
    ("Solarized Light", "solarized-light"),
]


class SettingsScreen(ZecretScreen):
    """Pick a theme, and change the master password."""

    SUB_TITLE = "Settings"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", priority=True),
    ]

    def compose(self) -> ComposeResult:
        yield DiaryHeader()
        # Scrolls: two sections of fields do not fit a 24-row terminal, and
        # a card that simply runs off the bottom hides the confirm field.
        with VerticalScroll(id="settings-box"):
            yield Label("Appearance", classes="section-title")
            yield Label(
                "Applied as you choose it, and kept for next time.",
                classes="section-hint",
            )
            yield Select(
                THEMES,
                value=self.zecret.config.theme,
                allow_blank=False,
                id="theme",
            )

            yield Label("Change master password", classes="section-title")
            yield Label(
                "Your entries are re-encrypted under the new password. "
                "There is no recovery if you forget it.",
                classes="section-hint",
            )
            yield Input(placeholder="Current password", password=True, id="current")
            yield Input(placeholder="New password", password=True, id="new")
            yield Input(placeholder="Confirm new password", password=True, id="confirm")
            yield Label("", id="settings-error")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#current", Input).focus()

    # --- appearance --------------------------------------------------------

    def on_select_changed(self, event: Select.Changed) -> None:
        """Apply the chosen theme and remember it."""
        theme = event.value
        # Select is typed as possibly blank; this one is allow_blank=False,
        # so anything else is not a theme name and there is nothing to do.
        if not isinstance(theme, str) or theme == self.zecret.theme:
            return

        self.zecret.apply_theme(theme)
        self.zecret.config.theme = theme
        try:
            self.zecret.config.save()
        except OSError:
            # The theme is already applied; only its persistence failed.
            self.notify(THEME_NOT_SAVED, severity="warning")

    def value_of(self, field: str) -> str:
        return self.query_one(f"#{field}", Input).value

    async def on_input_submitted(self, _event: Input.Submitted) -> None:
        await self.change_password()

    async def change_password(self) -> None:
        current, new, confirm = (self.value_of(f) for f in ("current", "new", "confirm"))
        diary, key = self.zecret.unlocked

        # Both of these clear the fields, like every other failure here and
        # on the unlock screen: a rejected attempt should not leave a
        # password sitting in a widget on an unattended terminal. It costs
        # retyping a password you got wrong anyway.
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
            self.set_error(
                DIARY_CHANGED
                if isinstance(error, ZecretConflictError)
                else f"Could not save: {error.strerror or error}."
            )
            self.notify("Your password was not changed.", severity="error")
            return

        self.zecret.key = new_key
        self.clear_inputs()
        self.notify(CHANGED)
        self.dismiss()

    def action_back(self) -> None:
        # This screen's escape binding is priority, so it would otherwise
        # win over the dropdown's own -- closing the whole screen when the
        # user meant to close the list they just opened.
        theme = self.query_one("#theme", Select)
        if theme.expanded:
            theme.expanded = False
            return
        self.dismiss()

    def set_error(self, message: str) -> None:
        self.query_one("#settings-error", Label).update(message)

    def clear_inputs(self) -> None:
        for widget in self.query(Input):
            widget.value = ""
