"""User preferences: small, non-secret, and kept out of the diary.

The diary file is for what you wrote. A theme is neither secret nor
writing, and it has to be known *before* the diary is unlocked -- the lock
screen is themed too -- so it cannot live inside a file that needs a
password to read. It gets its own plaintext JSON file instead:

    {"theme": "gruvbox"}

This is the one place besides storage.py that touches the filesystem, and
the one file Zecret writes in the clear. It may hold preferences and
nothing else: no entry text, no dates, no password, nothing derived from
the key. Anything that would tell a reader of this file something about
the diary's contents belongs in the diary.

Preferences are regenerable, so this module is forgiving where storage.py
is strict. A missing, unreadable, or malformed config falls back to
defaults rather than raising: a mangled preference must never be the
reason you cannot get to your diary. For the same reason the write is a
plain write rather than the atomic dance storage.py performs -- the worst
outcome is a file that fails to parse next launch and is replaced by
defaults.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

DEFAULT_CONFIG_PATH = Path.home() / ".zecret" / "config.json"

#: What the app uses until told otherwise, and the fallback for anything
#: unreadable. Matches Textual's own default theme.
DEFAULT_THEME = "textual-dark"

DIR_MODE = 0o700


@dataclass(slots=True)
class Config:
    """The user's preferences, and where they came from.

    Attributes:
        path: The file these were read from, and where save() writes back.
        theme: Name of the Textual theme to use. Not validated here --
            config.py has no opinion on which themes exist; the app checks
            the name against the themes actually registered and falls back
            if it does not know it.
    """

    path: Path
    theme: str = DEFAULT_THEME

    @classmethod
    def load(cls, path: Path) -> Self:
        """Read preferences from `path`, falling back to defaults.

        Never raises: a missing file is the normal first-run case, and a
        corrupt or unreadable one is treated the same way, since the diary
        must stay reachable regardless.
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
        return config

    def save(self) -> None:
        """Write preferences back to self.path, creating the directory.

        Raises:
            OSError: if the file cannot be written. The caller decides what
                to say about it -- the setting still applies to this
                session, it just will not outlive it.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
        self.path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    def to_dict(self) -> dict[str, Any]:
        """The JSON shape written to disk."""
        return {"theme": self.theme}
