"""Tests for the app's chrome: the title bar and what is not in it.

Required coverage:
    - The header shows "Zecret — <where you are>", following the screen.
    - The header cannot be expanded by clicking it, and carries no icon
      that opens anything.
    - The command palette is off: ctrl+p does nothing and the footer does
      not advertise it.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from textual.widgets import Input

from zecret.app import ZecretApp
from zecret.models import Entry
from zecret.screens.entry_list import EntryListScreen
from zecret.screens.header import DiaryHeader
from zecret.screens.unlock import UnlockScreen
from zecret.storage import DiaryFile

PASSWORD = "correct horse battery staple"
TODAY = dt.date.today()


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
    diary.add_entry(Entry.new(TODAY, "A body"))
    diary.save(key)
    return path


async def unlock(pilot) -> None:
    pilot.app.screen.query_one("#password", Input).value = PASSWORD
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()


def header(app: ZecretApp) -> DiaryHeader:
    return app.screen.query_one(DiaryHeader)


def header_text(app: ZecretApp) -> str:
    return str(header(app).visual)


# --- what the header says --------------------------------------------------


async def test_header_shows_the_app_name_and_the_screen(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert header_text(app) == "Zecret — Locked"


async def test_header_follows_the_screen_you_are_on(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert header_text(app) == "Zecret — 1 entry"
        await pilot.press("slash")
        await pilot.pause()
        await pilot.pause()
        assert header_text(app) == "Zecret — Search"


# --- what the header will not do -------------------------------------------


async def test_clicking_the_header_does_nothing(diary_path):
    """Textual's own header expands to a taller variant on click. This one
    is a title, not a control."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        before = (header(app).size.height, header(app).classes, header_text(app))
        await pilot.click(header(app))
        await pilot.pause()
        assert (header(app).size.height, header(app).classes, header_text(app)) == before
        assert isinstance(app.screen, EntryListScreen), "nothing may open"


async def test_the_header_is_one_line(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert header(app).size.height == 1


async def test_the_header_carries_no_icon(diary_path):
    """The icon Textual docks left is what opened the command palette."""
    from textual.widgets._header import HeaderIcon

    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert not app.screen.query(HeaderIcon)


# --- no command palette ----------------------------------------------------


async def test_the_command_palette_is_disabled(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen)
        assert app.ENABLE_COMMAND_PALETTE is False


async def test_the_footer_does_not_advertise_the_palette(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        described = " ".join(key.description for key in app.screen.query("FooterKey"))
        assert "palette" not in described.lower()


# --- app-level guards ------------------------------------------------------


async def test_reaching_the_diary_before_unlocking_is_a_programming_error(diary_path):
    """Screens rely on app.unlocked being real. A half-open state would be
    a routing bug, so it raises rather than returning None."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        with pytest.raises(RuntimeError):
            _ = app.unlocked
