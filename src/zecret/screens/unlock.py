"""Password entry screen: unlocks an existing diary or creates a new one.

Creating asks for a password and a confirmation and calls
DiaryFile.create_new(). Unlocking calls DiaryFile.unlock() and says which
thing went wrong: the password, damage to a file the password does open,
a file from a newer Zecret, or a file that is no diary. Telling these
apart gives an attacker nothing the file does not, and a writer with one
damaged record must not be told they forgot their password.

Key derivation runs off the event loop, with a status line and the fields
disabled while it does. Every failed attempt pauses for
FAILED_ATTEMPT_DELAY before the fields come back.

ZecretApp decides which flow to show and passes it as `creating`, so the
file can still appear or vanish before the password is submitted. A diary
that appeared turns this into the unlock screen for it. A diary that
vanished is reported and the screen stays as it is: offering to create
one there could write an empty diary where the real one is only on an
unmounted disk.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import Input, Label

from zecret.crypto import ZecretDecryptError
from zecret.screens.base import NO_RECOVERY, FormScreen, card, plain
from zecret.screens.header import DiaryFooter, DiaryHeader
from zecret.storage import DiaryFile, ZecretDamagedError, ZecretVersionError

# Every line below must fit the create card's 54 columns, the narrower of
# the two cards this row sits in.
UNLOCK_FAILED = "Incorrect password."
DIARY_DAMAGED = "The password is right, but the diary file is damaged."
DIARY_TOO_NEW = "A newer Zecret wrote this diary. Upgrade to open it."
NOT_A_DIARY = "This file is not a diary Zecret can read."

#: Argon2id could not get the memory the diary's header asks for.
OUT_OF_MEMORY = "Not enough free memory to open the diary."

#: Said while the key is being derived, which takes about a second.
UNLOCKING = "Unlocking…"
CREATING = "Creating your diary…"

#: Another Zecret created the diary while a password was being chosen
#: here. The screen has become the unlock screen by the time this shows.
DIARY_APPEARED = "A diary appeared here meanwhile. Enter its password."

#: The confirmation field's placeholder when creating a diary.
CONFIRM_HINT = "Confirm password, then press Enter"


class UnlockScreen(FormScreen):
    """Prompts for the master password and unlocks (or creates) the diary."""

    ERROR_ID = "unlock-error"

    # Shown here because someone who cannot get in needs an obvious way
    # out. "app.quit", not "quit": the action is dispatched on this screen,
    # which has no action_quit.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+q", "app.quit", "Quit", show=True, priority=True)
    ]

    #: Pause after a failed attempt, against interactive brute-forcing.
    #: Lowered in tests.
    FAILED_ATTEMPT_DELAY = 0.4

    def __init__(self, *, creating: bool) -> None:
        """Args:
        creating: True to set a new password for a new diary, False to
            ask for an existing diary's password.
        """
        super().__init__()
        self.creating = creating

    def compose(self) -> ComposeResult:
        yield DiaryHeader()
        # A scrolling card, so a short terminal does not lose the
        # confirmation field off the bottom.
        with card("unlock-box"):
            if self.creating:
                yield Label("Create a new diary", id="unlock-title")
                # Plain: the path is the user's.
                yield Label(
                    plain(
                        f"No diary at {self.zecret.diary_path}. Choose a master password for it."
                    ),
                    id="unlock-hint",
                )
                # Above the fields: it is the thing to know before
                # choosing a password.
                yield Label(NO_RECOVERY, classes="caution")
            else:
                yield Label("Unlock your diary", id="unlock-title")
            yield Input(placeholder="Master password", password=True, id="password")
            if self.creating:
                # The placeholder says how the form finishes; there is no
                # button to say it.
                yield Input(placeholder=CONFIRM_HINT, password=True, id="confirm")
            yield Label("", id="unlock-error")
        yield DiaryFooter()

    def on_mount(self) -> None:
        self.sub_title = "New diary" if self.creating else "Locked"
        self.query_one("#password", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Rate a password while it is being chosen.

        Only when creating: an existing password is recalled, not chosen,
        and rating it would be a remark about the diary to anyone
        watching.
        """
        if self.creating and event.input.id == "password":
            self.advise_on_password(event.value)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter submits the form, or moves on to the confirmation while it
        is still empty (see FormScreen.advance)."""
        if self.advance(event.input):
            return
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

        # Argon2id is slow on purpose. Say so and disable the fields until
        # it answers, so the wait does not read as a dead screen and a
        # second Enter has nowhere to go.
        self.set_status(CREATING if self.creating else UNLOCKING)
        for widget in self.query(Input):
            widget.disabled = True
        path = self.zecret.diary_path
        try:
            # Off the event loop, so the UI stays alive meanwhile.
            open_diary = DiaryFile.create_new if self.creating else DiaryFile.unlock
            diary, key = await asyncio.to_thread(open_diary, path, password)
        except ZecretDecryptError:
            await self.fail(UNLOCK_FAILED)
            return
        except ZecretDamagedError:
            await self.fail(DIARY_DAMAGED)
            return
        except ZecretVersionError:
            await self.fail(DIARY_TOO_NEW)
            return
        except ValueError:
            # Anything else that will not parse: no password could open it.
            await self.fail(NOT_A_DIARY)
            return
        except MemoryError:
            await self.fail(OUT_OF_MEMORY)
            return
        except FileExistsError:
            await self.become_unlock()
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

    async def become_unlock(self) -> None:
        """Turn from creating a diary into unlocking the one now there.

        Another Zecret created the diary while this one was choosing a
        password, and the create rightly refused to write over it.
        Recomposed rather than edited in place, so everything follows
        `creating` from the one compose(). The password typed goes with
        the old fields: it was chosen for a new diary, not this one.
        """
        self.creating = False
        await self.recompose()
        self.sub_title = "Locked"
        self.set_error(DIARY_APPEARED)
        self.query_one("#password", Input).focus()

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
