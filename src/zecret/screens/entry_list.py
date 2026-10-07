"""Main screen: the diary, one row per day, most recent first, grouped
into months.

Responsibilities:
    - Render entries from app.diary.entries, sorted by date descending,
      under a heading per month ("August 2026 · 12 entries"). Because the
      heading names the month, the rows under it need only the weekday and
      day of the month.
    - Keybindings: 'n' write today -> EditorScreen, 'c' the year laid out
      -> CalendarScreen, 'a' pick another day -> DatePromptScreen (given
      the days already written, which its calendar marks) -> EditorScreen,
      'enter' open selected day -> EditorScreen, 'd' delete selected (with
      confirmation modal), 'r' re-read the file, '/' -> SearchScreen,
      's' -> SettingsScreen, ctrl+l lock, '?' help, 'q' quit. Plus getting
      around a long diary: j/k, g/G, home/end and the page keys, none of
      which reach the footer.
    - After returning from EditorScreen/SearchScreen/CalendarScreen,
      refresh the list from
      the current in-memory app.diary state (no re-read from disk needed,
      since app.diary is the source of truth during the session), leaving
      the cursor on the day it was on -- a refresh is a redraw, not a
      reason to send a reader of a years-long diary back to the top. After
      the editor, "the day it was on" is the day just written, even when
      that day had no row until now. After the calendar, it is the day
      the calendar's cursor was on, or the nearest older one written.

'n' and 'a' both land on a date rather than on a new entry: the editor
opens whatever that day holds, so writing more about today just continues
today's entry instead of starting a second one.

Grouping is presentation only -- nothing about it reaches models.py or
storage.py, which know only about individual dated entries. The month
headings share the OptionList with the entries as disabled options, which
Textual's cursor navigation steps over and its clicks ignore. That leaves
one thing to get right: a row index is no longer an index into the
entries, so everything that maps a selection back to an entry goes through
self.rows.

An OptionList and not a ListView, because a diary is kept for years. A
ListView is a widget per row -- a ListItem holding a Label -- and every
one of them is mounted, styled and laid out on every rebuild, whether or
not it is anywhere near the screen: ten years of entries was 7,500 widgets
and eight seconds, on every return to this screen. An OptionList is one
widget that draws only the lines in view, and rebuilds the same ten years
in about a tenth of a second.

The delete confirmation uses the shared ConfirmScreen modal (screens/
confirm.py), as does leaving unsaved edits in the editor. That modal
offers a third answer, "save first", where there is something to save;
this question does not take it, since a deletion has no such road.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from itertools import groupby
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import Label
from textual.widgets.option_list import Option

from zecret.crypto import ZecretDecryptError
from zecret.models import Entry
from zecret.screens.base import (
    DayList,
    ZecretScreen,
    count_entries,
    day_row,
    day_summary,
    format_day,
    format_month,
    plain,
    save_error,
    today,
    unchanged,
)
from zecret.screens.calendar_view import CalendarScreen
from zecret.screens.confirm import Choice, ConfirmScreen
from zecret.screens.date_prompt import DatePromptScreen
from zecret.screens.editor import EditorScreen
from zecret.screens.header import DiaryFooter, DiaryHeader
from zecret.screens.search import SearchScreen
from zecret.screens.settings import SettingsScreen
from zecret.storage import DiaryFile, ZecretConflictError

EMPTY_MESSAGE = "Nothing written yet. Press 'n' to write about today."

#: A reload that cannot use the key this session holds. The only other
#: session that could cause it is one that changed the password.
RELOAD_REKEYED = "The password was changed elsewhere. Quit and unlock again."


#: Lines a month heading takes on screen: the blank line that sets it apart,
#: and the heading. A day takes one. Paging counts these rather than rows --
#: see EntryListScreen.move_cursor.
HEADING_LINES = 2


def heading_option(first_of_month: dt.date, count: int) -> Option:
    """The row naming a month, with a blank line above it to set it apart.

    Disabled, so the cursor steps over it and a click on it does nothing --
    it is a signpost, not somewhere to be. The blank line is part of the
    option rather than padding around it: an option has no margin of its
    own, and a separate blank option would be one more row to step over.
    """
    heading = f"{format_month(first_of_month)} · {count_entries(count)}"
    return Option(plain("\n" * (HEADING_LINES - 1) + heading), disabled=True)


def entry_option(entry: Entry) -> Option:
    """The row for one day, exactly as written -- see base.plain()."""
    return day_row(day_summary(entry))


class EntryListScreen(ZecretScreen):
    """Lists the days written and routes to write/edit/search/settings."""

    #: `show` decides what goes in the footer and nothing else -- the help
    #: popup lists every binding here regardless. The bar holds about eighty
    #: columns and these eight fill sixty-nine of them, so the room that was
    #: spare is spent; everything below them is no less real for being
    #: found through '?' instead.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("n", "today", "Today"),
        Binding("c", "calendar", "Calendar"),
        # Out of the bar since the calendar arrived: the calendar answers
        # the same question -- which day? -- with the whole year to point
        # at, and the bar had room for one of the two. This stays the
        # quicker road for a day whose date you already know.
        Binding("a", "another_day", "Another day", show=False),
        Binding("d", "delete_entry", "Delete"),
        Binding("slash", "search", "Search", key_display="/"),
        Binding("s", "settings", "Settings"),
        # A chord rather than a letter, and the same chord the editor
        # carries: locking is the one thing you want to press without first
        # working out which screen you are on, and a bare letter cannot be
        # bound where there is text to type into. ctrl+l is what a password
        # manager locks with, and Textual leaves it free -- no widget in
        # this app binds it, and the terminal's own clear-screen meaning
        # belongs to a shell prompt, which is not what is running here.
        #
        # Shown, which the rest of this group's weight of use would not
        # earn it. Whether someone can find this key is a security property
        # and not a convenience: a writer stepping away who does not know
        # it either quits, losing where they were, or leaves the diary open
        # on the screen. That is not true of 'r' or of the movement keys.
        Binding("ctrl+l", "lock", "Lock"),
        # Bound here rather than app-wide on purpose: a '?' typed into the
        # editor, the search box or a password field must stay a '?'. The
        # action is the app's, which the calendar shares -- see
        # ZecretApp.action_help.
        Binding("question_mark", "app.help", "Help", key_display="?"),
        # "app.quit", not "quit": a binding's action is dispatched on the
        # node that declares it, and a Screen has no action_quit -- an
        # unqualified "quit" here silently does nothing. The app's is
        # Zecret's own override, so this key and ctrl+q ask the same
        # question about unsaved writing rather than one of them not.
        Binding("q", "app.quit", "Quit"),
        # --- real, but not worth the width -------------------------------
        # The OptionList has focus and handles Enter itself, posting
        # OptionSelected -- which on_option_list_option_selected turns into
        # the same call. The action behind this binding is a second door
        # onto the same room rather than the one you walk through, and
        # guards its own selection accordingly. Hidden because the list's
        # own enter binding shadows it in the bar anyway: it never rendered
        # there.
        # "Edit", as the calendar's 'e' and enter are: both open the chosen
        # day in the editor.
        Binding("enter", "open_entry", "Edit", show=False),
        Binding("r", "reload", "Reload", show=False),
        # --- getting around ----------------------------------------------
        # A diary kept for years is a long list, and arrow keys alone make
        # its far end hundreds of presses away. j/k/g/G are what a terminal
        # reader will try first; home/end/page are what everyone else will.
        # j/k/g/G are ours alone. home, end and the page keys are the
        # OptionList's as well, and its page keys cannot be trusted with a
        # diary: a page up that lands on the month heading at the top finds
        # nothing enabled above it and drops the highlight altogether.
        # `priority` takes all four back so that every jump goes through
        # move_cursor, which walks off a heading rather than giving up --
        # safe here because this screen has no text field for them to mean
        # anything else in.
        Binding("j", "cursor_down", "Down a day", show=False),
        Binding("k", "cursor_up", "Up a day", show=False),
        Binding("pagedown", "page_down", "Down a screenful", show=False, priority=True),
        Binding("pageup", "page_up", "Up a screenful", show=False, priority=True),
        Binding("g", "first_entry", "Newest entry", show=False),
        Binding("home", "first_entry", "Newest entry", show=False, priority=True),
        Binding("G", "last_entry", "Oldest entry", show=False),
        Binding("end", "last_entry", "Oldest entry", show=False, priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        # One element per option of the list, in display order: the entry
        # that row shows, or None where the row is a month heading. This is
        # the only thing that maps a highlighted row back to a day.
        self.rows: list[Entry | None] = []
        # The diary the rows were last built from, so that coming back to
        # an unchanged one does not rebuild it -- see on_screen_resume.
        self.drawn: dict[dt.date, Entry] | None = None
        # The two screens this one sends the reader to and lands back from:
        # the day open in the editor, and the calendar while it is open over
        # this screen. Both are read in on_screen_resume, which is what
        # decides where the cursor goes on the way back -- see there.
        self.editing: dt.date | None = None
        self.calendar: CalendarScreen | None = None

    def compose(self) -> ComposeResult:
        yield DiaryHeader()
        yield Label(EMPTY_MESSAGE, id="entries-empty")
        yield DayList(id="entries")
        yield DiaryFooter()

    def on_screen_resume(self) -> None:
        """Fires when this screen is shown, including after returning from
        the editor or search -- so the list always reflects app.diary.

        Rebuilt only when the diary has changed since the rows were drawn.
        Most returns change nothing -- closing the help, cancelling a
        question, leaving settings, a calendar visit or a day read and not
        written -- and a rebuild replaces every row of a list that can be
        years long. Where nothing changed but there is a day to land on,
        the cursor goes there over the rows as they are.

        Where to land is decided here, for both of the screens that hand a
        day back, because this is the one place certain to run after the
        screen has gone and before the list is redrawn. Coming back from
        the editor lands on the day just written -- including one that had
        no row until now -- and on nothing new if the day was left
        unwritten. Coming back from the calendar lands on its cursor's day,
        or the nearest older one written.

        (The editor's day used to come back through its dismiss callback,
        which nothing orders against this handler: which of the two ran
        first depended on the road out of the editor, and the callback had
        to work out from the rows whether the rebuild had happened yet.)

        Also fires on the way out, as locking pops the screens above this
        one. There is no diary to draw from by then, and nothing to draw
        it onto.

        And fires late, sometimes, behind a screen already pushed over this
        one: the which-day question opens the editor from its dismiss
        callback, which can run before this handler does. Nothing is
        decided then -- the editor is still open, and this will be asked
        again when it closes.
        """
        if not self.zecret.is_unlocked or self.app.screen is not self:
            return
        diary, _ = self.zecret.unlocked
        landing: dt.date | None = None
        if self.calendar is not None:
            landing, self.calendar = self.calendar.date, None
        if self.editing is not None:
            if self.editing in diary.entries:
                landing = self.editing
            self.editing = None
        if not unchanged(self.drawn, diary.entries):
            self.refresh_entries(landing)
        elif landing is not None:
            self.move_cursor_to(self.row_for(landing))

    def refresh_entries(self, landing: dt.date | None = None) -> None:
        """Rebuild the list from the in-memory diary, most recent day first,
        with a heading above each month, and put the cursor on `landing` --
        or, if there is none, back on the day it was on.

        Synchronous, start to finish: an OptionList takes its options in one
        call with nothing to await, so no two rebuilds can interleave and
        nothing else can see the list half-built. (A ListView rebuild was a
        sequence of awaits, and needed a lock to keep two of them from
        duplicating rows.)
        """
        diary, _ = self.zecret.unlocked
        entries = sorted(diary.entries.values(), key=lambda entry: entry.date, reverse=True)

        listing = self.entries_list
        # Read before clearing: rebuilding is what loses the reader's place,
        # so where they were has to be taken down first. A day to land on
        # may have no entry at all -- the calendar's often does not -- and
        # row_for then finds the nearest that does.
        was_on = landing if landing is not None else self.highlighted_date
        self.drawn = dict(diary.entries)
        self.rows = []
        options: list[Option] = []
        # Sorted by date, so each month's entries are already adjacent.
        for first_of_month, group in groupby(entries, key=lambda entry: entry.date.replace(day=1)):
            month = list(group)
            self.rows.append(None)
            options.append(heading_option(first_of_month, len(month)))
            for entry in month:
                self.rows.append(entry)
                options.append(entry_option(entry))
        listing.set_options(options)

        self.sub_title = "no entries" if not entries else count_entries(len(entries))

        has_entries = bool(entries)
        self.query_one("#entries-empty", Label).display = not has_entries
        listing.display = has_entries
        if has_entries:
            # Never left at 0: that is a month heading, and assigning a
            # highlight is not filtered by the skip-disabled rule that
            # cursor movement follows -- Enter would then open nothing.
            listing.highlighted = self.row_for(was_on)
            listing.focus()

    @property
    def entries_list(self) -> DayList:
        return self.query_one("#entries", DayList)

    @property
    def first_entry_row(self) -> int | None:
        """The row of the newest entry, past the heading it sits under."""
        return next((row for row, entry in enumerate(self.rows) if entry is not None), None)

    @property
    def last_entry_row(self) -> int | None:
        """The row of the oldest entry, at the bottom of the list."""
        return next(
            (row for row in reversed(range(len(self.rows))) if self.rows[row] is not None), None
        )

    @property
    def highlighted_date(self) -> dt.date | None:
        """The day the cursor is on, or None if it is not on an entry."""
        entry = self.selected_entry
        return None if entry is None else entry.date

    def row_for(self, date: dt.date | None) -> int | None:
        """The row to put the cursor on to leave the reader where they were.

        `date` is the day highlighted before the rebuild, or a day handed
        over to land on. Usually it has a row and the cursor simply lands
        on it -- returning from the editor should not cost someone their
        place halfway down a diary of years. When it has none, the nearest
        older day is the one to land on, and that holds for both ways a day
        can be missing: one just deleted, whose next older day has moved up
        into the space it left, which is where the eye already is; and a
        day the calendar was left on that was never written, whose nearest
        written neighbour is the row that stands in for it. Rows run newest
        first, so that is the first row not newer than `date`.
        """
        if date is None:
            return self.first_entry_row
        same_or_older = next(
            (
                row
                for row, entry in enumerate(self.rows)
                if entry is not None and entry.date <= date
            ),
            None,
        )
        # Nothing that old is left: the deleted day was the oldest one, so
        # the cursor was at the foot of the list and belongs there still.
        return self.last_entry_row if same_or_older is None else same_or_older

    def entry_at(self, row: int | None) -> Entry | None:
        """The entry a row shows, or None for a heading or a missing row."""
        if row is None or not 0 <= row < len(self.rows):
            return None
        return self.rows[row]

    @property
    def selected_entry(self) -> Entry | None:
        """The highlighted entry, or None when the list is empty."""
        return self.entry_at(self.entries_list.highlighted)

    def on_option_list_option_selected(self, event: DayList.OptionSelected) -> None:
        """Enter (or a click) on a row opens it."""
        entry = self.entry_at(event.option_index)
        if entry is not None:
            self.open_day(entry.date)

    # --- actions -----------------------------------------------------------

    def action_open_entry(self) -> None:
        entry = self.selected_entry
        if entry is not None:
            self.open_day(entry.date)

    def action_today(self) -> None:
        self.open_day(today())

    def action_another_day(self) -> None:
        """Write about a day other than today -- one you missed, or one you
        want to add to.

        The days already written go with the question: the modal marks
        them on its calendar, and it is this screen that has the diary
        open to be asked. A frozenset of the keys, so what the modal holds
        cannot drift from the diary or be changed by it.
        """
        self.app.push_screen(DatePromptScreen(written=self.written_days), self.open_chosen_day)

    def action_calendar(self) -> None:
        """Lay out the year, opening on the day the cursor is on here.

        The calendar is kept so that coming back lands on the day its own
        cursor was left on -- read in on_screen_resume, which is the one
        thing certain to run after it has gone and before the list is
        rebuilt.
        """
        self.calendar = CalendarScreen(self.highlighted_date)
        self.app.push_screen(self.calendar)

    def action_search(self) -> None:
        self.app.push_screen(SearchScreen())

    def action_settings(self) -> None:
        self.app.push_screen(SettingsScreen())

    def action_lock(self) -> None:
        """Put the diary away without leaving the app."""
        self.zecret.lock()

    def action_reload(self) -> None:
        """Pick up what another Zecret wrote.

        The way out of a refused save: once the file has changed underneath
        this session, every save is a conflict until the diary in memory is
        the one on disk again. Nothing is lost by doing it -- every save
        here is immediate, so there is no unsaved state to overwrite.
        """
        diary, key = self.zecret.unlocked
        try:
            reopened = DiaryFile.reopen(diary.path, key)
        except ZecretDecryptError:
            # A re-key elsewhere. The session's key opens nothing in the
            # file now, and the password to derive a new one was not kept.
            self.notify(RELOAD_REKEYED, severity="error")
            return
        except (OSError, ValueError) as error:
            detail = error.strerror if isinstance(error, OSError) and error.strerror else error
            # Not markup: the detail can quote the file, which is the very
            # thing this is reporting as damaged.
            self.notify(f"Could not re-read the diary: {detail}.", severity="error", markup=False)
            return

        self.zecret.diary = reopened
        self.notify(f"Reloaded — {count_entries(len(reopened.entries))}.")
        self.refresh_entries()

    def action_delete_entry(self) -> None:
        entry = self.selected_entry
        if entry is None:
            return
        question = f"Delete the entry for {format_day(entry.date)}? This cannot be undone."
        self.app.push_screen(ConfirmScreen(question), self.confirm_delete(entry))

    # --- getting around ----------------------------------------------------

    def action_cursor_down(self) -> None:
        """j, handed to the list, which already steps over headings."""
        self.entries_list.action_cursor_down()

    def action_cursor_up(self) -> None:
        self.entries_list.action_cursor_up()

    def action_page_down(self) -> None:
        self.move_cursor(self.page_rows)

    def action_page_up(self) -> None:
        self.move_cursor(-self.page_rows)

    def action_first_entry(self) -> None:
        self.move_cursor_to(self.first_entry_row)

    def action_last_entry(self) -> None:
        self.move_cursor_to(self.last_entry_row)

    @property
    def page_rows(self) -> int:
        """A screenful of lines, less one, so the jump keeps something in view."""
        return max(1, self.entries_list.scrollable_content_region.height - 1)

    def lines_of(self, row: int) -> int:
        """How many lines of the screen a row takes."""
        return HEADING_LINES if self.rows[row] is None else 1

    def move_cursor(self, lines: int) -> None:
        """Move the highlight about `lines` lines of the screen, landing on a day.

        Lines and not rows: a month heading is two lines tall, so a jump of
        a screenful of rows went further than a screenful -- and in a diary
        with a few days a month, where every third row is a heading, page
        down stepped clean over days that never once reached the screen.
        At least one row is always crossed, so a page key is never dead.

        Assigning an index is not filtered by the skip-disabled rule that
        arrow keys follow, so a jump that lands on a month heading has to
        walk off it -- onwards first, since that is the way the reader was
        already going.
        """
        here = self.entries_list.highlighted
        if here is None:
            return
        onwards = 1 if lines > 0 else -1
        target, travelled = here, 0
        while 0 <= target + onwards < len(self.rows):
            step = self.lines_of(target + onwards)
            if target != here and travelled + step > abs(lines):
                break
            target += onwards
            travelled += step
        landing = self.entry_row_from(target, onwards)
        if landing is None:
            # Ran out of list that way: the top of the diary is always a
            # heading, so paging up lands on one with nothing above it.
            landing = self.entry_row_from(target, -onwards)
        self.move_cursor_to(landing)

    def entry_row_from(self, row: int, step: int) -> int | None:
        """The first row from `row` in the `step` direction showing a day."""
        while 0 <= row < len(self.rows):
            if self.rows[row] is not None:
                return row
            row += step
        return None

    def move_cursor_to(self, row: int | None) -> None:
        """Highlight `row`, or do nothing when there is no day to go to."""
        if row is not None:
            self.entries_list.highlighted = row

    # --- helpers -----------------------------------------------------------

    def open_day(self, date: dt.date) -> None:
        """Open a day for writing. The editor decides whether that means a
        new entry or the existing one, and the list refreshes on resume to
        pick up the change -- and lands on the day, see on_screen_resume.
        """
        self.editing = date
        self.app.push_screen(EditorScreen(date))

    def open_chosen_day(self, date: dt.date | None) -> None:
        """Callback for DatePromptScreen; None means the user backed out."""
        if date is not None:
            self.open_day(date)

    def confirm_delete(self, entry: Entry) -> Callable[[Choice | None], None]:
        """Build the callback ConfirmScreen dismisses into.

        Two answers here, not three: the modal offers to save where there
        is something to save, and a deletion has no third road between
        going through with it and leaving the day alone.
        """

        def on_answered(choice: Choice | None) -> None:
            if choice is Choice.CONFIRM:
                self.delete_entry(entry)

        return on_answered

    def delete_entry(self, entry: Entry) -> None:
        """Remove the day's entry and persist immediately."""
        diary, key = self.zecret.unlocked
        diary.delete_entry(entry.date)
        try:
            diary.save(key)
        except (OSError, ZecretConflictError) as error:
            # The file still holds the entry, so put it back in memory too
            # rather than let the user believe the deletion stuck.
            diary.add_entry(entry)
            self.notify(save_error(error), severity="error", markup=False)
        self.refresh_entries()
