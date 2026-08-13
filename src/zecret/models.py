"""Data model for diary entries.

One entry per calendar day: the date *is* the entry's identity, so there is
no separate id and no title -- the day names the entry. Deliberately minimal
per project scope: a body and timestamps. No tags, mood, or attachments.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field, replace
from typing import Self


@dataclass(frozen=True, slots=True)
class Entry:
    """A single day's diary entry.

    Frozen: entries are immutable, and edits go through edited(), which
    returns a new instance. storage.py relies on this -- it holds entry
    references to detect which ones changed since the last save, which
    in-place mutation would defeat.

    Attributes:
        date: The calendar day this entry belongs to, and its identity: a
            diary holds at most one entry per date. Local (the day the
            writer would name), and stored without a timezone, so entries
            do not shift around when the writer travels.
        body: The entry text (multi-line).
        created_at: UTC timestamp when the day's entry was first written.
            Distinct from `date`: a Tuesday entry may be backfilled on
            Friday, and the diary shows it under Tuesday either way.
        updated_at: UTC timestamp of the most recent edit. Equal to
            created_at until the entry is edited.
    """

    date: dt.date
    body: str
    created_at: dt.datetime
    updated_at: dt.datetime = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        """Default updated_at to created_at for a never-edited entry.

        object.__setattr__ because the dataclass is frozen; this runs during
        construction, before the instance is handed to anyone.
        """
        if self.updated_at is None:
            object.__setattr__(self, "updated_at", self.created_at)

    @classmethod
    def new(cls, date: dt.date, body: str) -> Self:
        """Construct a brand-new Entry for `date` with current timestamps."""
        now = dt.datetime.now(dt.UTC)
        return cls(date=date, body=body, created_at=now, updated_at=now)

    def edited(self, body: str) -> Self:
        """Return a new Entry with `body` replaced and updated_at refreshed.

        Entry is treated as immutable; edits produce a new instance rather
        than mutating in place, matching how storage.py rewrites records.

        The date and created_at are carried over unchanged: an edit must
        stay the same entry so storage.py replaces its record rather than
        adding a second one. Moving an entry to a different day is not an
        edit -- it would collide with whatever already lives there -- so it
        is deliberately not expressible here.
        """
        return replace(self, body=body, updated_at=dt.datetime.now(dt.UTC))

    def to_json_bytes(self) -> bytes:
        """Serialize to UTF-8 JSON bytes, ready for crypto.encrypt().

        The date is ISO 8601 (YYYY-MM-DD) and timestamps are ISO 8601 with
        microsecond precision preserved, so from_json_bytes() reconstructs
        an equal Entry.
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
            ValueError: if the JSON is malformed or a field is missing or
                unparseable. Decryption already authenticated these bytes,
                so this indicates a version/format problem rather than
                tampering -- either way it must not produce a half-built
                Entry.
        """
        try:
            payload = json.loads(data.decode("utf-8"))
            return cls(
                date=dt.date.fromisoformat(payload["date"]),
                body=payload["body"],
                created_at=dt.datetime.fromisoformat(payload["created_at"]),
                updated_at=dt.datetime.fromisoformat(payload["updated_at"]),
            )
        except (AttributeError, KeyError, TypeError, UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"malformed entry payload: {exc}") from exc
