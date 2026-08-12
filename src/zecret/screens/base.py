"""Shared base class for Zecret's screens.

Textual types `self.app` as the generic `App`, so every screen would
otherwise repeat the same cast to reach `diary_path`, `diary` and `key`.
This keeps that in one place, and with it the rule from CLAUDE.md that
screens reach the diary only through the app -- never through crypto.py or
the filesystem directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual.screen import Screen

from zecret.models import Entry

if TYPE_CHECKING:
    from zecret.app import ZecretApp

UNTITLED = "(untitled)"


def entry_summary(entry: Entry) -> str:
    """One-line label for an entry: local timestamp then title.

    Shared by the entry list and search results so a given entry looks the
    same wherever it appears.
    """
    # Stored as UTC; shown in the reader's own timezone.
    when = entry.created_at.astimezone().strftime("%Y-%m-%d %H:%M")
    return f"{when}  {entry.title or UNTITLED}"


class ZecretScreen(Screen[None]):
    """A screen with typed access to the running Zecret app."""

    @property
    def zecret(self) -> ZecretApp:
        """The running app, typed -- `self.app` is only known as App here."""
        return cast("ZecretApp", self.app)
