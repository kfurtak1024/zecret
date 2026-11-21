"""User preferences: small, non-secret, and kept out of the diary.

The theme and the idle-lock wait both have to be known before the diary is
unlocked, so they live in their own plaintext JSON file:

    {"theme": "gruvbox", "lock_after_minutes": 15}

This is the one file Zecret writes in the clear. It may hold preferences
and nothing else: no entry text, no dates, no password, nothing derived
from the key.

Forgiving where storage.py is strict. A missing or malformed config falls
back to defaults, because a mangled preference must never be why someone
cannot reach their diary. The write is a plain one for the same reason:
the worst outcome is defaults at the next launch.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

DEFAULT_CONFIG_PATH = Path.home() / ".zecret" / "config.json"

#: The fallback for anything unreadable. Matches Textual's own default.
DEFAULT_THEME = "textual-dark"

#: Minutes of no activity before the diary locks itself. Zero turns it off.
DEFAULT_LOCK_AFTER_MINUTES = 15

DIR_MODE = 0o700


@dataclass(slots=True)
class Config:
    """The user's preferences, and where they came from.

    Attributes:
        path: The file these were read from, and where save() writes back.
        theme: Name of the Textual theme. Not validated here; the app
            checks it against the themes actually registered.
        lock_after_minutes: Minutes of inactivity before the diary locks,
            or 0 to never lock. Always a whole non-negative number.
    """

    path: Path
    theme: str = DEFAULT_THEME
    lock_after_minutes: int = DEFAULT_LOCK_AFTER_MINUTES

    @classmethod
    def load(cls, path: Path) -> Self:
        """Read preferences from `path`, falling back to defaults.

        Never raises: a missing, corrupt or unreadable file all mean
        defaults.
        """
        config = cls(path=path)
        try:
            document = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return config
        if not isinstance(document, dict):
            return config

        theme = document.get("theme")
        if isinstance(theme, str) and theme:
            config.theme = theme

        lock_after = document.get("lock_after_minutes")
        # bool is an int in Python. A negative wait would lock the diary the
        # instant it opened, so it falls back rather than being clamped.
        if isinstance(lock_after, int) and not isinstance(lock_after, bool) and lock_after >= 0:
            config.lock_after_minutes = lock_after
        return config

    def save(self) -> None:
        """Write preferences back to self.path, creating the directory.

        Raises:
            OSError: if the file cannot be written. The setting still
                applies to this session.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
        self.path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    def to_dict(self) -> dict[str, Any]:
        """The JSON shape written to disk."""
        return {"theme": self.theme, "lock_after_minutes": self.lock_after_minutes}
