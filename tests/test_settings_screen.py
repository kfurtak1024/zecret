"""Tests for SettingsScreen: appearance, locking, and the password button.

Required coverage:
    - 's' from the list opens settings.
    - The theme picker starts on the theme in use, applies a choice
      immediately, and saves it so the next launch starts there.
    - A theme that cannot be saved still applies to this session.
    - The lock picker starts on the saved wait, falls back to the default
      for a wait it cannot show, applies and saves a choice, and offers
      "Never"; a wait that cannot be saved still applies.
    - The master password section is a button onto a dialog, and this
      screen holds no password fields and no warning of its own. What the
      dialog does is covered by tests/test_password_screen.py.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from textual.containers import VerticalScroll
from textual.widgets import Button, Input, Label, Select

from zecret.app import ZecretApp
from zecret.config import DEFAULT_LOCK_AFTER_MINUTES, DEFAULT_THEME, Config
from zecret.models import Entry
from zecret.screens.entry_list import EntryListScreen
from zecret.screens.settings import (
    LOCK_NOT_SAVED,
    LOCK_TIMEOUTS,
    THEME_NOT_SAVED,
    THEMES,
    SettingsScreen,
)
from zecret.screens.unlock import UnlockScreen
from zecret.storage import DiaryFile

PASSWORD = "correct horse battery staple"

TODAY = dt.date.today()
YESTERDAY = TODAY - dt.timedelta(days=1)
NEW_PASSWORD = "an entirely different passphrase"


# Argon2 at test cost, and no pause after a failed unlock: this suite
# opens diaries constantly (see tests/conftest.py).
pytestmark = pytest.mark.usefixtures("cheap_kdf")


@pytest.fixture(autouse=True)
def instant_failure_delay(monkeypatch):
    monkeypatch.setattr(UnlockScreen, "FAILED_ATTEMPT_DELAY", 0.0)


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


async def open_settings(pilot) -> None:
    await pilot.press("s")
    await pilot.pause()


async def submit_change(pilot, current: str, new: str, confirm: str) -> None:
    screen = pilot.app.screen
    screen.query_one("#current", Input).value = current
    screen.query_one("#new", Input).value = new
    confirm_field = screen.query_one("#confirm", Input)
    confirm_field.value = confirm
    # Focused explicitly: the screen opens on the theme picker, and Enter
    # submits the form only from inside one of its fields -- which is where
    # someone who just typed a password is.
    confirm_field.focus()
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()


def error_of(screen) -> str:
    return str(screen.query_one("#settings-error", Label).content)


def theme_select(app: ZecretApp) -> Select:
    return app.screen.query_one("#theme", Select)


# --- appearance ------------------------------------------------------------


async def test_the_picker_starts_on_the_theme_in_use(diary_path, isolated_config):
    Config(path=isolated_config, theme="nord").save()
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        assert theme_select(app).value == "nord"
        assert app.theme == "nord"


async def test_every_offered_theme_is_one_textual_knows(diary_path):
    """A name Textual does not have would raise the moment it is chosen."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        for _label, theme in THEMES:
            assert theme in app.available_themes


async def test_choosing_a_theme_applies_it_immediately(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        theme_select(app).value = "gruvbox"
        await pilot.pause()
        assert app.theme == "gruvbox"


async def test_choosing_a_theme_saves_it(diary_path, isolated_config):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        theme_select(app).value = "dracula"
        await pilot.pause()
    assert Config.load(isolated_config).theme == "dracula"


async def test_a_chosen_theme_survives_a_restart(diary_path, isolated_config):
    """The whole point of saving it: the next launch starts there, lock
    screen included."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        theme_select(app).value = "nord"
        await pilot.pause()

    relaunched = ZecretApp(diary_path=diary_path)
    async with relaunched.run_test() as pilot:
        await pilot.pause()
        assert relaunched.theme == "nord", "the lock screen is themed too"


async def test_choosing_by_keyboard_applies_the_theme(diary_path):
    """The dropdown is the intended way in, not just setting .value."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        theme_select(app).focus()
        await pilot.pause()
        await pilot.press("enter")  # open the list
        await pilot.pause()
        await pilot.press("down", "enter")  # move one and take it
        await pilot.pause()
        assert app.theme == THEMES[1][1]


async def test_escape_closes_the_open_dropdown_rather_than_the_screen(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        theme_select(app).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert theme_select(app).expanded is True

        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen), "the screen must stay"
        assert theme_select(app).expanded is False

        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen), "now it leaves"


async def test_a_theme_that_cannot_be_saved_still_applies(diary_path, monkeypatch):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)

        def boom(*_args, **_kwargs):
            raise OSError(13, "Permission denied")

        monkeypatch.setattr(Config, "save", boom)
        notifications = []
        monkeypatch.setattr(
            type(app), "notify", lambda self, message, **kw: notifications.append(message)
        )

        theme_select(app).value = "nord"
        await pilot.pause()
        assert app.theme == "nord", "the session keeps the theme"
        assert THEME_NOT_SAVED in notifications


async def test_an_unknown_saved_theme_falls_back_to_the_default(diary_path, isolated_config):
    """A theme name from a future Zecret, or a typo, must not stop the app
    from starting."""
    Config(path=isolated_config, theme="no-such-theme").save()
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == DEFAULT_THEME


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


async def test_the_password_section_is_a_button_and_not_a_form(diary_path):
    """The fields moved into a dialog of their own -- see
    tests/test_password_screen.py. What is left here is the way to it, and
    this screen holds no password fields at all."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        assert app.screen.query_one("#change-password", Button)
        assert not app.screen.query(Input), "no password fields on the settings screen"
        assert not app.screen.query(".caution"), "the warning belongs to the dialog"


# --- locking ---------------------------------------------------------------


async def test_the_lock_picker_starts_on_the_saved_wait(diary_path, isolated_config):
    isolated_config.write_text(json.dumps({"lock_after_minutes": 30}))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        assert app.screen.query_one("#lock-after", Select).value == 30


async def test_a_wait_the_picker_cannot_show_falls_back_to_the_default(diary_path, isolated_config):
    """The file may have been hand-edited to a number this build does not
    offer. Select refuses a value that is not one of its options, so the
    screen must not hand it one."""
    isolated_config.write_text(json.dumps({"lock_after_minutes": 7}))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        assert app.screen.query_one("#lock-after", Select).value == DEFAULT_LOCK_AFTER_MINUTES


async def test_choosing_a_wait_applies_and_is_remembered(diary_path, isolated_config):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        app.screen.query_one("#lock-after", Select).value = 5
        await pilot.pause()
        assert app.config.lock_after_minutes == 5

    assert json.loads(isolated_config.read_text())["lock_after_minutes"] == 5


async def test_never_is_offered_and_turns_locking_off(diary_path, isolated_config):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        app.screen.query_one("#lock-after", Select).value = 0
        await pilot.pause()
        assert app.config.lock_after_minutes == 0

    assert ("Never", 0) in LOCK_TIMEOUTS


async def test_a_wait_that_cannot_be_saved_still_applies(diary_path, monkeypatch):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_settings(pilot)

        def boom(*_args, **_kwargs):
            raise OSError(13, "Permission denied")

        monkeypatch.setattr(Config, "save", boom)
        notifications = []
        monkeypatch.setattr(
            type(app), "notify", lambda self, message, **kw: notifications.append(message)
        )

        app.screen.query_one("#lock-after", Select).value = 30
        await pilot.pause()

        assert app.config.lock_after_minutes == 30, "the session keeps the setting"
        assert LOCK_NOT_SAVED in notifications


async def test_settings_opens_at_the_top_of_the_form(diary_path):
    """The screen scrolls. Opening it focused on the password fields would
    put it straight past appearance and locking, which is what most visits
    are for."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(80, 26)) as pilot:
        await unlock(pilot)
        await open_settings(pilot)
        assert app.screen.focused is theme_select(app)
        assert app.screen.query_one("#settings-box", VerticalScroll).scroll_offset.y == 0
