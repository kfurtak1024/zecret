"""Shared base classes and formatting helpers for Zecret's screens.

Textual types `self.app` as the generic `App`, so every screen would
otherwise repeat the same cast to reach `diary_path`, `diary` and `key`.
ZecretScreen keeps that in one place, and with it the rule from CLAUDE.md
that screens reach the diary only through the app -- never through
crypto.py or the filesystem directly. FormScreen adds what the screens
with fields to fill in all need: one error line, and a way to empty the
fields after a rejected attempt.

The date helpers live here too: a diary is one entry per day, so how a day
is worded is a decision every screen shares, and "which day is today" is a
question only this layer asks (models.py takes the date it is given).

And the warning about a forgotten password, which the two screens that
set one both carry, and which must say the same thing on both.

And the wording for a save that did not happen, which is the same wherever
a save is attempted -- three screens attempt one, and none of them should
be deciding for itself how to describe a diary that changed underneath it.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, ClassVar, cast

from textual.screen import Screen
from textual.widgets import Input, Label

from zecret.models import Entry
from zecret.storage import ZecretConflictError

if TYPE_CHECKING:
    from zecret.app import ZecretApp

EMPTY_BODY = "(empty)"

#: Shared wording for a refused save: the cause is the same wherever it
#: happens, and each screen adds what it means for what you were doing.
DIARY_CHANGED = "The diary changed on disk — another Zecret may have it open."

#: Said wherever a password is being chosen: creating the diary, and
#: changing it later. One sentence rather than two, because it is one fact
#: and someone meeting it the second time should recognise it from the
#: first -- which is also why it lives here rather than being worded twice.
#:
#: It was already on both screens, in the muted grey the hints are written
#: in, where the one line with no way back read like the rest of the small
#: print. What changed is the weight it is given, not what it says.
NO_RECOVERY = (
    "Forget your master password and the diary is gone — there is no "
    "recovery and no back door, not even for you."
)

#: Said when leaving would lose what is on the screen. One sentence for
#: both ways of leaving -- backing out of the day and quitting the app --
#: because it is one situation, and the buttons underneath are where the
#: two differ. Stated rather than asked: with three answers on offer, a
#: question would be pulling for one of them.
UNSAVED_CHANGES = "Your changes to this day are not saved."

#: The most of an entry's first line a row will ever carry. Not a display
#: width: how much of a row is shown is the terminal's business, decided at
#: render time by `text-overflow: ellipsis` in app.tcss, so a wide window
#: shows more of the line and a narrow one trims it with no work here and
#: nothing to recompute when the window changes size.
#:
#: This is the cap behind that -- what stops one pasted paragraph with no
#: newline in it from putting fifty kilobytes into a label that then throws
#: nearly all of it away. Far past any terminal's width, so it never cuts a
#: line someone could otherwise have read.
SNIPPET_CAP = 500


def today() -> dt.date:
    """The local calendar day, which is the day a diary entry means.

    Local rather than UTC: an entry written at 23:50 belongs to the day
    the writer would name, not to tomorrow.
    """
    return dt.datetime.now().date()


def format_day(date: dt.date) -> str:
    """A day in full: 'Thu 13 Aug 2026'.

    Fixed width, so the dates line up as a column. Used where a row stands
    on its own -- search results, which are not grouped by month.
    """
    return f"{date:%a %d %b %Y}"


def format_day_short(date: dt.date) -> str:
    """A day within a month that is already named above it: 'Thu 13'."""
    return f"{date:%a %d}"


def format_month(date: dt.date) -> str:
    """The month a day falls in: 'August 2026'.

    Carries the year, so grouping the diary by month needs only one level
    of heading rather than a year above a month.
    """
    return f"{date:%B %Y}"


def count_entries(count: int) -> str:
    """'1 entry' / '12 entries', for headings and the header's subtitle."""
    return f"{count} entr{'y' if count == 1 else 'ies'}"


def format_day_long(date: dt.date) -> str:
    """A day in heading form: 'Thursday, 13 August 2026'."""
    return f"{date:%A, %d %B %Y}"


def body_snippet(body: str, length: int = SNIPPET_CAP) -> str:
    """The entry's first non-blank line, capped at `length`.

    With no titles, this is what tells one day apart from another in a
    list -- the diary equivalent of a subject line. The row is given the
    whole line and the terminal decides how much of it fits; `length` is a
    guard against a pathological line, not the width of anything.

    Scanned a line at a time rather than with splitlines(), which copies
    the entire body to get at its first line. That costs about six
    microseconds an entry on a long one against a tenth of that here --
    real, but a rounding error next to the cost of mounting the rows, so
    this is written the cheap way because there is no reason to write it
    the expensive way, not because it was ever the slow part.
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
    """One-line label for an entry standing on its own: full day, then a
    glimpse of the text. Used by search, whose results are ungrouped."""
    return f"{format_day(entry.date)}   {body_snippet(entry.body)}"


def day_summary(entry: Entry) -> str:
    """One-line label for an entry under a month heading, which already
    says which month and year this is."""
    return f"{format_day_short(entry.date)}   {body_snippet(entry.body)}"


def save_error(error: OSError | ZecretConflictError) -> str:
    """What to tell the user about a save that did not happen.

    Every screen that saves catches the same two things and has to say the
    same two things about them, so the wording lives here rather than in
    three copies that would drift. What each screen adds around this is
    what the failure cost *there* -- an entry not written, a password not
    changed -- which is the part that genuinely differs.
    """
    if isinstance(error, ZecretConflictError):
        return DIARY_CHANGED
    # strerror is None for an OSError raised without an errno, which the
    # tests do; falling back to the exception keeps the message readable.
    return f"Could not save: {error.strerror or error}."


class ZecretScreen(Screen[None]):
    """A screen with typed access to the running Zecret app."""

    @property
    def zecret(self) -> ZecretApp:
        """The running app, typed -- `self.app` is only known as App here."""
        return cast("ZecretApp", self.app)

    @property
    def blocks_lock(self) -> bool:
        """Whether locking now would throw away something not yet saved.

        Almost nothing does: every save in Zecret is immediate, so most
        screens have nothing to lose. The editor is the exception, and says
        so by overriding this. The idle timer asks every screen on the
        stack before it locks.
        """
        return False

    def save_pending(self) -> bool:
        """Persist what blocks_lock is holding, and say whether it landed.

        The other half of blocks_lock: a screen that claims to be holding
        something unsaved has to be able to save it on request, which is
        what answering "save first" to the quit question calls. False
        means the save did not happen and whoever asked should stay put --
        the screen has already said why on its own error line.

        A screen with nothing to lose has nothing to do here, and saying
        it succeeded is the truth for it.
        """
        return True


class FormScreen(ZecretScreen):
    """A screen with fields to fill in and one line to say what went wrong.

    Names the error label rather than each screen repeating the query for
    it. Deliberately not extended to DatePromptScreen, which has an error
    line of its own shape: it is a ModalScreen returning a date, so it
    cannot inherit Screen[None], and reaching it would need a mixin that
    fights both the type system and Textual's widget hierarchy for the sake
    of one two-line method.
    """

    #: The id of the Label this screen writes its errors into.
    ERROR_ID: ClassVar[str]

    def set_error(self, message: str) -> None:
        """Show `message` on the error line, or clear it when empty."""
        self.query_one(f"#{self.ERROR_ID}", Label).update(message)

    def clear_inputs(self) -> None:
        """Empty every text field.

        Used after a rejected attempt: a password left sitting in a widget
        on an unattended terminal costs more than retyping one does.
        """
        for widget in self.query(Input):
            widget.value = ""
