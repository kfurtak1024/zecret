"""Tests for the mask: covering the writing while it is on the screen.

The diary's other defences are all about the diary you are not looking at
-- the password, ctrl+l on the way out, the idle timer for when you forget.
The mask is the one that covers a diary you *are* looking at, so what it
has to get right is different: nothing about it may reach the disk, and
nothing on the screen may quietly read through it.

Required coverage:
    - ctrl+r covers the writing, and pressing it again uncovers it.
    - Everything is covered except the word the cursor is touching, and
      that reveal follows the cursor -- the word behind it closes again.
    - A covered word is drawn as bars, one per character.
    - **The document is never touched.** The bars exist only on the way to
      the screen: body_text, `modified` and what reaches the diary file
      are all exactly as they would be uncovered. Masking by rewriting the
      text would file an entry full of blocks, which is the one mistake
      here that cannot be taken back.
    - A character two cells wide still takes two cells when it is covered.
      A bar is one cell, so those cannot be swapped without shortening the
      line and losing the widget's place in it; they are painted in ink
      the colour of their own background instead, and this checks that
      what reaches the screen is still the width it was.
    - Nothing paints over the mask. TextArea styles the cursor's line and
      the selection *after* the mask is laid on, and both set the two
      colours that the wide-character path relies on being equal -- ctrl+a
      is select-all, and it laid the whole entry bare on a covered
      screen back when every character was hidden that way.
    - The mask belongs to the session, not to the day: it survives going
      back to the list and opening another entry. It is not written down,
      so a new session starts uncovered.
    - The key is advertised, because a mask nobody can find is no use to
      the person who needs it.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from textual.widgets import Input, TextArea

from zecret.app import ZecretApp
from zecret.models import Entry
from zecret.screens.editor import BAR, DiaryTextArea, EditorScreen, run_at, word_runs
from zecret.screens.entry_list import EntryListScreen
from zecret.screens.unlock import UnlockScreen
from zecret.storage import DiaryFile

PASSWORD = "correct horse battery staple"

TODAY = dt.date.today()
YESTERDAY = TODAY - dt.timedelta(days=1)

BODY = "Long walk once the rain stopped.\nCame back the long way."


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


def readable(body: TextArea) -> str:
    """Everything on the screen a person could actually read.

    Two things are not that. A covered character has been swapped for a
    bar, so the bars come out; and a character too wide to swap is painted
    in ink the colour of its own background, so the segments whose two
    colours match come out as well. What is left is the writing.
    """
    words: list[str] = []
    for y in range(body.wrapped_document.height):
        for segment in body.render_line(y):
            style = segment.style
            if style is None or style.color is None or style.bgcolor is None:
                continue
            if style.color.triplet == style.bgcolor.triplet:
                continue
            words.append(segment.text.replace(BAR, " "))
    return " ".join("".join(words).split())


# --- switching it on -------------------------------------------------------


async def test_ctrl_r_covers_the_writing(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        assert "Long walk once the rain" in readable(body), "uncovered to begin with"

        await pilot.press("ctrl+r")
        await pilot.pause()
        assert body.masked is True
        assert "Long walk" not in readable(body)


async def test_ctrl_r_again_uncovers_it(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        await pilot.press("ctrl+r")
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert body.masked is False
        assert "Long walk once the rain" in readable(body)


async def test_the_key_is_advertised(diary_path):
    """A mask nobody can find protects nobody. The editor's bar carries
    three keys in a bar with room for eight, so this one is shown."""
    advertised = {
        binding.key
        for binding in EditorScreen.BINDINGS
        if getattr(binding, "show", False) and getattr(binding, "key", None)
    }
    assert "ctrl+r" in advertised


# --- what stays readable ---------------------------------------------------


async def test_only_the_word_under_the_cursor_is_left_readable(diary_path):
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        body.move_cursor((0, 2))  # inside "Long"
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert readable(body) == "Long"


async def test_the_reveal_follows_the_cursor(diary_path):
    """The word behind you closes again, which is the whole point: what is
    protected is what you wrote before now."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        body.move_cursor((0, 2))
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert readable(body) == "Long"

        body.move_cursor((0, 7))  # inside "walk"
        await pilot.pause()
        assert readable(body) == "walk", "the last word must close behind the cursor"


async def test_a_word_on_another_line_stays_covered(diary_path):
    """Only the cursor's own line has a word to spare."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        body.move_cursor((1, 2))  # inside "Came", on the second line
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert readable(body) == "Came"


async def test_a_covered_word_is_drawn_as_bars(diary_path):
    """The characters are swapped, not merely hidden -- which is what
    stops a later coat of paint bringing them back."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        body.move_cursor((0, 2))  # "Long" is the word left readable
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()

        drawn = "".join(segment.text for segment in body.render_line(0))
        assert BAR * 4 in drawn, "a four-letter word should be four bars"
        assert "walk" not in drawn, "the letters must be gone, not just dressed"
        assert "Long" in drawn, "the cursor's word is still itself"


# --- what must never happen ------------------------------------------------


async def test_the_mask_never_reaches_the_document(diary_path):
    """The cardinal rule. The mask is drawn, never written."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_the_day(pilot)
        await pilot.press("ctrl+r")
        await pilot.pause()

        assert app.screen.body_text == BODY
        assert app.screen.modified is False, "covering the writing is not editing it"


async def test_saving_while_masked_writes_the_real_words(diary_path):
    """A diary full of blocks is the one mistake here that cannot be
    taken back, so this is checked against the file itself."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        await pilot.press("ctrl+r")
        await pilot.pause()
        body.text = f"{BODY}\nWritten behind the bars."
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    saved = reopened.entries[YESTERDAY].body
    assert saved == f"{BODY}\nWritten behind the bars."
    assert "█" not in saved


async def test_a_two_cell_character_still_takes_two_cells(diary_path):
    """A bar is one cell, so a two-cell character cannot be swapped for
    one without shortening the line and losing the widget's place in it.
    Those keep their own glyph and are covered by colour instead.

    The cursor is parked at the far end deliberately: on the wide word it
    would be the one word left readable, and this would pass while
    covering nothing.
    """
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        body.text = "日本語 and rain"
        body.move_cursor((0, len("日本語 and rain")))  # on "rain", not on the wide word
        await pilot.pause()
        bare = body.render_line(0).cell_length

        await pilot.press("ctrl+r")
        await pilot.pause()
        assert body.render_line(0).cell_length == bare, "the line changed width"

        drawn = "".join(segment.text for segment in body.render_line(0))
        assert "日本語" in drawn, "a wide character keeps its own glyph"
        assert "and" not in drawn, "the single-cell word beside it is swapped for bars"
        assert readable(body) == "rain", "and the wide word is covered all the same"


async def test_selecting_does_not_read_through_the_mask(diary_path):
    """ctrl+a is select-all, and TextArea paints the selection after the
    mask -- so one keystroke used to lay the whole entry bare on a screen
    that was supposed to be covered."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        await pilot.press("ctrl+r")
        await pilot.pause()
        await pilot.press("ctrl+a")
        await pilot.pause()

        assert body.selected_text == BODY, "the selection itself is real"
        assert "Long walk" not in readable(body)


async def test_the_cursor_line_highlight_does_not_read_through_it_either(diary_path):
    """The other style TextArea lays on after the mask. It would have
    given away the whole line the cursor was on, rather than one word."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        body = await open_the_day(pilot)
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert body.highlight_cursor_line is False
        assert readable(body) == "Long", "the cursor's line, not just its word"


# --- whose state it is -----------------------------------------------------


async def test_the_mask_survives_opening_another_day(diary_path):
    """Someone writing in a carriage covers the screen once, not once per
    entry -- so it lives on the app rather than on the screen."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_the_day(pilot)
        await pilot.press("ctrl+r")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen)

        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        assert app.screen.query_one("#body", DiaryTextArea).masked is True


async def test_a_new_session_starts_uncovered(diary_path):
    """Never written down: a diary that opened unreadable would be a
    puzzle before it was a protection."""
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        assert app.masked is False
        body = await open_the_day(pilot)
        assert body.masked is False


# --- the rule for what a bar covers ----------------------------------------


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("", []),
        ("     ", []),
        ("one", [(0, 3)]),
        ("one two", [(0, 3), (4, 7)]),
        ("  padded  ", [(2, 8)]),
        ("don't stop", [(0, 5), (6, 10)]),
        ("tabs\tbetween", [(0, 4), (5, 12)]),
        ("trailing. ", [(0, 9)]),
    ],
)
def test_word_runs(line, expected):
    """A run is anything with no blank in it -- punctuation rides inside
    the bar rather than sticking out of it, and an apostrophe does not
    split a word in two and tell a reader where the apostrophes are."""
    assert word_runs(line) == expected


@pytest.mark.parametrize(
    ("column", "expected"),
    [
        (0, (0, 3)),  # at the start of a word
        (1, (0, 3)),  # inside it
        (3, (0, 3)),  # just past its last letter, which is where typing leaves you
        (4, (4, 7)),  # at the start of the next
        (7, (4, 7)),  # at the end of the last word
        (99, None),  # past everything
    ],
)
def test_run_at(column, expected):
    assert run_at(word_runs("one two"), column) == expected


def test_run_at_finds_nothing_on_a_blank_line():
    assert run_at(word_runs("   "), 1) is None
