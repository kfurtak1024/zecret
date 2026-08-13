"""Password entry screen: unlocks an existing diary or creates a new one.

If app.diary_path does not exist, this screen should instead prompt to
create a new diary (set password + confirm), calling DiaryFile.create_new().
Otherwise it prompts for the password and calls DiaryFile.unlock(),
catching ZecretDecryptError to show an inline "incorrect password" message
without leaking whether the failure was due to a wrong password vs. a
corrupted file.

A short artificial delay (e.g. 300-500ms) should be added after a failed
attempt to mildly slow down brute-force guessing in an interactive session.

Which of the two flows to present is decided by ZecretApp and passed in as
`creating`, keeping the "does the file exist" question with the app that
owns the path (and letting tests drive either flow directly).
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, Label

from zecret.crypto import ZecretDecryptError
from zecret.screens.base import ZecretScreen
from zecret.storage import DiaryFile

# Deliberately the same message for a wrong password and for an unreadable
# file: distinguishing them would tell an attacker that a given path holds a
# real, intact diary.
UNLOCK_FAILED = "Incorrect password."


class UnlockScreen(ZecretScreen):
    """Prompts for the master password and unlocks (or creates) the diary."""

    # ctrl+q already quits app-wide, but it is hidden by default. Someone
    # who cannot get in needs an obvious way out, so show it here.
    # "app.quit" rather than "quit": the action is dispatched on this
    # screen, which has no action_quit, and would fall through to the app's
    # own ctrl+q binding by luck alone.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+q", "app.quit", "Quit", show=True, priority=True)
    ]

    #: Pause after a failed attempt, to take the edge off interactive
    #: brute-forcing. Lowered in tests to keep them fast.
    FAILED_ATTEMPT_DELAY = 0.4

    def __init__(self, *, creating: bool) -> None:
        """Args:
        creating: True to run the "set a new password" flow, False to
            prompt for an existing diary's password.
        """
        super().__init__()
        self.creating = creating

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="unlock-box"):
            if self.creating:
                yield Label("Create a new diary", id="unlock-title")
                yield Label(
                    f"No diary at {self.zecret.diary_path}. Choose a master "
                    "password — it cannot be recovered.",
                    id="unlock-hint",
                )
            else:
                yield Label("Unlock your diary", id="unlock-title")
            yield Input(placeholder="Master password", password=True, id="password")
            if self.creating:
                yield Input(placeholder="Confirm password", password=True, id="confirm")
            yield Label("", id="unlock-error")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = "New diary" if self.creating else "Locked"
        self.query_one("#password", Input).focus()

    async def on_input_submitted(self, _event: Input.Submitted) -> None:
        """Enter in either field submits the form."""
        await self.attempt()

    async def attempt(self) -> None:
        """Try to open (or create) the diary with the entered password."""
        password = self.query_one("#password", Input).value

        if self.creating:
            if not password:
                await self.fail("Choose a password.")
                return
            if password != self.query_one("#confirm", Input).value:
                await self.fail("Passwords do not match.")
                return

        self.set_error("")
        path = self.zecret.diary_path
        try:
            # Argon2id is intentionally slow; run it off the event loop so
            # the UI does not freeze while the key is derived.
            open_diary = DiaryFile.create_new if self.creating else DiaryFile.unlock
            diary, key = await asyncio.to_thread(open_diary, path, password)
        except (ZecretDecryptError, ValueError):
            # ValueError covers a malformed or unsupported file; reported
            # identically to a bad password, on purpose.
            await self.fail(UNLOCK_FAILED)
            return
        except FileExistsError:
            await self.fail("A diary already exists at that path.")
            return
        except FileNotFoundError:
            await self.fail("The diary file has gone missing.")
            return
        except OSError as error:
            await self.fail(f"Could not open the diary: {error.strerror or error}.")
            return

        self.zecret.diary = diary
        self.zecret.key = key
        # Drop the typed password from the widget as soon as it is spent.
        self.clear_inputs()
        self.dismiss()

    async def fail(self, message: str) -> None:
        """Show an inline error, clear the inputs, and pause briefly."""
        self.set_error(message)
        self.clear_inputs()
        inputs = list(self.query(Input))
        for widget in inputs:
            widget.disabled = True
        try:
            await asyncio.sleep(self.FAILED_ATTEMPT_DELAY)
        finally:
            for widget in inputs:
                widget.disabled = False
            self.query_one("#password", Input).focus()

    def set_error(self, message: str) -> None:
        self.query_one("#unlock-error", Label).update(message)

    def clear_inputs(self) -> None:
        for widget in self.query(Input):
            widget.value = ""
