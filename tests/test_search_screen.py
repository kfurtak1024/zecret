"""Tests for SearchScreen: live in-memory filtering.

Required coverage:
    - '/' from the list opens search, showing everything by default.
    - Typing filters live over the entry text, case-insensitively.
    - No matches shows an empty state rather than a blank list.
    - Selecting a result opens that day in the editor; results refresh on
      return.
    - Escape returns to the list.
    - Searching never writes anything to disk.
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
