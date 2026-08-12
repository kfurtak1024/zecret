"""Data model for diary entries.

Deliberately minimal per project scope: title, body, and timestamps.
No tags, mood, or attachments (may be revisited in a future version).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Self
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class Entry:
    """A single diary entry.

    Frozen: entries are immutable, and edits go through edited(), which
    returns a new instance. storage.py relies on this -- it holds entry
    references to detect which ones changed since the last save, which
    in-place mutation would defeat.

    Attributes:
        id: Stable unique identifier, generated once at creation and never
            reused. Used to locate the entry's record for edit/delete.
        title: Short entry title, shown in the entry list.
        body: Full entry text (multi-line).
        created_at: UTC timestamp when the entry was first created.
        updated_at: UTC timestamp of the most recent edit. Equal to
            created_at until the entry is edited.
    """

    id: UUID
    title: str
    body: str
    created_at: datetime
    updated_at: datetime = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        """Default updated_at to created_at for a never-edited entry.

        object.__setattr__ because the dataclass is frozen; this runs during
        construction, before the instance is handed to anyone.
        """
        if self.updated_at is None:
            object.__setattr__(self, "updated_at", self.created_at)

    @classmethod
    def new(cls, title: str, body: str) -> Self:
        """Construct a brand-new Entry with a fresh id and current timestamps."""
        now = datetime.now(UTC)
        return cls(id=uuid4(), title=title, body=body, created_at=now, updated_at=now)

    def edited(self, *, title: str | None = None, body: str | None = None) -> Self:
        """Return a new Entry with title/body updated and updated_at refreshed.

        Entry is treated as immutable; edits produce a new instance rather
        than mutating in place, matching how storage.py rewrites records.

        The id and created_at are carried over unchanged: an edit must stay
        the same entry so storage.py replaces its record rather than adding
        a second one. Fields left as None keep their current value.
        """
        return replace(
            self,
            title=self.title if title is None else title,
            body=self.body if body is None else body,
            updated_at=datetime.now(UTC),
        )

    def to_json_bytes(self) -> bytes:
        """Serialize to UTF-8 JSON bytes, ready for crypto.encrypt().

        Timestamps are ISO 8601 (microsecond precision preserved) and the
        id is its canonical string form, so from_json_bytes() reconstructs
        an equal Entry.
        """
        payload = {
            "id": str(self.id),
            "title": self.title,
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
                id=UUID(payload["id"]),
                title=payload["title"],
                body=payload["body"],
                created_at=datetime.fromisoformat(payload["created_at"]),
                updated_at=datetime.fromisoformat(payload["updated_at"]),
            )
        except (AttributeError, KeyError, TypeError, UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"malformed entry payload: {exc}") from exc
