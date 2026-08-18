"""Tests for SearchScreen: live in-memory filtering.

Required coverage:
    - '/' from the list opens search, showing everything by default.
    - Typing filters live over the entry text, case-insensitively.
    - No matches shows an empty state rather than a blank list.
    - Selecting a result opens that day in the editor; results refresh on
      return, with the cursor still on the day that was opened.
    - Escape returns to the list.
    - Searching never writes anything to disk.
    - A result carries the entry's whole first line and is clipped to the
      window, the same as a row of the diary list -- the two sit one key
      apart and would look mismatched if only one of them grew.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from textual.widgets import Input, Label, ListView, TextArea

from zecret.app import ZecretApp
from zecret.models import Entry
from zecret.screens.base import format_day
from zecret.screens.editor import EditorScreen
from zecret.screens.entry_list import EntryListScreen
from zecret.screens.search import NO_MATCHES, SearchScreen
from zecret.screens.unlock import UnlockScreen
from zecret.storage import DiaryFile

PASSWORD = "correct horse battery staple"

TODAY = dt.date.today()
YESTERDAY = TODAY - dt.timedelta(days=1)
LAST_WEEK = TODAY - dt.timedelta(days=7)


# Argon2 at test cost, and no pause after a failed unlock: this suite
# opens diaries constantly (see tests/conftest.py).
pytestmark = pytest.mark.usefixtures("cheap_kdf")


@pytest.fixture(autouse=True)
def instant_failure_delay(monkeypatch):
    monkeypatch.setattr(UnlockScreen, "FAILED_ATTEMPT_DELAY", 0.0)


@pytest.fixture
def diary_path(tmp_path: Path) -> Path:
    return tmp_path / "diary.enc"


def seed(path: Path, *entries: Entry) -> None:
    diary, key = DiaryFile.create_new(path, PASSWORD)
    for entry in entries:
        diary.add_entry(entry)
    diary.save(key)


async def unlock(pilot) -> None:
    pilot.app.screen.query_one("#password", Input).value = PASSWORD
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()


async def open_search(pilot) -> None:
    await pilot.press("slash")
    await pilot.pause()
    await pilot.pause()


async def type_query(pilot, query: str) -> None:
    pilot.app.screen.query_one("#query", Input).value = query
    await pilot.pause()
    await pilot.pause()


def result_snippets(app: ZecretApp) -> list[str]:
    return [
        str(item.query_one(Label).content).split("   ")[-1]
        for item in app.screen.query_one("#results", ListView).children
    ]


def result_days(app: ZecretApp) -> list[str]:
    return [
        str(item.query_one(Label).content).split("   ")[0]
        for item in app.screen.query_one("#results", ListView).children
    ]


@pytest.fixture
def stocked(diary_path):
    seed(
        diary_path,
        Entry.new(TODAY, "Morning walk. Frost on the grass."),
        Entry.new(YESTERDAY, "Book notes: a chapter about RIVERS."),
        Entry.new(LAST_WEEK, "Groceries: bread, milk, coffee."),
    )
    return diary_path


# --- opening ---------------------------------------------------------------


async def test_slash_opens_search(stocked):
    app = ZecretApp(diary_path=stocked)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_search(pilot)
        assert isinstance(app.screen, SearchScreen)


async def test_search_lists_everything_before_typing(stocked):
    app = ZecretApp(diary_path=stocked)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_search(pilot)
        assert len(result_snippets(app)) == 3


# --- filtering -------------------------------------------------------------


async def test_filters_on_the_entry_text(stocked):
    app = ZecretApp(diary_path=stocked)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_search(pilot)
        await type_query(pilot, "coffee")
        assert result_snippets(app) == ["Groceries: bread, milk, coffee."]


async def test_filtering_is_case_insensitive(stocked):
    app = ZecretApp(diary_path=stocked)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_search(pilot)
        await type_query(pilot, "rivers")
        assert result_days(app) == [format_day(YESTERDAY)]
        await type_query(pilot, "MORNING")
        assert result_days(app) == [format_day(TODAY)]


async def test_filtering_is_live(stocked):
    """Each keystroke narrows the results -- no submit step."""
    app = ZecretApp(diary_path=stocked)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_search(pilot)
        await type_query(pilot, "o")
        assert len(result_snippets(app)) == 3
        await type_query(pilot, "ost")
        assert result_days(app) == [format_day(TODAY)]


async def test_no_matches_shows_the_empty_state(stocked):
    app = ZecretApp(diary_path=stocked)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_search(pilot)
        await type_query(pilot, "kangaroo")
        assert result_snippets(app) == []
        empty = app.screen.query_one("#search-empty", Label)
        assert empty.display is True
        assert str(empty.content) == NO_MATCHES


async def test_clearing_the_query_restores_all_results(stocked):
    app = ZecretApp(diary_path=stocked)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_search(pilot)
        await type_query(pilot, "kangaroo")
        await type_query(pilot, "")
        assert len(result_snippets(app)) == 3


async def test_results_are_most_recent_first(diary_path):
    seed(
        diary_path,
        Entry.new(LAST_WEEK, "Older, shared word"),
        Entry.new(YESTERDAY, "Newer, shared word"),
    )

    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_search(pilot)
        await type_query(pilot, "shared")
        assert result_days(app) == [format_day(YESTERDAY), format_day(LAST_WEEK)]


# --- navigation ------------------------------------------------------------


async def test_selecting_a_result_opens_that_day_in_the_editor(stocked):
    app = ZecretApp(diary_path=stocked)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_search(pilot)
        await type_query(pilot, "coffee")
        await pilot.press("enter")  # move focus to results
        await pilot.pause()
        await pilot.press("enter")  # open the highlighted result
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        assert app.screen.date == LAST_WEEK
        assert app.screen.body_text == "Groceries: bread, milk, coffee."


async def test_results_refresh_after_editing_from_search(stocked):
    app = ZecretApp(diary_path=stocked)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_search(pilot)
        await type_query(pilot, "walk")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        app.screen.query_one("#body", TextArea).text = "Evening walk. Frost on the grass."
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.pause()

        assert isinstance(app.screen, SearchScreen)
        assert result_snippets(app) == ["Evening walk. Frost on the grass."], (
            "results must reflect the edit"
        )


async def test_escape_returns_to_the_list(stocked):
    app = ZecretApp(diary_path=stocked)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_search(pilot)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(app.screen, EntryListScreen)


async def test_searching_does_not_touch_the_file(stocked):
    """Search is pure in-memory filtering -- nothing is written, and in
    particular no plaintext."""
    before = stocked.read_bytes()
    app = ZecretApp(diary_path=stocked)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_search(pilot)
        await type_query(pilot, "coffee")
        await type_query(pilot, "walk")
    assert stocked.read_bytes() == before


# --- selecting nothing -----------------------------------------------------


async def test_enter_on_an_empty_result_list_stays_put(stocked):
    """Enter in the query box moves focus to the results, but only when
    there are results to move to."""
    app = ZecretApp(diary_path=stocked)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_search(pilot)
        await type_query(pilot, "kangaroo")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, SearchScreen)
        assert app.screen.focused is app.screen.query_one("#query", Input)


# --- keeping the reader's place --------------------------------------------


async def test_the_cursor_stays_on_the_result_you_opened(stocked):
    """Returning from an entry should not cost you the one you were on."""
    app = ZecretApp(diary_path=stocked)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_search(pilot)
        await pilot.press("enter")  # focus the results
        await pilot.pause()
        await pilot.press("down", "down")  # the oldest of the three
        await pilot.pause()
        assert app.screen.query_one("#results", ListView).index == 2

        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()

        assert app.screen.query_one("#results", ListView).index == 2


async def test_a_query_that_drops_the_highlighted_day_starts_at_the_top(stocked):
    app = ZecretApp(diary_path=stocked)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_search(pilot)
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("down", "down")
        await pilot.pause()
        assert app.screen.query_one("#results", ListView).index == 2

        await type_query(pilot, "frost")
        assert app.screen.query_one("#results", ListView).index == 0


async def test_the_highlighted_day_is_none_when_the_cursor_is_off_the_results(stocked):
    """The guard that keeps highlighted_date total, exercised directly:
    the widgets above it cannot normally desync from self.results."""
    app = ZecretApp(diary_path=stocked)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await open_search(pilot)
        screen = app.screen
        screen.query_one("#results", ListView).index = None
        assert screen.highlighted_date is None
        screen.results = []
        assert screen.highlighted_date is None
        assert screen.row_for(None) == 0


# --- how much of a day a result shows --------------------------------------


#: Longer than a narrow terminal can show, so a result carrying all of it
#: proves the length is not decided when the row is built.
LONG_FIRST_LINE = "The morning was clear and I walked further than I meant to, " * 3


async def test_a_result_carries_the_whole_first_line(diary_path):
    """Search rows grew with the diary list rather than being left behind:
    the two are one keypress apart, and a stunted result beside a full row
    reads as a bug in the one that is shorter."""
    seed(diary_path, Entry.new(TODAY, f"{LONG_FIRST_LINE}\nand a second line"))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(60, 20)) as pilot:
        await unlock(pilot)
        await open_search(pilot)
        assert result_snippets(app) == [LONG_FIRST_LINE.strip()]


async def test_results_are_clipped_by_the_window_rather_than_wrapped(diary_path):
    seed(diary_path, Entry.new(TODAY, LONG_FIRST_LINE))
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(60, 20)) as pilot:
        await unlock(pilot)
        await open_search(pilot)
        rows = [
            item.query_one(Label) for item in app.screen.query_one("#results", ListView).children
        ]
        assert rows
        for label in rows:
            assert label.styles.text_wrap == "nowrap"
            assert label.styles.text_overflow == "ellipsis"
            assert label.size.height == 1, "a day must not become two rows"
