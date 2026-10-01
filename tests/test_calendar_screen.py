"""Tests for CalendarScreen: the year laid out, as the list's other face.

Required coverage:
    - 'c' on the entry list opens it, on the day the list's cursor was on,
      or on today where the list has nothing to be on.
    - 'c' and escape both go back, and the list lands on the calendar's day
      -- or, where that day has no entry, on the nearest older one. The day
      is kept on the screen itself, so it can still be read once the
      widgets are gone.
    - 'e' and enter both open the day under the cursor in the editor,
      written or not, and a day written there is marked on the way back.
      The day under the cursor means the widget's, even when the key that
      moved it has not yet been heard about by the screen -- 'right' and
      'enter' in one burst used to open the day just left, and 'c' after
      it landed the list on the wrong day.
    - '[' and ']' move a year, and the header names the year on show and
      how many of its days are written.
    - The months sit three across at 80 columns, four at 100, six where
      there is room for six -- never five -- and none is cut off.
    - In a terminal too short for the year, the cursor's month is scrolled
      into view, and the top row of months brings the year's title along.
    - The first frame drawn is already the finished one: the right number
      of months across and scrolled to the cursor. The year used to be seen
      rearranging itself as the view opened. Resizing rearranges it again.
    - ctrl+l locks from here -- and from a day opened here -- '?' opens
      help, 'q' quits.
    - The whole year fits the size tools/screenshots.py shoots it at.
    - Its key bar advertises editing, going back and locking, and fits 80
      columns.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from textual.widgets import Input, Label

from zecret.app import ZecretApp
from zecret.models import Entry
from zecret.screens.calendar import YearCalendar
from zecret.screens.calendar_view import CalendarScreen, months_across
from zecret.screens.editor import EditorScreen
from zecret.screens.entry_list import EntryListScreen
from zecret.screens.help import HelpScreen, documented_bindings
from zecret.screens.unlock import UnlockScreen
from zecret.storage import DiaryFile

PASSWORD = "correct horse battery staple"
TODAY = dt.date.today()

#: Days in a past year with known edges, so nothing here depends on when
#: the suite runs.
WRITTEN = [dt.date(2024, 3, 4), dt.date(2024, 3, 17), dt.date(2024, 9, 2)]

pytestmark = pytest.mark.usefixtures("cheap_kdf")


@pytest.fixture(autouse=True)
def instant_failure_delay(monkeypatch):
    monkeypatch.setattr(UnlockScreen, "FAILED_ATTEMPT_DELAY", 0.0)


@pytest.fixture
def diary_path(tmp_path: Path) -> Path:
    return tmp_path / "diary.enc"


def seed(path: Path, *days: dt.date) -> None:
    diary, key = DiaryFile.create_new(path, PASSWORD)
    for day in days:
        diary.add_entry(Entry.new(day, f"Body for {day}"))
    diary.save(key)


async def unlock(pilot) -> None:
    pilot.app.screen.query_one("#password", Input).value = PASSWORD
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()


async def press(pilot, *keys: str) -> None:
    """Press, and let the screens that keys push or pop settle."""
    for key in keys:
        await pilot.press(key)
        await pilot.pause()
        await pilot.pause()


def year(app: ZecretApp) -> YearCalendar:
    return app.screen.query_one(YearCalendar)


def footer_text(app: ZecretApp) -> str:
    strips = app.screen._compositor.render_strips()
    return "".join(segment.text for segment in strips[-1])


def header_text(app: ZecretApp) -> str:
    strips = app.screen._compositor.render_strips()
    return "".join(segment.text for segment in strips[0]).strip()


# --- getting there and back ------------------------------------------------


async def test_c_opens_the_calendar_on_the_highlighted_day(diary_path):
    seed(diary_path, *WRITTEN)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await press(pilot, "down")
        assert app.screen.selected_entry.date == WRITTEN[1]
        await press(pilot, "c")
        assert isinstance(app.screen, CalendarScreen)
        assert year(app).date == WRITTEN[1]
        assert year(app).has_focus


async def test_an_empty_diary_opens_the_calendar_on_today(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await press(pilot, "c")
        assert year(app).date == TODAY


@pytest.mark.parametrize("key", ["c", "escape"])
async def test_c_and_escape_go_back_to_the_list(diary_path, key):
    seed(diary_path, *WRITTEN)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await press(pilot, "c", key)
        assert isinstance(app.screen, EntryListScreen)


async def test_the_list_lands_on_the_day_the_calendar_was_on(diary_path):
    seed(diary_path, *WRITTEN)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await press(pilot, "c")
        year(app).move_to(WRITTEN[0])
        await press(pilot, "escape")
        assert app.screen.selected_entry.date == WRITTEN[0]


async def test_an_unwritten_day_lands_the_list_on_the_nearest_older_one(diary_path):
    """The calendar's cursor is on a gap more often than not -- that is
    what it is for -- and the row nearest it is where the eye goes next."""
    seed(diary_path, *WRITTEN)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await press(pilot, "c")
        year(app).move_to(dt.date(2024, 6, 1))
        await press(pilot, "c")
        assert app.screen.selected_entry.date == WRITTEN[1]


async def test_the_day_is_kept_for_the_list_even_once_the_widget_is_gone(diary_path):
    """The list reads where the calendar was left as the calendar is being
    torn down, and Textual takes a popped screen's widgets away in a task
    of its own -- so what the list reads must not be a query into them."""
    seed(diary_path, *WRITTEN)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await press(pilot, "c")
        calendar = app.screen
        year(app).move_to(WRITTEN[0])
        await pilot.pause()
        await year(app).remove()
        assert calendar.date == WRITTEN[0]


async def test_a_day_older_than_the_diary_lands_the_list_at_its_foot(diary_path):
    seed(diary_path, *WRITTEN)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await press(pilot, "c")
        year(app).move_to(dt.date(2020, 1, 1))
        await press(pilot, "c")
        assert app.screen.selected_entry.date == WRITTEN[0]


# --- writing ---------------------------------------------------------------


@pytest.mark.parametrize("key", ["e", "enter"])
async def test_e_and_enter_open_the_day_under_the_cursor(diary_path, key):
    seed(diary_path, *WRITTEN)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await press(pilot, "c")
        year(app).move_to(WRITTEN[2])
        await press(pilot, key)
        assert isinstance(app.screen, EditorScreen)
        assert app.screen.date == WRITTEN[2]
        assert app.screen.query_one("#body").text == f"Body for {WRITTEN[2]}"


async def test_a_day_written_from_the_calendar_is_marked_on_the_way_back(diary_path):
    seed(diary_path, *WRITTEN)
    missed = dt.date(2024, 3, 10)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await press(pilot, "c")
        year(app).move_to(missed)
        await press(pilot, "e")
        assert app.screen.query_one("#body").text == "", "an unwritten day opens empty"
        await press(pilot, "x", "ctrl+s", "escape")

        assert isinstance(app.screen, CalendarScreen)
        assert missed in year(app).written
        assert "10•" in year(app).months[2].render().plain
        assert year(app).date == missed, "and the cursor is where it was"


async def test_writing_from_the_calendar_reaches_the_list(diary_path):
    seed(diary_path, *WRITTEN)
    missed = dt.date(2024, 3, 10)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await press(pilot, "c")
        year(app).move_to(missed)
        await press(pilot, "e", "x", "ctrl+s", "escape", "escape")
        assert isinstance(app.screen, EntryListScreen)
        assert app.screen.selected_entry.date == missed


# --- years -----------------------------------------------------------------


async def test_the_brackets_move_a_year(diary_path):
    seed(diary_path, *WRITTEN)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await press(pilot, "c")
        year(app).move_to(WRITTEN[2])
        await press(pilot, "left_square_bracket")
        assert year(app).date == dt.date(2023, 9, 2)
        await press(pilot, "right_square_bracket", "right_square_bracket")
        assert year(app).date == dt.date(2025, 9, 2)


async def test_the_header_and_title_name_the_year_and_count_it(diary_path):
    seed(diary_path, *WRITTEN)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await press(pilot, "c")
        year(app).move_to(WRITTEN[2])
        await pilot.pause()
        assert header_text(app) == "Zecret — Calendar · 2024 · 3 entries"
        assert str(app.screen.query_one("#year-title", Label).content) == "2024"

        await press(pilot, "left_square_bracket")
        assert header_text(app) == "Zecret — Calendar · 2023 · 0 entries"


# --- layout ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("width", "across"),
    [(60, 2), (80, 3), (100, 4), (130, 4), (150, 6)],
    ids=["narrow", "default-terminal", "screenshot-width", "no-five", "wide"],
)
async def test_months_sit_as_many_across_as_fit(diary_path, width, across):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(width, 30)) as pilot:
        await unlock(pilot)
        await press(pilot, "c")
        months = year(app).months
        top_row = [month for month in months if month.region.y == months[0].region.y]
        assert len(top_row) == across
        # Not cut off: every month of the row ends inside the window.
        assert all(month.region.right <= width for month in top_row)


async def test_the_cursors_month_is_scrolled_into_view(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await unlock(pilot)
        await press(pilot, "c")
        year(app).move_to(dt.date(2024, 1, 15))
        await pilot.pause()
        title = app.screen.query_one("#year-title")
        assert title.region.y >= 0, "the top row brings the year's title with it"

        year(app).move_to(dt.date(2024, 12, 15))
        await pilot.pause()
        december = year(app).months[11]
        box = app.screen.query_one("#year-box")
        assert box.region.contains_region(december.region)


# --- the keys every main view shares ---------------------------------------


async def test_ctrl_l_locks_from_the_calendar(diary_path):
    seed(diary_path, *WRITTEN)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await press(pilot, "c", "ctrl+l")
        assert isinstance(app.screen, UnlockScreen)
        assert not app.is_unlocked


async def test_locking_from_a_day_opened_in_the_calendar(diary_path):
    """Locking pops the editor first, which resumes the calendar under it
    -- by which time the diary is gone, and the calendar must not reach
    for it to redraw its marks."""
    seed(diary_path, *WRITTEN)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await press(pilot, "c", "e", "ctrl+l")
        assert isinstance(app.screen, UnlockScreen)
        assert not app.is_unlocked


async def test_question_mark_opens_help_from_the_calendar(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await press(pilot, "c", "question_mark")
        assert isinstance(app.screen, HelpScreen)
        await press(pilot, "escape")
        assert isinstance(app.screen, CalendarScreen)


async def test_q_quits_from_the_calendar(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await press(pilot, "c", "q")
        assert app.return_code == 0


async def test_the_key_bar_advertises_its_keys_in_eighty_columns(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await unlock(pilot)
        await press(pilot, "c")
        bar = footer_text(app)
        advertised = [
            f"{app.get_key_display(binding)} {binding.description}"
            for binding in documented_bindings(CalendarScreen.BINDINGS)
            if binding.show
        ]
        assert {"e Edit", "c List", "^l Lock"} <= set(advertised)
        missing = [entry for entry in advertised if entry not in bar]
        assert not missing, f"the footer at 80 columns does not fully show: {missing}"


#: The size tools/screenshots.py shoots the calendar at. Written out rather
#: than imported, as in test_help_screen.py: tools/ is not in the sdist.
SHOT_SIZE = (100, 34)


async def test_the_whole_year_fits_the_size_the_screenshots_use(diary_path):
    """Nothing fails when a picture is cropped, so the check lives here.
    Raise both together if the view genuinely needs more room."""
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=SHOT_SIZE) as pilot:
        await unlock(pilot)
        await press(pilot, "c")
        box = app.screen.query_one("#year-box")
        assert box.virtual_size.height <= box.size.height, (
            f"the year no longer fits {SHOT_SIZE}; the screenshot will be cropped"
        )


# --- the first frame -------------------------------------------------------


@pytest.mark.parametrize(
    ("width", "across"),
    [(53, 1), (54, 2), (76, 2), (77, 3), (99, 3), (100, 4), (145, 4), (146, 6)],
)
def test_months_across_steps_at_the_width_each_needs(width, across):
    assert months_across(width) == across


@pytest.mark.parametrize("size", [(80, 24), (150, 30)], ids=["scrolled", "wide"])
async def test_the_first_frame_drawn_is_the_finished_one(diary_path, size):
    """Every frame the calendar reaches the terminal with, recorded: none of
    them may be the year half laid out -- the wrong number of months
    across, or the view not yet scrolled to the cursor."""
    seed(diary_path, *WRITTEN)
    app = ZecretApp(diary_path=diary_path)
    frames: list[tuple[frozenset[str], float]] = []
    display = app._display

    def recording(screen, renderable) -> None:
        if isinstance(screen, CalendarScreen) and not app._batch_count:
            box = screen.query_one("#year-box")
            frames.append((frozenset(screen.classes), box.scroll_y))
        display(screen, renderable)

    app._display = recording
    async with app.run_test(size=size) as pilot:
        await unlock(pilot)
        # The list opens on the newest entry, 2 September -- low enough in
        # its year that at 80x24 the view has to scroll to show it.
        await press(pilot, "c")
        await pilot.pause()
        final = (frozenset(app.screen.classes), app.screen.query_one("#year-box").scroll_y)

    assert f"-months-{months_across(size[0])}" in final[0]
    if size == (80, 24):
        assert final[1] > 0, "September should need scrolling to at 80x24"
    assert frames, "the calendar was never drawn"
    assert frames[0] == final, f"first frame {frames[0]}, settled on {final}"


async def test_resizing_rearranges_the_months(diary_path):
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test(size=(80, 24)) as pilot:
        await unlock(pilot)
        await press(pilot, "c")
        assert app.screen.has_class("-months-3")
        await pilot.resize_terminal(150, 30)
        await pilot.pause()
        await pilot.pause()
        assert app.screen.has_class("-months-6")
        assert not app.screen.has_class("-months-3")


async def test_repaints_are_released_once_the_calendar_is_shown(diary_path):
    """The hold on repaints is app-wide: one left behind would freeze every
    screen, not just this one."""
    seed(diary_path)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await press(pilot, "c")
        assert app._batch_count == 0
        await press(pilot, "escape", "c", "ctrl+l")
        assert app._batch_count == 0


# --- keys in a burst -------------------------------------------------------


async def test_a_key_right_after_a_move_acts_on_the_new_day(diary_path):
    """The move and the key in one go, with no chance for the widget's
    DateChanged to reach the screen in between -- which is what a fast
    typist or a batched SSH connection delivers."""
    seed(diary_path, *WRITTEN)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await press(pilot, "c")
        year(app).move_to(dt.date(2024, 3, 10))
        await pilot.pause()

        year(app).action_next_day()
        app.screen.action_edit_day()
        await pilot.pause()
        assert isinstance(app.screen, EditorScreen)
        assert app.screen.date == dt.date(2024, 3, 11)


async def test_leaving_right_after_a_move_hands_back_the_new_day(diary_path):
    seed(diary_path, *WRITTEN)
    app = ZecretApp(diary_path=diary_path)
    async with app.run_test() as pilot:
        await unlock(pilot)
        await press(pilot, "c")
        calendar = app.screen
        year(app).move_to(WRITTEN[0])
        await pilot.pause()

        year(app).action_previous_day()
        calendar.action_back()
        assert calendar.date == WRITTEN[0] - dt.timedelta(days=1)
