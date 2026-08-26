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
    - A long section is laid out in two columns side by side, and stacks
      back into one where the terminal is too narrow to pair them.
    - The whole popup fits the height tools/screenshots.py shoots it at, so
      a layout that grows is caught here rather than by someone noticing a
      cropped picture months later.
    - The text-editing keys are not on it. The page documents what Zecret
      does with a diary; ctrl+home, ctrl+end and ctrl+a mean in the editor
      exactly what they mean in every other editor, and listing them would
      raise the question of why ctrl+z and the arrow keys are absent.
    - '?' typed into a text field stays a '?'.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from textual.containers import VerticalScroll
from textual.widget import Widget
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

#: The height tools/screenshots.py shoots the help popup at. Written out
#: rather than imported: tools/ is not in the sdist, and these tests have to
#: run from one. It guards the direction that actually goes wrong -- a page
#: that grows past its picture -- so raise this and ROWS["help"] together if
#: the help ever genuinely needs more room.
SHOT_ROWS = 34


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


# --- columns ---------------------------------------------------------------


def columns(app: ZecretApp) -> list[Widget]:
    """The column containers of the first multi-column section."""
    return list(app.screen.query(".help-columns").first().query(".help-column"))


async def test_a_long_section_is_laid_out_in_two_columns(diary_path):
    """Eighteen keys in one column is a page you scroll; the same eighteen
    in two is most of a page you do not. Side by side means same top, and
    different left -- geometry rather than the style that produced it."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(100, 40)) as pilot:
        await unlock(pilot)
        await open_help(pilot)
        left, right = columns(app)
        assert left.region.y == right.region.y, "columns should sit side by side"
        assert left.region.x < right.region.x
        assert len(left.query(".help-key")) == len(right.query(".help-key")), (
            "eighteen keys should split down the middle"
        )


async def test_a_narrow_terminal_stacks_the_columns(diary_path):
    """Two columns squeezed until the descriptions truncate tell the reader
    less than one column they have to scroll."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(40, 40)) as pilot:
        await unlock(pilot)
        await open_help(pilot)
        left, right = columns(app)
        assert left.region.y < right.region.y, "columns should stack, not squeeze"


async def test_widening_the_terminal_pairs_the_columns_again(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(40, 40)) as pilot:
        await unlock(pilot)
        await open_help(pilot)
        assert columns(app)[0].region.y < columns(app)[1].region.y

        await pilot.resize_terminal(100, 40)
        await pilot.pause()
        assert columns(app)[0].region.y == columns(app)[1].region.y


async def test_the_whole_popup_fits_the_height_the_screenshots_use(diary_path):
    """tools/screenshots.py shoots the help at SHOT_ROWS, and nothing fails
    when a picture is cropped -- so the check lives here instead. Raise both
    together if the page genuinely needs to grow."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(80, SHOT_ROWS)) as pilot:
        await unlock(pilot)
        await open_help(pilot)
        box = app.screen.query_one("#help-box", VerticalScroll)
        assert box.virtual_size.height <= box.size.height, (
            f"the help no longer fits {SHOT_ROWS} rows; screenshots will be cropped"
        )


# --- what is on the page ---------------------------------------------------


async def test_every_advertised_key_of_every_screen_is_listed(diary_path):
    """The anti-drift check: add a binding anywhere, and it must appear
    here, worded and displayed exactly as the footer words it."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_help(pilot)
        lines = page_lines(app)

        # SECTIONS holds *groups* of binding lists, one per screen the
        # section merges, so it has to be flattened a level. Passing the
        # nested list straight to documented_bindings() returns nothing --
        # a list is not a Binding -- and this check silently covered only
        # the entry list.
        every_binding = [EntryListScreen.BINDINGS] + [
            bindings for _title, groups in SECTIONS for bindings in groups
        ]
        assert sum(len(documented_bindings(b)) for b in every_binding) > len(
            documented_bindings(EntryListScreen.BINDINGS)
        ), "this check must reach past the entry list"

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


async def test_the_text_editing_keys_are_not_on_the_page(diary_path):
    """They are the widget's, not the screen's, and that is the whole
    reason they are bound there: this page lists what Zecret does with a
    diary. ctrl+home and ctrl+a do here what they do in every other editor,
    and putting them up would invite the question of where ctrl+z, ctrl+k
    and the arrow keys went -- which are just as real and just as absent.
    """
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(100, 40)) as pilot:
        await unlock(pilot)
        await open_help(pilot)
        page = " ".join(page_lines(app))
        for key in ("^home", "^end", "^a"):
            assert key not in page, f"{key} is the text area's key, not the diary's"


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
