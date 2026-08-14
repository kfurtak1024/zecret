"""Password entry screen: unlocks an existing diary or creates a new one.

In the create flow it asks for a password and a confirmation and calls
DiaryFile.create_new(). In the unlock flow it asks for the password and
calls DiaryFile.unlock(), reporting ZecretDecryptError and a malformed
file identically -- an inline "incorrect password" -- so that nothing here
tells an attacker whether a given path holds a real, intact diary.

Every failed attempt pauses for FAILED_ATTEMPT_DELAY before the fields
come back, which takes the edge off interactive brute-forcing. Key
derivation itself runs off the event loop: Argon2id is deliberately slow,
and the UI would otherwise freeze for the length of every attempt.

Which of the two flows to present is decided by ZecretApp and passed in as
`creating`, keeping the "does the file exist" question with the app that
owns the path (and letting tests drive either flow directly). Because that
decision is made when the screen is built, the file can still turn out to
be missing or already there by the time the password is submitted; both
are handled as ordinary failures rather than crashes.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.widgets import Footer, Input, Label

from zecret.crypto import ZecretDecryptError
from zecret.screens.base import FormScreen
from zecret.screens.header import DiaryHeader
from zecret.storage import DiaryFile

# Deliberately the same message for a wrong password and for an unreadable
# file: distinguishing them would tell an attacker that a given path holds a
# real, intact diary.
UNLOCK_FAILED = "Incorrect password."


class UnlockScreen(FormScreen):
    """Prompts for the master password and unlocks (or creates) the diary."""

    ERROR_ID = "unlock-error"

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
        yield DiaryHeader()
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
