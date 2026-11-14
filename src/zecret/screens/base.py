"""Shared base classes, wording and formatting for Zecret's screens.

- ZecretScreen: typed access to the app, and with it the rule that screens
  reach the diary only through the app. Also deleting a day, which the
  list and the calendar both offer.
- FormScreen: one error line, password advice, and emptying the fields
  after a rejected attempt.
- DayList: the list of days the entry list and search both use.
- card(), plain(), day_row(): how a panel is built and how text Zecret did
  not write is handed to Textual.
- Date and snippet formatting, and the wording every screen shares for a
  refused save, a failed re-read, unsaved changes and a forgotten password.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import TYPE_CHECKING, ClassVar, cast

from textual.containers import VerticalScroll
from textual.content import Content
from textual.screen import Screen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from zecret.models import Entry
from zecret.storage import ZecretConflictError
from zecret.strength import NEEDS_HELP, rate

if TYPE_CHECKING:
    from zecret.app import ZecretApp

EMPTY_BODY = "(empty)"

#: A save refused because the file changed underneath this session.
DIARY_CHANGED = "The diary changed on disk — another Zecret may have it open."

#: Said wherever a password is chosen: creating the diary, and changing it.
NO_RECOVERY = (
    "Forget your master password and the diary is gone — there is no "
    "recovery and no back door, not even for you."
)

#: Said when leaving would lose what is on the screen, whether by backing
#: out of the day or by quitting. A statement rather than a question: with
#: three answers on offer, a question would pull for one of them.
UNSAVED_CHANGES = "Your changes to this day are not saved."

#: The most of an entry's first line a row will carry. Not a display width:
#: the terminal trims rows at render time (`text-overflow: ellipsis` in
#: app.tcss). This only guards against one huge pasted line.
SNIPPET_CAP = 500


def today() -> dt.date:
    """The local calendar day: an entry written at 23:50 belongs to the day
    the writer would name."""
    return dt.datetime.now().date()


def format_day(date: dt.date) -> str:
    """A day in full, fixed width: 'Thu 13 Aug 2026'."""
    return f"{date:%a %d %b %Y}"


def format_day_short(date: dt.date) -> str:
    """A day within a month that is already named above it: 'Thu 13'."""
    return f"{date:%a %d}"


def format_month(date: dt.date) -> str:
    """The month a day falls in, with its year: 'August 2026'."""
    return f"{date:%B %Y}"


def count_entries(count: int) -> str:
    """'1 entry' / '12 entries'."""
    return f"{count} entr{'y' if count == 1 else 'ies'}"


def format_day_long(date: dt.date) -> str:
    """A day in heading form: 'Thursday, 13 August 2026'."""
    return f"{date:%A, %d %B %Y}"


def body_snippet(body: str, length: int = SNIPPET_CAP) -> str:
    """The entry's first non-blank line, capped at `length`.

    What tells one day from another in a list, there being no titles.
    Scanned a line at a time rather than with splitlines(), which would
    copy the whole body to reach its first line.
    """
    start = 0
    while start < len(body):
        end = body.find("\n", start)
        if end == -1:
            end = len(body)
        first = body[start:end].strip()
        if first:
            if len(first) <= length:
                return first
            return f"{first[: length - 1].rstrip()}…"
        start = end + 1
    return EMPTY_BODY


def entry_summary(entry: Entry) -> str:
    """One-line label for an entry standing on its own (search results)."""
    return f"{format_day(entry.date)}   {body_snippet(entry.body)}"


def day_summary(entry: Entry) -> str:
    """One-line label for an entry under a month heading."""
    return f"{format_day_short(entry.date)}   {body_snippet(entry.body)}"


def unchanged(drawn: Mapping[dt.date, Entry] | None, entries: Mapping[dt.date, Entry]) -> bool:
    """Whether `entries` is still exactly the diary a list was drawn from.

    By identity, not value: Entry is frozen and every edit makes a new
    one, so the check never reads an entry's text. A reload builds new
    objects and always counts as a change. `drawn` is None until a list
    has been drawn.
    """
    if drawn is None or drawn.keys() != entries.keys():
        return False
    return all(drawn[date] is entry for date, entry in entries.items())


def save_error(error: OSError | ZecretConflictError) -> str:
    """What to tell the user about a save that did not happen."""
    if isinstance(error, ZecretConflictError):
        return DIARY_CHANGED
    # strerror is None for an OSError raised without an errno.
    return f"Could not save: {error.strerror or error}."


def reread_error(error: OSError | ValueError) -> str:
    """What to tell the user about a re-read of the diary that failed.

    A re-read that fails for the key (ZecretDecryptError) is
    REKEYED_ELSEWHERE instead.
    """
    detail = error.strerror if isinstance(error, OSError) and error.strerror else error
    return f"Could not re-read the diary: {detail}."


#: The diary on disk no longer opens with this session's key: another
#: Zecret changed the password.
REKEYED_ELSEWHERE = "The password was changed elsewhere. Quit and unlock again."


def delete_question(date: dt.date) -> str:
    """What to ask before a day's entry is deleted, wherever it is asked."""
    return f"Delete the entry for {format_day(date)}? This cannot be undone."


def card(id: str) -> VerticalScroll:
    """The scrolling panel a screen's content sits in, out of the tab order.

    Textual makes a scrollable container focusable. On a form that is an
    empty stop on the tab ring: tab past the last field and the focus ring
    disappears. Scrolling is not lost, since Textual keeps the focused
    field in view.

    HelpScreen builds its own panel and keeps it focusable: it has no
    fields, and focusing the panel is what the arrow keys scroll with.
    """
    return VerticalScroll(id=id, can_focus=False)


def plain(text: str) -> Content:
    """`text` exactly as it is, never read as markup.

    Textual parses a plain string handed to a Label, an Option or a
    notification as markup, and a stray closing tag raises MarkupError.
    Anything Zecret did not write (entry text, paths, OS errors, text
    quoting the diary file) goes through here.
    """
    return Content(text)


def day_row(text: str) -> Option:
    """One row of a DayList, as plain text."""
    return Option(plain(text))


class DayList(OptionList):
    """A list of days that stops at its ends instead of wrapping.

    Textual's OptionList wraps: down on the last option goes to the first,
    which in a diary of years is an unannounced jump across all of them.
    The screens handle the page keys and the ends themselves.
    """

    def scroll_to_highlight(self, top: bool = False) -> None:
        """Bring the highlight into view, and on the first day, the top.

        Textual scrolls just far enough to show the row, which on the
        newest entry leaves its month heading out of sight.
        """
        highlighted = self.highlighted
        if highlighted is not None and all(
            self.get_option_at_index(index).disabled for index in range(highlighted)
        ):
            self.scroll_home(animate=False, immediate=True)
            return
        super().scroll_to_highlight(top)

    def action_cursor_up(self) -> None:
        self._step(-1)

    def action_cursor_down(self) -> None:
        self._step(1)

    def _step(self, direction: int) -> None:
        """Highlight the next enabled option that way, or stay put."""
        if self.highlighted is None:
            return
        index = self.highlighted + direction
        while 0 <= index < self.option_count:
            if not self.get_option_at_index(index).disabled:
                self.highlighted = index
                return
            index += direction


class ZecretScreen(Screen[None]):
    """A screen with typed access to the running Zecret app."""

    #: Textual's first-focusable guess, switched off: every screen says
    #: what it opens focused on in on_mount. The guess runs first and
    #: focusing scrolls the widget into view, which opened Settings one
    #: section down. Empty string rather than None, which Textual reads as
    #: "ask the app" (whose default is "*").
    AUTO_FOCUS: ClassVar[str | None] = ""

    @property
    def zecret(self) -> ZecretApp:
        """The running app, typed."""
        return cast("ZecretApp", self.app)

    @property
    def written_days(self) -> frozenset[dt.date]:
        """Every day the diary holds an entry for, as of now.

        What the calendars mark. Handed to a calendar, never looked up by
        it: widgets do not reach for storage.
        """
        diary, _ = self.zecret.unlocked
        return frozenset(diary.entries)

    #: Whether this screen is part way through something that must finish
    #: before the diary can lock (re-encrypting under a new password). A
    #: lock asked for meanwhile waits; see ZecretApp.action_lock.
    working = False

    @property
    def blocks_lock(self) -> bool:
        """Whether locking now would throw away something not yet saved.

        Only the editor overrides this. The idle timer asks every screen
        on the stack before it locks.
        """
        return False

    def save_pending(self) -> bool:
        """Persist what blocks_lock is holding, and say whether it landed.

        False means the save did not happen and the caller should stay
        put; the screen has said why on its own error line.
        """
        return True

    def delete_day(self, date: dt.date) -> None:
        """Remove the day's entry, save at once, and say which happened.

        If the save fails, saving() puts the entry back in memory. The
        calling screen redraws afterwards either way.
        """
        diary, key = self.zecret.unlocked
        try:
            with diary.saving(key):
                diary.delete_entry(date)
        except (OSError, ZecretConflictError) as error:
            self.notify(save_error(error), severity="error", markup=False)
            return
        self.notify(f"Deleted the entry for {format_day(date)}.", markup=False)


class FormScreen(ZecretScreen):
    """A screen with fields to fill in and one line to say what went wrong.

    PasswordScreen inherits this together with ModalScreen[None], which
    only works because it dismisses nothing. A modal that returns a value
    (DatePromptScreen) is a Screen of another type and cannot.
    """

    #: The id of the Label this screen writes its errors into.
    ERROR_ID: ClassVar[str]

    def set_error(self, message: str) -> None:
        """Show `message` on the error line, or clear it when empty.

        Takes the line back from any advice or status on it.
        """
        line = self.query_one(f"#{self.ERROR_ID}", Label)
        line.remove_class("-advice", "-advice-strong", "-status")
        line.update(plain(message))

    def set_status(self, message: str) -> None:
        """Say what the screen is busy with, on the row errors use.

        Styled by its own class: nothing has gone wrong.
        """
        line = self.query_one(f"#{self.ERROR_ID}", Label)
        line.remove_class("-advice", "-advice-strong")
        line.add_class("-status")
        line.update(message)

    def advise_on_password(self, password: str) -> None:
        """Show how strong a password being chosen is, without refusing it.

        Written on the error row, which is one fixed line: the password
        dialog is sized to fit a 24-row terminal and has no row to spare.
        The row's measured width goes to rate(), so advice that would be
        cut off is shortened instead.

        The `-advice` class is styling and bookkeeping at once. It marks
        the line as withdrawable, so clearing the reading cannot clear an
        error put there just before a rejected attempt emptied the fields.
        """
        line = self.query_one(f"#{self.ERROR_ID}", Label)
        strength = rate(password, max(line.content_region.width, 0))
        if strength is None:
            if line.has_class("-advice"):
                line.remove_class("-advice", "-advice-strong")
                line.update("")
            return
        line.add_class("-advice")
        line.set_class(strength.score > NEEDS_HELP, "-advice-strong")
        line.update(plain(strength.line()))

    def clear_inputs(self) -> None:
        """Empty every text field, so a rejected password does not sit in
        a widget on an unattended terminal."""
        for widget in self.query(Input):
            widget.value = ""

    def advance(self, submitted: Input) -> bool:
        """Move to a field still empty, if Enter came early; say if so.

        Enter in a filled field moves to the next empty one, looking after
        this field and then before it, and the form submits only once none
        is empty. An empty field itself submits, so the error says what is
        missing.
        """
        if not submitted.value:
            return False
        fields = list(self.query(Input))
        at = fields.index(submitted)
        for field in fields[at + 1 :] + fields[:at]:
            if not field.value:
                field.focus()
                return True
        return False
