"""Tests for zecret.models.

Required coverage (fill in as models.py is implemented):
    - Entry.new() sets created_at == updated_at and generates a unique id.
    - entry.edited() returns a NEW Entry instance (original untouched),
      with updated_at refreshed and later than created_at.
    - to_json_bytes() / from_json_bytes() round-trips an Entry exactly,
      including datetime precision and UUID equality.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from zecret.models import Entry


@pytest.fixture
def entry() -> Entry:
    return Entry.new("A title", "A body\nwith two lines")


# --- Entry.new() -----------------------------------------------------------


def test_new_sets_created_at_equal_to_updated_at(entry):
    assert entry.created_at == entry.updated_at


def test_new_generates_unique_ids():
    ids = {Entry.new("t", "b").id for _ in range(100)}
    assert len(ids) == 100, "each new entry must get its own id"


def test_new_id_is_a_uuid(entry):
    assert isinstance(entry.id, UUID)


def test_new_stores_title_and_body(entry):
    assert entry.title == "A title"
    assert entry.body == "A body\nwith two lines"


def test_new_timestamps_are_utc_aware(entry):
    """Naive datetimes would compare unpredictably across DST and would
    break sorting in the entry list."""
    assert entry.created_at.tzinfo is not None
    assert entry.created_at.utcoffset() == timedelta(0)


def test_new_timestamp_is_current(entry):
    assert abs(datetime.now(UTC) - entry.created_at) < timedelta(seconds=5)


def test_updated_at_defaults_to_created_at_when_omitted():
    """Direct construction (as storage.py does when loading) must not leave
    updated_at as None."""
    created = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    constructed = Entry(id=uuid4(), title="t", body="b", created_at=created)
    assert constructed.updated_at == created


# --- immutability ----------------------------------------------------------


@pytest.mark.parametrize("attribute", ["id", "title", "body", "created_at", "updated_at"])
def test_entry_is_immutable(entry, attribute):
    """storage.py detects edits by comparing entry references across a save,
    so an entry mutated in place would be persisted inconsistently -- or
    silently not at all. Frozen makes that unrepresentable."""
    with pytest.raises(AttributeError):
        setattr(entry, attribute, "mutated")


def test_entry_is_hashable(entry):
    """Follows from frozen, and lets entries go in sets/dict keys."""
    assert {entry, entry} == {entry}


# --- Entry.edited() --------------------------------------------------------


def test_edited_returns_a_new_instance(entry):
    assert entry.edited(title="New") is not entry


def test_edited_leaves_the_original_untouched(entry):
    before = (entry.title, entry.body, entry.created_at, entry.updated_at)
    entry.edited(title="New title", body="New body")
    assert (entry.title, entry.body, entry.created_at, entry.updated_at) == before


def test_edited_refreshes_updated_at_to_later_than_created_at(entry):
    time.sleep(0.001)
    assert entry.edited(title="New title").updated_at > entry.created_at


def test_edited_preserves_id_and_created_at(entry):
    """An edit is the same entry -- storage.py replaces its record by id, so
    a changed id would silently duplicate the entry instead."""
    edited = entry.edited(title="New title", body="New body")
    assert edited.id == entry.id
    assert edited.created_at == entry.created_at


def test_edited_updates_title_and_body(entry):
    edited = entry.edited(title="New title", body="New body")
    assert edited.title == "New title"
    assert edited.body == "New body"


def test_edited_with_only_title_keeps_body(entry):
    edited = entry.edited(title="New title")
    assert edited.title == "New title"
    assert edited.body == entry.body


def test_edited_with_only_body_keeps_title(entry):
    edited = entry.edited(body="New body")
    assert edited.title == entry.title
    assert edited.body == "New body"


def test_edited_with_no_arguments_only_touches_updated_at(entry):
    time.sleep(0.001)
    edited = entry.edited()
    assert (edited.id, edited.title, edited.body, edited.created_at) == (
        entry.id,
        entry.title,
        entry.body,
        entry.created_at,
    )
    assert edited.updated_at > entry.updated_at


def test_edited_can_set_empty_strings(entry):
    """Empty string is a real value, not 'unchanged' -- only None means
    'leave this field alone'."""
    edited = entry.edited(title="", body="")
    assert edited.title == ""
    assert edited.body == ""


def test_edited_is_chainable(entry):
    time.sleep(0.001)
    once = entry.edited(title="First edit")
    time.sleep(0.001)
    twice = once.edited(title="Second edit")
    assert twice.title == "Second edit"
    assert twice.id == entry.id
    assert twice.created_at == entry.created_at
    assert twice.updated_at > once.updated_at


# --- JSON round-trip -------------------------------------------------------


def test_json_round_trip_is_exact(entry):
    assert Entry.from_json_bytes(entry.to_json_bytes()) == entry


def test_json_round_trip_preserves_uuid_equality(entry):
    restored = Entry.from_json_bytes(entry.to_json_bytes())
    assert isinstance(restored.id, UUID)
    assert restored.id == entry.id


def test_json_round_trip_preserves_microsecond_precision():
    """Truncating to whole seconds would reorder entries edited in quick
    succession."""
    precise = datetime(2026, 3, 4, 5, 6, 7, 891011, tzinfo=UTC)
    original = Entry(id=uuid4(), title="t", body="b", created_at=precise, updated_at=precise)
    restored = Entry.from_json_bytes(original.to_json_bytes())
    assert restored.created_at == precise
    assert restored.created_at.microsecond == 891011


def test_json_round_trip_preserves_timezone(entry):
    restored = Entry.from_json_bytes(entry.to_json_bytes())
    assert restored.created_at.tzinfo is not None
    assert restored.created_at.utcoffset() == timedelta(0)


def test_json_round_trip_distinguishes_created_from_updated(entry):
    time.sleep(0.001)
    edited = entry.edited(title="Edited")
    restored = Entry.from_json_bytes(edited.to_json_bytes())
    assert restored.created_at == edited.created_at
    assert restored.updated_at == edited.updated_at
    assert restored.updated_at > restored.created_at


@pytest.mark.parametrize(
    "title,body",
    [
        ("", ""),
        ("unicode ✨", "日本語の本文 🔐"),
        ('quotes "and" \\backslashes\\', "tabs\tand\nnewlines\r\n"),
        ("null-ish", "not a null: \\u0000 literal"),
        ("long", "x" * 50_000),
        ("json-looking", '{"id": "not really", "body": [1, 2, 3]}'),
    ],
    ids=["empty", "unicode", "escapes", "nullish", "long", "json-injection"],
)
def test_json_round_trip_handles_awkward_content(title, body):
    original = Entry.new(title, body)
    assert Entry.from_json_bytes(original.to_json_bytes()) == original


def test_to_json_bytes_returns_utf8_bytes(entry):
    data = entry.to_json_bytes()
    assert isinstance(data, bytes)
    data.decode("utf-8")  # must not raise


def test_to_json_bytes_is_deterministic(entry):
    """Same entry, same bytes -- so a save that changes nothing produces
    identical plaintext for the cipher."""
    assert entry.to_json_bytes() == entry.to_json_bytes()


def test_to_json_bytes_emits_expected_shape(entry):
    payload = json.loads(entry.to_json_bytes())
    assert set(payload) == {"id", "title", "body", "created_at", "updated_at"}


def test_from_json_bytes_rejects_invalid_json():
    with pytest.raises(ValueError):
        Entry.from_json_bytes(b"{not json")


@pytest.mark.parametrize("missing", ["id", "title", "body", "created_at", "updated_at"])
def test_from_json_bytes_rejects_missing_field(entry, missing):
    payload = json.loads(entry.to_json_bytes())
    del payload[missing]
    with pytest.raises(ValueError):
        Entry.from_json_bytes(json.dumps(payload).encode("utf-8"))


def test_from_json_bytes_rejects_malformed_uuid(entry):
    payload = json.loads(entry.to_json_bytes())
    payload["id"] = "definitely-not-a-uuid"
    with pytest.raises(ValueError):
        Entry.from_json_bytes(json.dumps(payload).encode("utf-8"))


def test_from_json_bytes_rejects_malformed_timestamp(entry):
    payload = json.loads(entry.to_json_bytes())
    payload["created_at"] = "last tuesday"
    with pytest.raises(ValueError):
        Entry.from_json_bytes(json.dumps(payload).encode("utf-8"))


def test_from_json_bytes_rejects_non_utf8_bytes():
    with pytest.raises(ValueError):
        Entry.from_json_bytes(b"\xff\xfe\x00garbage")
