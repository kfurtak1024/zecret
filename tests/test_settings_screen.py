"""Tests for SettingsScreen: the master password change.

Required coverage:
    - 's' from the list opens settings.
    - A correct current password + matching new password re-keys the diary:
      the new password opens it and the old one no longer does.
    - app.key is updated, so the session keeps working afterwards.
    - A wrong current password is refused and changes nothing.
    - An empty or mismatched new password is refused.
    - A save that fails does not leave the diary half re-keyed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from textual.widgets import Input, Label

from zecret.app import ZecretApp
from zecret.crypto import ZecretDecryptError
from zecret.models import Entry
from zecret.screens.entry_list import EntryListScreen
from zecret.screens.settings import EMPTY_NEW, MISMATCH, WRONG_CURRENT, SettingsScreen
from zecret.screens.unlock import UnlockScreen
from zecret.storage import DiaryFile

PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "an entirely different passphrase"


@pytest.fixture(autouse=True)
def instant_failure_delay(monkeypatch):
    monkeypatch.setattr(UnlockScreen, "FAILED_ATTEMPT_DELAY", 0.0)


@pytest.fixture
def diary_path(tmp_path: Path) -> Path:
    path = tmp_path / "diary.enc"
    diary, key = DiaryFile.create_new(path, PASSWORD)
    diary.add_entry(Entry.new("A title", "A body"))
    diary.save(key)
    return path


async def unlock(pilot) -> None:
    pilot.app.screen.query_one("#password", Input).value = PASSWORD
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()


async def open_settings(pilot) -> None:
    await pilot.press("s")
    await pilot.pause()


async def submit_change(pilot, current: str, new: str, confirm: str) -> None:
    screen = pilot.app.screen
    screen.query_one("#current", Input).value = current
    screen.query_one("#new", Input).value = new
    screen.query_one("#confirm", Input).value = confirm
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()


def error_of(screen) -> str:
    return str(screen.query_one("#settings-error", Label).content)


# --- opening ---------------------------------------------------------------


async def test_s_opens_settings(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        assert isinstance(app.screen, SettingsScreen)


async def test_escape_returns_to_the_list(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen)


# --- a successful change ---------------------------------------------------


async def test_change_rekeys_the_diary(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        await submit_change(pilot, PASSWORD, NEW_PASSWORD, NEW_PASSWORD)
        assert isinstance(app.screen, EntryListScreen), "should return to the list"

    reopened, _ = DiaryFile.unlock(diary_path, NEW_PASSWORD)
    assert len(reopened.entries) == 1

    with pytest.raises(ZecretDecryptError):
        DiaryFile.unlock(diary_path, PASSWORD)


async def test_change_updates_the_session_key(diary_path):
    """A stale app.key would corrupt the next save."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        old_key = app.key
        await open_settings(pilot)
        await submit_change(pilot, PASSWORD, NEW_PASSWORD, NEW_PASSWORD)
        assert app.key != old_key
        assert app.diary.verify_password(NEW_PASSWORD, app.key)


async def test_the_session_still_works_after_a_change(diary_path):
    """Adding an entry after re-keying must stay readable under the new
    password -- this is the path a stale key would break."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        await submit_change(pilot, PASSWORD, NEW_PASSWORD, NEW_PASSWORD)

        app.diary.add_entry(Entry.new("Written after", "the change"))
        app.diary.save(app.key)

    reopened, _ = DiaryFile.unlock(diary_path, NEW_PASSWORD)
    assert {entry.title for entry in reopened.entries.values()} == {"A title", "Written after"}


async def test_change_uses_a_fresh_salt(diary_path):
    before = json.loads(diary_path.read_bytes())["kdf"]["salt"]
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        await submit_change(pilot, PASSWORD, NEW_PASSWORD, NEW_PASSWORD)
    assert json.loads(diary_path.read_bytes())["kdf"]["salt"] != before


# --- refusals --------------------------------------------------------------


async def test_wrong_current_password_is_refused(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        await submit_change(pilot, "not my password", NEW_PASSWORD, NEW_PASSWORD)
        assert isinstance(app.screen, SettingsScreen)
        assert error_of(app.screen) == WRONG_CURRENT

    # Unchanged: the old password still works, the new one does not.
    DiaryFile.unlock(diary_path, PASSWORD)
    with pytest.raises(ZecretDecryptError):
        DiaryFile.unlock(diary_path, NEW_PASSWORD)


async def test_mismatched_new_passwords_are_refused(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        await submit_change(pilot, PASSWORD, NEW_PASSWORD, "something else")
        assert error_of(app.screen) == MISMATCH
    DiaryFile.unlock(diary_path, PASSWORD)


async def test_empty_new_password_is_refused(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        await submit_change(pilot, PASSWORD, "", "")
        assert error_of(app.screen) == EMPTY_NEW
    DiaryFile.unlock(diary_path, PASSWORD)


async def test_wrong_current_password_clears_the_fields(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        await submit_change(pilot, "not my password", NEW_PASSWORD, NEW_PASSWORD)
        assert all(widget.value == "" for widget in app.screen.query(Input))


# --- failure part-way through ----------------------------------------------


async def test_a_failed_save_leaves_the_diary_openable(diary_path, monkeypatch):
    """The dangerous case: if the re-key is not rolled back, the next save
    writes the new KDF params over ciphertext still under the old key, and
    neither password opens the file again."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)

        def boom(*_args, **_kwargs):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(type(app.diary), "save", boom)
        await submit_change(pilot, PASSWORD, NEW_PASSWORD, NEW_PASSWORD)
        assert isinstance(app.screen, SettingsScreen)
        assert "No space left" in error_of(app.screen)

        # Params rolled back, session key untouched.
        monkeypatch.undo()
        assert app.diary.verify_password(PASSWORD, app.key)

        # A later save must still produce a file the old password opens.
        app.diary.add_entry(Entry.new("After the failure", "body"))
        app.diary.save(app.key)

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert len(reopened.entries) == 2
