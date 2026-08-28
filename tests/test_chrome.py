"""Tests for the app's chrome: the title bar and what is not in it.

Required coverage:
    - The header shows "Zecret — <where you are>", following the screen.
    - The header cannot be expanded by clicking it, and carries no icon
      that opens anything.
    - The command palette is off: ctrl+p does nothing and the footer does
      not advertise it.
    - Every key the entry list advertises fits an 80-column terminal, and
      every screen wears the same compact footer.
    - Lock is one of the keys the bar advertises. Being able to find it is
      what the bar is for here, so this is not a styling detail.
    - A modal shows its own key. Without a footer of its own it let the
      entry list's bar show through, advertising eight keys that do
      nothing while a question has focus and none of the one that does.
    - The answers to a question are all one width, and every label fits
      the width it is given -- the buttons are sized in app.tcss rather
      than by their own text, so a longer label would be cut in silence.
    - None of them hangs off the end of the row. The row is aligned right,
      so a couple of cells too many are taken off the *last* button, which
      is where the focus frame's right hand side is drawn -- silently, and
      only on the answer that is focused by default.
    - Taking focus does not resize one. The frame is painted over the
      button's edge rather than carved out of its inside, so the answer
      you are about to press is exactly the size of the two beside it.
    - Text lines up down the left edge of every screen. The gutter in
      app.tcss lines the borders up; what a reader follows is where the
      text starts, and Input and TextArea pad their insides by different
      amounts, so the two do not follow from each other.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from textual.widgets import Button, Footer, Input, Label, ListView, TextArea

from zecret.app import ZecretApp
from zecret.models import Entry
from zecret.screens.entry_list import EntryListScreen
from zecret.screens.header import DiaryHeader
from zecret.screens.help import documented_bindings
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


# --- alignment -------------------------------------------------------------


#: Where text begins on every full-width screen, in columns from the left:
#: the 2-cell gutter, its border, and one cell inside that.
TEXT_COLUMN = 4


async def test_text_starts_at_the_same_column_on_every_screen(diary_path):
    """The search box used to sit one cell right of the results under it.
    Input pads its inside by two cells and TextArea by one, so bordering
    them at the same column is not the same as lining their text up --
    which is the edge a reader's eye actually runs down."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(NARROWEST, 20)) as pilot:
        await unlock(pilot)
        rows = app.screen.query_one("#entries", ListView).children
        assert rows[-1].query_one(Label).region.x == TEXT_COLUMN, "an entry row"

        await pilot.press("slash")
        await pilot.pause()
        app.screen.query_one("#query", Input).value = "A"
        await pilot.pause()
        await pilot.pause()
        assert app.screen.query_one("#query", Input).content_region.x == TEXT_COLUMN, "the query"
        results = app.screen.query_one("#results", ListView).children
        assert results[-1].query_one(Label).region.x == TEXT_COLUMN, "a result row"

        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.query_one("#body", TextArea).content_region.x == TEXT_COLUMN, "the editor"


# --- the key bar -----------------------------------------------------------


#: The narrowest terminal Zecret is expected to be usable in. Eighty is not
#: an arbitrary round number -- it is the width a terminal defaults to.
NARROWEST = 80


def footer_text(app: ZecretApp) -> str:
    """The bottom line of the screen, as rendered."""
    strips = app.screen._compositor.render_strips()
    return "".join(segment.text for segment in strips[-1])


async def test_every_advertised_key_fits_an_eighty_column_terminal(diary_path):
    """The entry list advertises more keys than any other screen, and the
    roomy spelling of Textual's footer needs 102 columns to lay them out.
    At 80 it stopped mid-word -- "? Hel" -- and dropped Quit entirely, which
    is how two keys got added without anyone seeing the bar overflow.
    """
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(NARROWEST, 16)) as pilot:
        await unlock(pilot)
        assert isinstance(app.screen, EntryListScreen)
        bar = footer_text(app)

        # Asked of the app rather than read off the binding: the footer
        # renders a chord the way Textual spells it, so ctrl+l is "^l"
        # there and comparing against the raw key name would look for
        # something the bar never contained.
        advertised = [
            f"{app.get_key_display(binding)} {binding.description}"
            for binding in documented_bindings(EntryListScreen.BINDINGS)
            if binding.show
        ]
        missing = [entry for entry in advertised if entry not in bar]
        assert not missing, (
            f"the footer at {NARROWEST} columns does not fully show: {missing}\ngot: {bar!r}"
        )


async def test_the_key_bar_advertises_lock(diary_path):
    """Hidden, this key was reachable only through '?'. Someone stepping
    away who cannot find it quits instead, or leaves the diary open on the
    screen -- which makes its place in the bar a security decision rather
    than a matter of taste."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(NARROWEST, 16)) as pilot:
        await unlock(pilot)
        assert isinstance(app.screen, EntryListScreen)
        assert "^l Lock" in footer_text(app)


async def test_a_modal_advertises_its_own_key_and_not_the_list_behind_it(diary_path):
    """A ModalScreen renders over the screen it was opened from, so with no
    footer of its own the list's bar stayed on show -- every key on it dead
    while the question had focus, and 'esc Cancel' displayed nowhere
    despite being declared show=True."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(NARROWEST, 20)) as pilot:
        await unlock(pilot)
        for key in ("a", "d"):
            await pilot.press(key)
            await pilot.pause()
            await pilot.pause()
            bar = footer_text(app)
            assert "esc Cancel" in bar, f"{key!r} opened a modal with no key of its own: {bar!r}"
            assert "n Today" not in bar, f"{key!r} left the list's dead keys on show: {bar!r}"
            await pilot.press("escape")
            await pilot.pause()
            await pilot.pause()


async def test_the_password_dialog_advertises_its_own_key(diary_path):
    """The same rule as the two modals above, reached the other way: this
    one opens from a button on the settings screen rather than from a key
    on the list, so it is checked separately rather than assumed."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(NARROWEST, 24)) as pilot:
        await unlock(pilot)
        await pilot.press("s")
        await pilot.pause()
        app.screen.query_one("#change-password", Button).press()
        await pilot.pause()
        await pilot.pause()

        bar = footer_text(app)
        assert "esc Cancel" in bar, f"the dialog showed no key of its own: {bar!r}"
        assert "esc Back" not in bar, f"the settings bar stayed on show: {bar!r}"


# --- the confirmation modal ------------------------------------------------


#: What a button spends on something other than its label: a cell of
#: Textual's line-pad each side, and a cell at each end kept clear for the
#: frame focus paints over them.
BUTTON_CHROME = 2 + 2


async def test_every_answer_is_one_width_and_holds_its_label(diary_path):
    """The buttons are given a width in app.tcss rather than sized to their
    own text, which is what makes three answers to one question read as a
    set. The cost of a fixed width is that a longer label would wrap onto a
    second line the moment focus reached it -- taking the button's height
    with it, and the row's alignment -- so the labels are measured against
    the width they will have when focused, not the wider one they sit at
    the rest of the time."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(NARROWEST, 20)) as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        app.screen.query_one("#body", TextArea).text = "Changed"
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()

        buttons = list(app.screen.query("#confirm-buttons Button"))
        assert len(buttons) == 3, "save, discard and cancel"
        # The region, not the size: `size` is the content box, which the
        # focused button's frame takes two cells out of. What has to match
        # is the space each button occupies in the row.
        widths = {button.region.width for button in buttons}
        assert len(widths) == 1, f"the answers are different widths: {widths}"

        width = widths.pop()
        for button in buttons:
            label = str(button.label)
            assert len(label) + BUTTON_CHROME <= width, (
                f"{label!r} does not fit a {width}-cell button once focus frames it"
            )

        # The one that is focused is the proof: it is carrying the frame
        # now, and it is still the same height as the two beside it.
        heights = {button.region.height for button in buttons}
        assert len(heights) == 1, f"a label wrapped: {heights}"


async def test_taking_focus_does_not_resize_a_button(diary_path):
    """The frame is an outline, painted over the button's own edge, rather
    than a border, which Textual draws inside the widget and takes out of
    the content. With a border the focused answer narrowed by two columns
    as you tabbed onto it -- and a label one cell longer than ours would
    have wrapped instead of shrinking, taking the row's alignment with it.
    """
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(NARROWEST, 20)) as pilot:
        await unlock(pilot)
        await pilot.press("enter")
        await pilot.pause()
        app.screen.query_one("#body", TextArea).text = "Changed"
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()

        buttons = list(app.screen.query("#confirm-buttons Button"))
        assert any(app.screen.focused is button for button in buttons), (
            "one of them must be focused, or this proves nothing"
        )
        # The content box, not the region: the region stayed put even when
        # the frame was eating into it, which is what made this invisible
        # to the width check above.
        insides = {button.content_region.width for button in buttons}
        assert len(insides) == 1, f"focus changed a button's size: {insides}"


async def test_no_answer_hangs_off_the_end_of_its_row(diary_path):
    """The row is right-aligned, so a row of buttons two cells wider than
    the space for it loses those cells from the *last* button -- and the
    two that go missing are the ones the focus frame draws down the right
    hand side. Cancel is the last answer in both questions and the one
    focused by default in the delete one, so it came out framed on three
    sides and open on the fourth. Nothing failed: the layout was fine, the
    button was fine, and two columns were simply not drawn.
    """
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(NARROWEST, 20)) as pilot:
        await unlock(pilot)

        for key, expected in (("d", 2), ("escape", 0)):
            await pilot.press(key)
            await pilot.pause()
            await pilot.pause()
            if not expected:
                continue

            row = app.screen.query_one("#confirm-buttons")
            buttons = list(app.screen.query("#confirm-buttons Button"))
            assert len(buttons) == expected
            for button in buttons:
                assert row.content_region.contains_region(button.region), (
                    f"{str(button.label)!r} is cut off: {button.region} "
                    f"is not inside {row.content_region}"
                )

        # And the same for the three-answer question, which is the wider
        # of the two and so the one with no room to spare.
        await pilot.press("enter")
        await pilot.pause()
        app.screen.query_one("#body", TextArea).text = "Changed"
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()

        row = app.screen.query_one("#confirm-buttons")
        buttons = list(app.screen.query("#confirm-buttons Button"))
        assert len(buttons) == 3
        for button in buttons:
            assert row.content_region.contains_region(button.region), (
                f"{str(button.label)!r} is cut off: {button.region} "
                f"is not inside {row.content_region}"
            )


async def test_the_footer_is_compact_on_every_screen(diary_path):
    """One screen quietly using the roomy footer would look like a bug on
    the way in and out of it."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(NARROWEST, 20)) as pilot:
        await unlock(pilot)
        for key in ("n", "escape", "slash", "escape", "s", "escape", "a", "escape", "d"):
            await pilot.press(key)
            await pilot.pause()
            await pilot.pause()
            for footer in app.screen.query(Footer):
                assert footer.compact, f"{type(app.screen).__name__} has a roomy footer"
