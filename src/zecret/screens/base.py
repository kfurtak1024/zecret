"""Shared base class and formatting helpers for Zecret's screens.

Textual types `self.app` as the generic `App`, so every screen would
otherwise repeat the same cast to reach `diary_path`, `diary` and `key`.
This keeps that in one place, and with it the rule from CLAUDE.md that
screens reach the diary only through the app -- never through crypto.py or
the filesystem directly.

The date helpers live here too: a diary is one entry per day, so how a day
is worded is a decision every screen shares, and "which day is today" is a
question only this layer asks (models.py takes the date it is given).
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, cast

from textual.screen import Screen

from zecret.models import Entry

if TYPE_CHECKING:
    from zecret.app import ZecretApp

EMPTY_BODY = "(empty)"

#: How much of an entry's first line the list shows before trimming.
SNIPPET_LENGTH = 60


def today() -> dt.date:
    """The local calendar day, which is the day a diary entry means.

    Local rather than UTC: an entry written at 23:50 belongs to the day
    the writer would name, not to tomorrow.
    """
    return dt.datetime.now().date()


def format_day(date: dt.date) -> str:
    """A day in list form: 'Thu 13 Aug 2026'.

    Fixed width, so the dates line up as a column down the entry list.
    """
    return f"{date:%a %d %b %Y}"


def format_day_long(date: dt.date) -> str:
    """A day in heading form: 'Thursday, 13 August 2026'."""
    return f"{date:%A, %d %B %Y}"


def body_snippet(body: str, length: int = SNIPPET_LENGTH) -> str:
    """The entry's first non-blank line, trimmed to `length`.

    With no titles, this is what tells one day apart from another in a
    list -- the diary equivalent of a subject line.
    """
    first = next((line.strip() for line in body.splitlines() if line.strip()), "")
    if not first:
        return EMPTY_BODY
    if len(first) <= length:
        return first
    return f"{first[: length - 1].rstrip()}…"


def entry_summary(entry: Entry) -> str:
    """One-line label for an entry: its day, then a glimpse of the text.

    Shared by the entry list and search results so a given entry looks the
    same wherever it appears.
    """
    return f"{format_day(entry.date)}   {body_snippet(entry.body)}"


class ZecretScreen(Screen[None]):
    """A screen with typed access to the running Zecret app."""

    @property
    def zecret(self) -> ZecretApp:
        """The running app, typed -- `self.app` is only known as App here."""
        return cast("ZecretApp", self.app)
