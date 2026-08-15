"""Tests for HelpScreen: one popup of keys.

Required coverage:
    - '?' from the entry list opens help; escape and '?' close it.
    - It is a modal: the diary stays behind it rather than being replaced.
    - Every key the app binds anywhere appears on the page, with the same
      wording the footer uses for the ones that reach it. This is the point
      of generating the page from BINDINGS: a new binding cannot be added
      without it showing up here, so the help can never quietly go stale.
      Keys kept out of the footer for want of width are listed too -- the
      navigation keys are only ever found here.
    - The logo and version are shown, and the logo gives way rather than
      being drawn half-cut on a narrow terminal.
    - '?' typed into a text field stays a '?'.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from textual.widgets import Input, Label, Static, TextArea

from zecret import __version__
from zecret.app import ZecretApp
from zecret.models import Entry
from zecret.screens.editor import EditorScreen
from zecret.screens.entry_list import EntryListScreen
from zecret.screens.help import (
    LOGO,
    MIN_LOGO_WIDTH,
    NOTES,
    SECTIONS,
    TAGLINE,
    HelpScreen,
    documented_bindings,
)
from zecret.screens.search import SearchScreen
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


async def open_help(pilot) -> None:
    await pilot.press("question_mark")
    await pilot.pause()
    await pilot.pause()


def page_lines(app: ZecretApp) -> list[str]:
    return [str(label.content) for label in app.screen.query(Label)]


# --- opening and closing ---------------------------------------------------


async def test_question_mark_opens_help(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_help(pilot)
        assert isinstance(app.screen, HelpScreen)


async def test_escape_closes_help(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_help(pilot)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen)


async def test_question_mark_closes_help_too(diary_path):
    """Whatever opened it should shut it."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_help(pilot)
        await pilot.press("question_mark")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen)


async def test_help_is_a_modal_over_the_diary(diary_path):
    """A popup, not a replacement: the entry list stays mounted behind it,
    which is what makes escape feel like closing rather than navigating."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_help(pilot)
        assert isinstance(app.screen, HelpScreen)
        assert isinstance(app.screen_stack[-2], EntryListScreen)


async def test_help_leaves_the_diary_untouched(diary_path):
    before = diary_path.read_bytes()
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_help(pilot)
    assert diary_path.read_bytes() == before


# --- logo and version ------------------------------------------------------


async def test_the_logo_is_shown(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(100, 40)) as pilot:
        await unlock(pilot)
        await open_help(pilot)
        logo = app.screen.query_one("#help-logo", Static)
        assert logo.display is True
        assert str(logo.visual).splitlines() == LOGO.splitlines()


async def test_the_version_is_shown(diary_path):
    """Read off the installed distribution, so it cannot drift from
    pyproject.toml."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(100, 40)) as pilot:
        await unlock(pilot)
        await open_help(pilot)
        assert f"v{__version__}" in TAGLINE
        assert TAGLINE in page_lines(app)


async def test_the_version_is_a_real_version(diary_path):
    assert __version__ != "0.0.0+unknown", "the package should be installed under test"


async def test_a_narrow_terminal_drops_the_logo_rather_than_cutting_it(diary_path):
    """Half a block letter reads as breakage; the keys are the point."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(MIN_LOGO_WIDTH - 10, 40)) as pilot:
        await unlock(pilot)
        await open_help(pilot)
        assert app.screen.query_one("#help-logo", Static).display is False
        assert "n   Today" in " ".join(line.strip() for line in page_lines(app))


async def test_widening_the_terminal_brings_the_logo_back(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(MIN_LOGO_WIDTH - 10, 40)) as pilot:
        await unlock(pilot)
        await open_help(pilot)
        assert app.screen.query_one("#help-logo", Static).display is False

        await pilot.resize_terminal(MIN_LOGO_WIDTH + 10, 40)
        await pilot.pause()
        assert app.screen.query_one("#help-logo", Static).display is True


# --- what is on the page ---------------------------------------------------


async def test_every_advertised_key_of_every_screen_is_listed(diary_path):
    """The anti-drift check: add a binding anywhere, and it must appear
    here, worded and displayed exactly as the footer words it."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_help(pilot)
        lines = page_lines(app)

        every_binding = [EntryListScreen.BINDINGS] + [bindings for _title, bindings in SECTIONS]
        for bindings in every_binding:
            for binding in documented_bindings(bindings):
                # Rows are right-aligned within their section, so compare
                # the stripped line: "  ^s   Save" -> "^s   Save".
                expected = f"{app.get_key_display(binding)}   {binding.description}"
                assert any(line.strip() == expected for line in lines), (
                    f"missing from the help page: {expected!r}"
                )


async def test_the_page_names_each_section(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_help(pilot)
        lines = page_lines(app)
        for title, _bindings in SECTIONS:
            assert title in lines


async def test_the_page_carries_the_notes_keys_cannot_express(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_help(pilot)
        page = " ".join(page_lines(app))
        for note in NOTES:
            assert note in page
        assert "No password recovery" in page, "the one thing that cannot be undone"


async def test_keys_kept_out_of_the_footer_are_still_listed(diary_path):
    """This page documents the whole keymap, not the footer's share of it.

    Navigation is the case that matters. None of it fits in eighty columns,
    so none of it is in the bar, and this popup is the only place in the
    app where a reader is ever told that j, g, G or the page keys exist.
    """
    hidden = [
        binding for binding in documented_bindings(EntryListScreen.BINDINGS) if not binding.show
    ]
    assert hidden, "nothing is being kept out of the footer, so this proves nothing"

    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_help(pilot)
        lines = page_lines(app)
        for binding in hidden:
            assert any(line.endswith(binding.description) for line in lines), (
                f"{binding.key} is bound but documented nowhere"
            )


# --- '?' elsewhere ---------------------------------------------------------


async def test_question_mark_in_the_editor_is_typed_not_a_shortcut(diary_path):
    """Why the binding lives on the entry list and not on the app."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen), "help must not open mid-sentence"
        assert "?" in app.screen.query_one("#body", TextArea).text


async def test_question_mark_in_search_is_typed_not_a_shortcut(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await pilot.press("slash")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, SearchScreen)
        assert app.screen.query_one("#query", Input).value == "?"
