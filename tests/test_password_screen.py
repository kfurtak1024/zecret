"""Tests for PasswordScreen: the dialog that changes the master password.

These moved out of tests/test_settings_screen.py with the flow itself. The
behaviour they guard is unchanged and is the most consequential in the app
-- a re-key that half happens leaves a diary neither password opens.

Required coverage:
    - The button on the settings screen is what opens it, and escape
      closes it again having changed nothing.
    - It carries the warning about a forgotten password, in the same words
      the create screen uses.
    - A correct current password + matching new password re-keys the
      diary: the new password opens it, the old one no longer does, and
      the file gets a fresh salt.
    - app.key is updated, so the session keeps working afterwards.
    - A wrong current password is refused and changes nothing.
    - An empty or mismatched new password is refused.
    - Every refusal empties the fields, so an unattended terminal never
      holds a typed password in a widget.
    - A save that fails does not leave the diary half re-keyed.
    - A short new password is mentioned as it is typed, and is then
      accepted anyway. The note sits on the error row rather than a row of
      its own, and has to keep fitting there: the dialog is sized so the
      warning about a forgotten password never needs scrolling to on a
      24-row terminal, and a wrapped line would take that row back.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from rich.cells import cell_len
from textual.widgets import Button, Input, Label

from zecret.app import ZecretApp
from zecret.crypto import ZecretDecryptError
from zecret.models import Entry
from zecret.screens.base import LENGTH_ADVICE, NO_RECOVERY
from zecret.screens.password import (
    CHANGED,
    EMPTY_NEW,
    MISMATCH,
    WRONG_CURRENT,
    PasswordScreen,
)
from zecret.screens.settings import SettingsScreen
from zecret.screens.unlock import UnlockScreen
from zecret.storage import DiaryFile

PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a completely different passphrase"

TODAY = dt.date.today()
YESTERDAY = TODAY - dt.timedelta(days=1)


# Argon2 at test cost, and no pause after a failed unlock: this suite
# opens diaries constantly (see tests/conftest.py).
pytestmark = pytest.mark.usefixtures("cheap_kdf")


@pytest.fixture(autouse=True)
def instant_failure_delay(monkeypatch):
    monkeypatch.setattr(UnlockScreen, "FAILED_ATTEMPT_DELAY", 0.0)


def tmp_missing_diary(existing: Path) -> Path:
    """A path in the same directory with no diary at it, so the app opens
    the create screen -- the other place this sentence is written."""
    return existing.with_name("unwritten.enc")


@pytest.fixture
def diary_path(tmp_path: Path) -> Path:
    path = tmp_path / "diary.enc"
    diary, key = DiaryFile.create_new(path, PASSWORD)
    diary.add_entry(Entry.new(YESTERDAY, "A body"))
    diary.save(key)
    return path


async def unlock(pilot) -> None:
    pilot.app.screen.query_one("#password", Input).value = PASSWORD
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()


async def open_dialog(pilot) -> None:
    """Settings, then the button that asks for a new password."""
    await pilot.press("s")
    await pilot.pause()
    pilot.app.screen.query_one("#change-password", Button).press()
    await pilot.pause()
    await pilot.pause()


async def submit_change(pilot, current: str, new: str, confirm: str) -> None:
    screen = pilot.app.screen
    screen.query_one("#current", Input).value = current
    screen.query_one("#new", Input).value = new
    confirm_field = screen.query_one("#confirm", Input)
    confirm_field.value = confirm
    confirm_field.focus()
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()


def error_of(screen) -> str:
    return str(screen.query_one("#password-error", Label).content)


# --- getting to it ---------------------------------------------------------


async def test_the_settings_button_opens_the_dialog(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_dialog(pilot)
        assert isinstance(app.screen, PasswordScreen)


async def test_the_current_password_is_focused_so_typing_can_start(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_dialog(pilot)
        assert app.screen.focused is app.screen.query_one("#current", Input)


async def test_escape_closes_it_and_changes_nothing(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_dialog(pilot)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen), "back to where it was opened"

    DiaryFile.unlock(diary_path, PASSWORD)


async def test_it_warns_that_there_is_no_recovery(diary_path):
    """The same sentence as the screen that first asked for a password,
    and from the same constant -- the two must not word it differently.

    This is the reason the flow is a dialog at all: in the settings form
    the warning was the small print under two dropdowns.
    """
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_dialog(pilot)
        cautions = [str(label.content) for label in app.screen.query(".caution").results(Label)]
        assert NO_RECOVERY in cautions


# --- a successful change ---------------------------------------------------


async def test_change_rekeys_the_diary(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_dialog(pilot)
        await submit_change(pilot, PASSWORD, NEW_PASSWORD, NEW_PASSWORD)
        assert isinstance(app.screen, SettingsScreen), "the dialog closes behind it"

    reopened, _ = DiaryFile.unlock(diary_path, NEW_PASSWORD)
    assert len(reopened.entries) == 1

    with pytest.raises(ZecretDecryptError):
        DiaryFile.unlock(diary_path, PASSWORD)


async def test_the_change_is_said_over_the_screen_it_returns_to(diary_path, notifications):
    """Nothing on the settings screen shows that it worked, so it is said
    -- and a notification outlives the screen that raised it."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_dialog(pilot)
        await submit_change(pilot, PASSWORD, NEW_PASSWORD, NEW_PASSWORD)
        assert CHANGED in notifications(app)


async def test_change_updates_the_session_key(diary_path):
    """A stale app.key would corrupt the next save."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        old_key = app.key
        await open_dialog(pilot)
        await submit_change(pilot, PASSWORD, NEW_PASSWORD, NEW_PASSWORD)
        assert app.key != old_key
        assert app.diary.verify_password(NEW_PASSWORD, app.key)


async def test_the_session_still_works_after_a_change(diary_path):
    """Adding an entry after re-keying must stay readable under the new
    password -- this is the path a stale key would break."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_dialog(pilot)
        await submit_change(pilot, PASSWORD, NEW_PASSWORD, NEW_PASSWORD)

        app.diary.add_entry(Entry.new(TODAY, "Written after the change"))
        app.diary.save(app.key)

    reopened, _ = DiaryFile.unlock(diary_path, NEW_PASSWORD)
    assert {entry.body for entry in reopened.entries.values()} == {
        "A body",
        "Written after the change",
    }


async def test_change_uses_a_fresh_salt(diary_path):
    before = json.loads(diary_path.read_bytes())["kdf"]["salt"]
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_dialog(pilot)
        await submit_change(pilot, PASSWORD, NEW_PASSWORD, NEW_PASSWORD)
    assert json.loads(diary_path.read_bytes())["kdf"]["salt"] != before


# --- refusals --------------------------------------------------------------


async def test_wrong_current_password_is_refused(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_dialog(pilot)
        await submit_change(pilot, "not my password", NEW_PASSWORD, NEW_PASSWORD)
        assert isinstance(app.screen, PasswordScreen), "the dialog stays open"
        assert error_of(app.screen) == WRONG_CURRENT

    # Unchanged: the old password still works, the new one does not.
    DiaryFile.unlock(diary_path, PASSWORD)
    with pytest.raises(ZecretDecryptError):
        DiaryFile.unlock(diary_path, NEW_PASSWORD)


async def test_mismatched_new_passwords_are_refused(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_dialog(pilot)
        await submit_change(pilot, PASSWORD, NEW_PASSWORD, "something else")
        assert error_of(app.screen) == MISMATCH
    DiaryFile.unlock(diary_path, PASSWORD)


async def test_empty_new_password_is_refused(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_dialog(pilot)
        await submit_change(pilot, PASSWORD, "", "")
        assert error_of(app.screen) == EMPTY_NEW
    DiaryFile.unlock(diary_path, PASSWORD)


async def test_wrong_current_password_clears_the_fields(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_dialog(pilot)
        await submit_change(pilot, "not my password", NEW_PASSWORD, NEW_PASSWORD)
        assert all(widget.value == "" for widget in app.screen.query(Input))


@pytest.mark.parametrize(
    "new,confirm",
    [("", ""), ("a new password", "a different one")],
    ids=["empty", "mismatch"],
)
async def test_a_refused_change_leaves_no_password_in_the_fields(diary_path, new, confirm):
    """Every failure path clears, so an unattended terminal never holds a
    typed password in a widget."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_dialog(pilot)
        await submit_change(pilot, PASSWORD, new, confirm)

        assert isinstance(app.screen, PasswordScreen), "must not leave"
        assert error_of(app.screen)
        assert [field.value for field in app.screen.query(Input)] == ["", "", ""]


# --- failure part-way through ----------------------------------------------


async def test_a_failed_save_leaves_the_diary_openable(diary_path, monkeypatch):
    """The dangerous case: if the re-key is not rolled back, the next save
    writes the new KDF params over ciphertext still under the old key, and
    neither password opens the file again."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_dialog(pilot)

        def boom(*_args, **_kwargs):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(type(app.diary), "save", boom)
        await submit_change(pilot, PASSWORD, NEW_PASSWORD, NEW_PASSWORD)
        assert isinstance(app.screen, PasswordScreen)
        assert "No space left" in error_of(app.screen)

        # Params rolled back, session key untouched.
        monkeypatch.undo()
        assert app.diary.verify_password(PASSWORD, app.key)

        # A later save must still produce a file the old password opens.
        app.diary.add_entry(Entry.new(TODAY, "After the failure"))
        app.diary.save(app.key)

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert len(reopened.entries) == 2


# --- the note about a short password ---------------------------------------


def advice_line(app: ZecretApp) -> Label:
    return app.screen.query_one("#password-error", Label)


async def test_a_short_new_password_is_mentioned_as_it_is_typed(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_dialog(pilot)
        app.screen.query_one("#new", Input).value = "hunter2"
        await pilot.pause()

        assert str(advice_line(app).content) == LENGTH_ADVICE


async def test_nothing_is_said_about_the_current_password(diary_path):
    """It is being recalled, not chosen, and the confirmation is a copy of
    a field that has already been spoken about."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_dialog(pilot)
        app.screen.query_one("#current", Input).value = "abc"
        await pilot.pause()

        assert str(advice_line(app).content) == ""


async def test_a_short_new_password_is_still_accepted(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_dialog(pilot)
        await submit_change(pilot, PASSWORD, "abc", "abc")
        await pilot.pause()

        assert not isinstance(app.screen, PasswordScreen), "the change went through"
        assert DiaryFile.unlock(diary_path, "abc")[0] is not None


async def test_a_refusal_takes_the_line_back_from_the_note(diary_path):
    """Emptying the fields after a refusal is a change like any other and
    reaches the advice handler a moment after the error was written."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_dialog(pilot)
        await submit_change(pilot, PASSWORD, "abc", "xyz")
        await pilot.pause()

        assert str(advice_line(app).content) == MISMATCH
        assert not advice_line(app).has_class("-advice")


async def test_the_note_fits_the_row_it_is_written_on(diary_path):
    """The error row is one fixed row, which is what protects the dialog's
    height -- so an over-long note is not wrapped onto a second line but
    quietly cut off at the edge of the card, and the reader loses the end
    of the sentence with nothing to say it happened. Measured against the
    row's real width rather than against a number written down here."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await unlock(pilot)
        await open_dialog(pilot)
        app.screen.query_one("#new", Input).value = "hunter2"
        await pilot.pause()

        line = advice_line(app)
        assert line.size.height == 1, "the error row is supposed to be a single row"
        assert cell_len(LENGTH_ADVICE) <= line.content_region.width, (
            "the note is wider than the row it is written on and will be cut off"
        )


async def test_the_note_fits_the_narrower_card_too(diary_path):
    """The create screen writes the same sentence into a 62-column card
    rather than the dialog's 70, so that is the width it has to fit."""
    app = ZecretApp(diary_path=tmp_missing_diary(diary_path))
    async with app.run_test(size=(80, 24)) as pilot:
        app.screen.query_one("#password", Input).value = "hunter2"
        await pilot.pause()

        line = app.screen.query_one("#unlock-error", Label)
        assert cell_len(LENGTH_ADVICE) <= line.content_region.width, (
            "the note is wider than the create screen's row and will be cut off"
        )
