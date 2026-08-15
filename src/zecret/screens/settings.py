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
from textual.widgets import Input, Label, Select

from zecret.config import DEFAULT_LOCK_AFTER_MINUTES
from zecret.screens.base import FormScreen, save_error
from zecret.screens.header import DiaryFooter, DiaryHeader
from zecret.storage import ZecretConflictError

#: How long the diary may sit untouched, as (what the user reads, minutes).
#: Zero never locks, which is offered rather than hidden -- someone writing
#: on a machine only they can reach should be able to say so.
LOCK_TIMEOUTS: list[tuple[str, int]] = [
    ("After 1 minute", 1),
    ("After 5 minutes", 5),
    ("After 15 minutes", 15),
    ("After 30 minutes", 30),
    ("After 1 hour", 60),
    ("Never", 0),
]

WRONG_CURRENT = "That is not your current password."
EMPTY_NEW = "Choose a new password."
MISMATCH = "The new passwords do not match."
CHANGED = "Master password changed."
THEME_NOT_SAVED = "Theme applied, but could not be saved for next time."
LOCK_NOT_SAVED = "Lock timing applied, but could not be saved for next time."

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


class SettingsScreen(FormScreen):
    """Pick a theme, and change the master password."""

    SUB_TITLE = "Settings"
    ERROR_ID = "settings-error"

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

            yield Label("Locking", classes="section-title")
            yield Label(
                "Zecret puts the diary away when you stop typing, and asks "
                "for your password again.",
                classes="section-hint",
            )
            yield Select(
                LOCK_TIMEOUTS,
                value=self.lock_after_choice(),
                allow_blank=False,
                id="lock-after",
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
        yield DiaryFooter()

    def on_mount(self) -> None:
        # The top of the form, not the password fields at the bottom of it.
        # This screen scrolls, and focusing the last section would open it
        # already scrolled past the two settings most people came to
        # change. Arrow keys on a closed dropdown open it rather than
        # moving the selection, so landing here changes nothing by itself.
        self.query_one("#theme", Select).focus()

    def lock_after_choice(self) -> int:
        """The saved timeout, or the nearest one this screen can show.

        The file may hold any whole number of minutes -- it was hand-edited,
        or written by a version offering a different set. Falling back to
        the default beats starting the dropdown on a value it cannot
        display, which Select refuses outright.
        """
        saved = self.zecret.config.lock_after_minutes
        offered = {minutes for _, minutes in LOCK_TIMEOUTS}
        return saved if saved in offered else DEFAULT_LOCK_AFTER_MINUTES

    # --- appearance --------------------------------------------------------

    def on_select_changed(self, event: Select.Changed) -> None:
        """Route a dropdown's new value to whichever setting it belongs to."""
        if event.select.id == "theme":
            self.choose_theme(event.value)
        else:
            self.choose_lock_after(event.value)

    def choose_theme(self, theme: object) -> None:
        """Apply the chosen theme and remember it."""
        # Select is typed as possibly blank; this one is allow_blank=False,
        # so anything else is not a theme name and there is nothing to do.
        if not isinstance(theme, str) or theme == self.zecret.theme:
            return

        self.zecret.apply_theme(theme)
        self.zecret.config.theme = theme
        self.remember(THEME_NOT_SAVED)

    def choose_lock_after(self, minutes: object) -> None:
        """Remember how long the diary may sit idle before locking itself.

        Nothing is restarted: the idle check reads the setting each time it
        runs, so a longer wait takes effect on the next tick and a shorter
        one applies to the quiet that has already passed.
        """
        if not isinstance(minutes, int) or minutes == self.zecret.config.lock_after_minutes:
            return

        self.zecret.config.lock_after_minutes = minutes
        self.remember(LOCK_NOT_SAVED)

    def remember(self, complaint: str) -> None:
        """Persist the preferences, saying so only if it did not work.

        Best effort by design: a preferences file that cannot be written
        costs the setting next launch, never the session you are in.
        """
        try:
            self.zecret.config.save()
        except OSError:
            self.notify(complaint, severity="warning")

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
            self.set_error(save_error(error))
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
