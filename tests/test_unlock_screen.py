"""Tests for the unlock/create-diary flow (ZecretApp + UnlockScreen).

Smoke tests over the real screens driven by Textual's Pilot, per CLAUDE.md:
full UI coverage is lower priority than crypto/storage correctness, so these
cover routing and the security-relevant behavior rather than appearance.

Required coverage:
    - A missing diary presents the create flow; an existing one presents
      the unlock flow.
    - Creating a diary writes the file and leaves app.diary/app.key set.
    - Mismatched or empty passwords are refused without creating a file.
    - The correct password unlocks and exposes the decrypted entries.
    - A wrong password shows an inline error, leaves app.diary as None, and
      does not leak whether the file was wrong-password vs. corrupted.
    - The typed password is cleared from the widget after any attempt.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from textual.widgets import Input, Label

from zecret.app import ZecretApp
from zecret.models import Entry
from zecret.screens.unlock import UNLOCK_FAILED, UnlockScreen
from zecret.storage import DiaryFile

PASSWORD = "correct horse battery staple"

TODAY = dt.date.today()
WRONG_PASSWORD = "Correct horse battery staple"


@pytest.fixture(autouse=True)
def instant_failure_delay(monkeypatch):
    """The 400ms anti-brute-force pause is real behavior, but waiting for it
    in every test is not worth the wall time."""
    monkeypatch.setattr(UnlockScreen, "FAILED_ATTEMPT_DELAY", 0.0)


@pytest.fixture
def diary_path(tmp_path: Path) -> Path:
    return tmp_path / "diary.enc"


def existing_diary(path: Path, *entries: Entry) -> None:
    diary, key = DiaryFile.create_new(path, PASSWORD)
    for entry in entries:
        diary.add_entry(entry)
    diary.save(key)


def error_text(app: ZecretApp) -> str:
    return str(app.screen.query_one("#unlock-error", Label).content)


async def submit(pilot, password: str, confirm: str | None = None) -> None:
    """Type into the password field (and confirm, if present) and submit."""
    pilot.app.screen.query_one("#password", Input).value = password
    if confirm is not None:
        pilot.app.screen.query_one("#confirm", Input).value = confirm
    await pilot.press("enter")
    await pilot.pause()


# --- which flow is presented -----------------------------------------------


async def test_missing_diary_presents_the_create_flow(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, UnlockScreen)
        assert app.screen.creating is True
        assert app.screen.query("#confirm"), "create flow needs a confirm field"


async def test_existing_diary_presents_the_unlock_flow(diary_path):
    existing_diary(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.creating is False
        assert not app.screen.query("#confirm"), "unlock flow must not confirm"


async def test_password_input_is_masked(diary_path):
    existing_diary(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.query_one("#password", Input).password is True


async def test_app_starts_locked(diary_path):
    existing_diary(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.diary is None
        assert app.key is None


async def test_ctrl_q_quits_from_the_lock_screen(diary_path):
    """Someone who cannot get in needs the advertised way out to work."""
    existing_diary(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await pilot.press("ctrl+q")
        await pilot.pause()
        assert app._exit is True


# --- creating a diary ------------------------------------------------------


async def test_create_writes_the_file_and_unlocks_the_session(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await submit(pilot, PASSWORD, confirm=PASSWORD)
        assert diary_path.exists()
        assert app.diary is not None
        assert app.key is not None
        assert app.diary.entries == {}


async def test_created_diary_opens_with_the_chosen_password(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await submit(pilot, PASSWORD, confirm=PASSWORD)

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entries == {}


async def test_create_refuses_mismatched_passwords(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await submit(pilot, PASSWORD, confirm="something else")
        assert not diary_path.exists(), "no diary may be written on mismatch"
        assert app.diary is None
        assert "match" in error_text(app).lower()


async def test_create_refuses_an_empty_password(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await submit(pilot, "", confirm="")
        assert not diary_path.exists()
        assert app.diary is None
        assert error_text(app)


async def test_create_recovers_after_a_mismatch(diary_path):
    """A rejected attempt must leave the screen usable."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await submit(pilot, PASSWORD, confirm="mismatch")
        await submit(pilot, PASSWORD, confirm=PASSWORD)
        assert diary_path.exists()
        assert app.diary is not None


# --- unlocking an existing diary -------------------------------------------


async def test_correct_password_unlocks_and_exposes_entries(diary_path):
    entry = Entry.new(TODAY, "A body")
    existing_diary(diary_path, entry)

    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await submit(pilot, PASSWORD)
        assert app.diary is not None
        assert app.key is not None
        assert app.diary.entries == {entry.date: entry}


async def test_wrong_password_shows_an_error_and_stays_locked(diary_path):
    existing_diary(diary_path, Entry.new(TODAY, "A body"))

    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await submit(pilot, WRONG_PASSWORD)
        assert app.diary is None, "a failed unlock must not open the diary"
        assert app.key is None
        assert error_text(app) == UNLOCK_FAILED


async def test_wrong_password_never_falls_back_to_an_empty_diary(diary_path):
    """CLAUDE.md requirement 7 at the UI layer: failure is an error, never
    a diary that merely looks empty."""
    existing_diary(diary_path)  # empty diary: the case the verifier covers
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await submit(pilot, WRONG_PASSWORD)
        assert app.diary is None
        assert error_text(app) == UNLOCK_FAILED


async def test_corrupted_file_is_indistinguishable_from_a_wrong_password(diary_path):
    """The message must not reveal that the file itself is damaged."""
    existing_diary(diary_path)
    diary_path.write_text("this is not a diary")

    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await submit(pilot, PASSWORD)
        assert app.diary is None
        assert error_text(app) == UNLOCK_FAILED


async def test_retry_after_a_wrong_password_succeeds(diary_path):
    existing_diary(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        # Held directly: the screen is torn down once the retry succeeds.
        error_label = app.screen.query_one("#unlock-error", Label)
        await submit(pilot, WRONG_PASSWORD)
        assert str(error_label.content) == UNLOCK_FAILED
        await submit(pilot, PASSWORD)
        assert app.diary is not None
        assert str(error_label.content) == "", "stale error left on screen"


# --- handling of the typed password ----------------------------------------


async def test_password_is_cleared_from_the_widget_after_success(diary_path):
    existing_diary(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        # Hold the widget directly: on success the screen is dismissed and
        # torn down, so it can no longer be queried by id.
        password_input = app.screen.query_one("#password", Input)
        await submit(pilot, PASSWORD)
        assert password_input.value == ""


async def test_password_is_cleared_from_the_widget_after_failure(diary_path):
    existing_diary(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await submit(pilot, WRONG_PASSWORD)
        assert app.screen.query_one("#password", Input).value == ""


async def test_inputs_are_re_enabled_after_a_failed_attempt(diary_path):
    """They are disabled during the anti-brute-force pause; if they stayed
    disabled the user could never retry."""
    existing_diary(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await submit(pilot, WRONG_PASSWORD)
        assert all(not widget.disabled for widget in app.screen.query(Input))
