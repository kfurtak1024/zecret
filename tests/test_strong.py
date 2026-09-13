"""Tests for emphasis: a phrase between asterisks, coloured as you write.

The mask's tests next door are about what must not reach the screen. These
are about what must not reach the *file*: emphasis is the second thing
Zecret draws over the text on its way out, and like the first it is drawn
and never written. A diary that filed the colour instead of the asterisks
would be a diary that quietly rewrote what someone typed.

Required coverage:
    - A phrase between asterisks is drawn in the emphasis ink and in bold,
      and the asterisks around it in the same ink without the bold.
    - **Colour and weight are both set, and neither depends on the other.**
      They are independent parameters of one escape sequence, so a terminal
      that drops bold still gets the colour; at sixteen colours, or under
      NO_COLOR, the bold is what is left. Emphasis must never rest on one
      of them alone.
    - **The document is never touched.** body_text, `modified` and what
      reaches the diary file all carry the asterisks exactly as typed, and
      carry nothing else.
    - The line drawn is the line that was typed: same characters, same
      count. Emphasis only ever colours, so nothing downstream -- the
      cursor, the wrapping, a selection -- can be put out of step by it.
    - What counts as a pair, and what does not: a sentence that trails off
      in an asterisk is not an opening, and a mark with nothing to close it
      emphasises nothing.
    - Arithmetic stays arithmetic, spaced or not. "2 * 3" falls out of the
      flanking rule; "3*4 packs and 2*6 bottles" does not, and needs the
      rule that a phrase may not open straight after a digit.
    - A run of asterisks is one mark, so "**bold**" typed from habit is
      emphasised rather than half-emphasised.
    - A phrase does not cross a line. A soft wrap is not a line, so a long
      phrase keeps its colour all the way down -- checked on the rendered
      rows, not on the parser; a newline is, so an asterisk left open at
      the end of a paragraph cannot colour the rest of the day.
    - A tab on the line does not shift the colour off the phrase. Tabs are
      expanded after the styling is laid on, which rebuilds the line.
    - **The mask wins.** Nothing is emphasised while the writing is
      covered: a coloured phrase drawn over a row of bars would
      say where the emphasis in a covered day is.
    - No key and no setting: this is always on, so there is nothing to
      advertise and nothing to leave switched off by accident.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from textual.widgets import Input

from zecret.app import ZecretApp
from zecret.models import Entry
from zecret.screens.editor import DiaryTextArea, EditorScreen, strong_spans
from zecret.screens.unlock import UnlockScreen
from zecret.storage import DiaryFile

PASSWORD = "correct horse battery staple"

TODAY = dt.date.today()
YESTERDAY = TODAY - dt.timedelta(days=1)

#: One phrase to find, one line with nothing to find on it.
BODY = "Bread came out *flat* again.\nSame mistake as last time."


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
    diary.add_entry(Entry.new(YESTERDAY, BODY))
    diary.save(key)
    return path


async def unlock(pilot) -> None:
    pilot.app.screen.query_one("#password", Input).value = PASSWORD
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()


async def open_the_day(pilot) -> DiaryTextArea:
    """Open yesterday's entry and hand back the widget it is written in."""
    await pilot.press("enter")
    await pilot.pause()
    return pilot.app.screen.query_one("#body", DiaryTextArea)


def drawn_in(body: DiaryTextArea, component: str) -> str:
    """Everything on the screen dressed the way `component` says.

    Matched on colour *and* weight, because the phrase and the asterisks
    around it now share a colour and are told apart by the bold alone --
    which is the point of the pairing and so the thing worth checking.

    Read off the rendered strips rather than off the Text handed back by
    get_line, because what is being checked is that the styling survives
    the rest of the way: TextArea paints over its own lines afterwards,
    which is the road the mask has twice been undone on.
    """
    want = body.get_component_rich_style(component)
    painted: list[str] = []
    for y in range(body.wrapped_document.height):
        for segment in body.render_line(y):
            style = segment.style
            if style is None or style.color != want.color:
                continue
            if bool(style.bold) != bool(want.bold):
                continue
            painted.append(segment.text)
    return "".join(painted).strip()


def emphasised(body: DiaryTextArea) -> str:
    return drawn_in(body, "diary-text-area--strong")


def emphasised_rows(body: DiaryTextArea) -> list[str]:
    """The emphasised text on each row of the screen, in order.

    Rows rather than one string, because what a soft wrap does to a phrase
    is only visible per row: the whole of it comes back either way.
    """
    want = body.get_component_rich_style("diary-text-area--strong")
    rows: list[str] = []
    for y in range(body.wrapped_document.height):
        row = [
            segment.text
            for segment in body.render_line(y)
            if segment.style is not None
            and segment.style.color == want.color
            and bool(segment.style.bold)
        ]
        rows.append("".join(row))
    return rows


def marks(body: DiaryTextArea) -> str:
    return drawn_in(body, "diary-text-area--strong-marker")


# --- what counts as a pair -------------------------------------------------


def spans_of(line: str) -> list[str]:
    """The emphasised phrases in `line`, without their asterisks."""
    return [line[span.text_start : span.text_end] for span in strong_spans(line)]


def marks_of(line: str) -> list[str]:
    """The asterisks doing the marking, opening then closing."""
    return [
        mark
        for span in strong_spans(line)
        for mark in (line[span.start : span.text_start], line[span.text_end : span.end])
    ]


def test_a_pair_of_asterisks_emphasises_what_is_between_them():
    assert spans_of("Make *this strong*") == ["this strong"]


def test_a_line_can_hold_several():
    assert spans_of("*one* and then *two*") == ["one", "two"]


def test_a_phrase_does_not_have_to_start_the_line_or_end_it():
    assert spans_of("mid(*x*)word") == ["x"]


@pytest.mark.parametrize(
    "line",
    [
        "2 * 3 = 6",
        "a * b * c",
        "the footnote is over there *",
        "* leading, with a space after it *",
        "***",
        "*  *",
        "nothing here at all",
    ],
)
def test_an_asterisk_that_is_not_a_pair_emphasises_nothing(line: str):
    """The rule earns its keep on the lines it leaves alone: multiplication
    and a trailing footnote mark are ordinary writing, and colouring them
    would make the feature something to work around."""
    assert strong_spans(line) == []


@pytest.mark.parametrize(
    "line",
    [
        "3*4 packs and 2*6 bottles",
        "5*6 and 7*8",
        "2*3*4",
    ],
)
def test_unspaced_arithmetic_is_still_arithmetic(line: str):
    """The flanking rule alone is not enough for a diary. "2 * 3" it keeps
    out on the spaces, but "3*4 packs and 2*6 bottles" has an asterisk that
    opens and another that closes, and came out with "4 packs and 2"
    emphasised in the middle of the sums. A phrase may not open straight
    after a digit, which is the whole of the difference."""
    assert strong_spans(line) == []


def test_a_phrase_may_still_open_inside_a_word():
    """Only digits are excluded, not letters: a script written without
    spaces between its words would otherwise have no way to emphasise
    anything but the start of a line."""
    assert spans_of("日本語*強調*です") == ["強調"]
    assert spans_of("mid(*x*)word") == ["x"]


def test_a_mark_with_nothing_to_close_it_is_not_a_phrase():
    assert spans_of("unclosed *phrase and then nothing") == []


def test_a_run_of_asterisks_is_one_mark():
    """Typed from Markdown habit, and it would be a poor joke to emphasise
    all but the outer asterisk of it."""
    assert spans_of("**bold** habit") == ["bold"]
    assert marks_of("**bold** habit") == ["**", "**"]


def test_a_phrase_never_crosses_a_line():
    """strong_spans is handed one line at a time, so this is structural --
    but it is the property that stops an asterisk left open at the end of
    a paragraph colouring everything after it."""
    assert spans_of("open *here") == []
    assert spans_of("and close* there") == []


# --- what reaches the screen -----------------------------------------------


async def test_the_phrase_is_drawn_in_the_emphasis_ink(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        assert emphasised(body) == "flat"


async def test_the_asterisks_are_drawn_in_their_own_right(diary_path):
    """They stay on the screen -- one character fewer drawn than the
    document holds would put the cursor out for the rest of the line -- so
    the only question is how they are dressed, and they are dressed as
    part of the phrase."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        assert marks(body) == "**"


async def test_the_phrase_is_bold_as_well_as_coloured(diary_path):
    """Both, never one. Bold cannot carry emphasis on its own -- a terminal
    may have no bold face, or may fake it by brightening the ink -- and
    colour cannot carry it where there is no colour to have. Setting both
    is what makes the phrase survive either being ignored."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        style = body.get_component_rich_style("diary-text-area--strong")
        assert style.color is not None, "colour must not depend on bold arriving"
        assert style.bold is True, "bold must not depend on colour arriving"


async def test_the_asterisks_share_the_colour_but_not_the_weight(diary_path):
    """What makes `*phrase*` read as one thing rather than as a word with
    punctuation stuck to it, while still letting the writing outrank the
    marks holding it up."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        phrase = body.get_component_rich_style("diary-text-area--strong")
        mark = body.get_component_rich_style("diary-text-area--strong-marker")
        assert mark.color == phrase.color
        assert not mark.bold


async def test_a_line_with_no_phrase_on_it_is_left_alone(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        assert "Same mistake" not in emphasised(body)


async def test_a_phrase_keeps_its_colour_across_a_soft_wrap(diary_path):
    """A soft wrap is not a line. The phrase is marked up before the widget
    wraps it, so the colour has to survive being divided into rows -- which
    is Rich's `Text.divide` doing the right thing, and exactly what a change
    to render_lines or to the wrapping would break without a word."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        body.text = "*" + " ".join(["wrapped"] * 30) + "*"
        await pilot.pause()

        rows = [row for row in emphasised_rows(body) if row.strip()]
        assert len(rows) > 1, "the phrase has to be long enough to wrap"
        assert "".join(rows).split() == ["wrapped"] * 30, "and all of it stays coloured"


async def test_a_tab_on_the_line_does_not_shift_the_colour(diary_path):
    """TextArea expands tabs *after* get_line has styled the line, which
    rebuilds the Text and could carry the spans to the wrong characters.

    Worth its own test because it is the same class of thing that broke
    the mask: a character whose width on the screen is not its width in
    the document. Here the check is that the phrase, not the text beside
    it, is what ends up wearing the colour.
    """
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        body.text = "\tindented *phrase* here\nplain *phrase* here"
        await pilot.pause()
        assert emphasised(body) == "phrasephrase", "both lines, tabbed or not"
        assert marks(body) == "****"


async def test_the_drawn_line_is_the_typed_line(diary_path):
    """Emphasis only ever colours. Nothing is swapped, hidden or added, so
    no measurement downstream can be put out of step by it -- which is the
    whole reason this needs none of the care the mask does."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        assert body.get_line(0).plain == "Bread came out *flat* again."


# --- what reaches the file -------------------------------------------------


async def test_the_document_keeps_the_asterisks(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        assert body.text == BODY
        assert pilot.app.screen.modified is False, "drawing it is not editing it"


async def test_a_saved_day_is_filed_exactly_as_typed(diary_path):
    """The colour is drawn, never written. A diary that filed what it drew
    would have rewritten what someone typed, which is the one mistake here
    that cannot be taken back."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        body.text = "A *whole new* day."
        await pilot.press("ctrl+s")
        await pilot.pause()

    diary, _ = DiaryFile.unlock(diary_path, PASSWORD)
    entry = diary.entry_for(YESTERDAY)
    assert entry is not None
    assert entry.body == "A *whole new* day."


# --- the mask wins ---------------------------------------------------------


async def test_nothing_is_emphasised_while_the_writing_is_covered(diary_path):
    """A coloured phrase over a row of bars would say where
    the emphasis in a covered day is, which is more than nothing about
    what it says."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        body.move_cursor((1, 2))  # a different line, so nothing here is revealed
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert emphasised(body) == ""
        assert marks(body) == ""


async def test_the_colour_comes_back_when_it_is_uncovered(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        await pilot.press("ctrl+r")
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert emphasised(body) == "flat"


# --- nothing to switch on --------------------------------------------------


def test_emphasis_costs_no_key():
    """Always on, so there is no binding for it -- which is what keeps the
    editor's bar at the four keys it advertises and the help popup at the
    keys that do something to the diary."""
    keys = {binding.key for binding in EditorScreen.BINDINGS}
    assert keys == {"ctrl+s", "escape", "ctrl+l", "ctrl+r"}
