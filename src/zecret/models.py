"""Data model for diary entries.

One entry per calendar day: the date is the entry's identity, so there is
no id and no title. A body and two timestamps, nothing else.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field, replace
from typing import Self


@dataclass(frozen=True, slots=True)
class Entry:
    """A single day's diary entry.

    Frozen: an edit goes through edited(), which returns a new instance.
    storage.py relies on that to tell which entries changed since the last
    save.

    Attributes:
        date: The local calendar day this entry belongs to, and its
            identity. Stored without a timezone, so entries do not shift
            when the writer travels.
        body: The entry text (multi-line).
        created_at: UTC timestamp of the first write. Distinct from `date`:
            Tuesday's entry may be written on Friday.
        updated_at: UTC timestamp of the most recent edit. Equal to
            created_at until the entry is edited.
    """

    date: dt.date
    # Out of the repr, which is what a traceback or a debugger prints. See
    # ZecretApp._fatal_error.
    body: str = field(repr=False)
    created_at: dt.datetime
    # None only until __post_init__ replaces it, so it is annotated as the
    # datetime every reader sees.
    updated_at: dt.datetime = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        """Default updated_at to created_at for a never-edited entry."""
        if self.updated_at is None:
            object.__setattr__(self, "updated_at", self.created_at)

    @classmethod
    def new(cls, date: dt.date, body: str) -> Self:
        """Construct a brand-new Entry for `date` with current timestamps."""
        now = dt.datetime.now(dt.UTC)
        return cls(date=date, body=body, created_at=now, updated_at=now)

    def edited(self, body: str) -> Self:
        """Return a new Entry with `body` replaced and updated_at refreshed.

        The date and created_at carry over. Moving an entry to another day
        is not an edit and is deliberately not expressible.
        """
        return replace(self, body=body, updated_at=dt.datetime.now(dt.UTC))

    def to_json_bytes(self) -> bytes:
        """Serialize to UTF-8 JSON bytes, ready for crypto.encrypt().

        ISO 8601 throughout, with microseconds kept, so from_json_bytes()
        reconstructs an equal Entry.
        """
        payload = {
            "date": self.date.isoformat(),
            "body": self.body,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")

    @classmethod
    def from_json_bytes(cls, data: bytes) -> Self:
        """Reconstruct an Entry from decrypted JSON bytes.

        Raises:
            ValueError: if the JSON is malformed, or a field is missing,
                unparseable or of the wrong type.
        """
        try:
            payload = json.loads(data.decode("utf-8"))
            body = payload["body"]
            if not isinstance(body, str):
                raise TypeError(f"body must be text, got {type(body).__name__}")
            return cls(
                date=dt.date.fromisoformat(payload["date"]),
                body=body,
                created_at=dt.datetime.fromisoformat(payload["created_at"]),
                updated_at=dt.datetime.fromisoformat(payload["updated_at"]),
            )
        except (AttributeError, KeyError, TypeError, UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"malformed entry payload: {exc}") from exc
