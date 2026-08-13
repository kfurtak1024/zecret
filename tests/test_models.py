"""Tests for zecret.models.

Required coverage:
    - Entry.new() sets created_at == updated_at and keeps the date it was
      given.
    - entry.edited() returns a NEW Entry instance (original untouched),
      with updated_at refreshed and later than created_at, and with date
      and created_at carried over -- the date is the entry's identity, so
      an edit must not move it.
    - to_json_bytes() / from_json_bytes() round-trips an Entry exactly,
      including datetime precision and the date as a date (not a datetime).
    - body_snippet() picks the first line worth showing and trims it, since
      it is what stands in for a title everywhere an entry is listed.
"""

from __future__ import annotations

import datetime as dt
import json
import time

import pytest

from zecret.models import Entry
from zecret.screens.base import EMPTY_BODY, body_snippet

DAY = dt.date(2026, 8, 13)


@pytest.fixture
def entry() -> Entry:
    return Entry.new(DAY, "A body\nwith two lines")


# --- Entry.new() -----------------------------------------------------------


def test_new_sets_created_at_equal_to_updated_at(entry):
    assert entry.created_at == entry.updated_at


def test_new_stores_date_and_body(entry):
    assert entry.date == DAY
    assert entry.body == "A body\nwith two lines"


def test_new_keeps_the_given_date_regardless_of_today():
    """Backfilling yesterday must file the entry under yesterday, not now."""
    long_ago = dt.date(1999, 12, 31)
    assert Entry.new(long_ago, "b").date == long_ago


def test_new_timestamps_are_utc_aware(entry):
    """Naive datetimes would compare unpredictably across DST and would
    break ordering of entries written on the same day."""
    assert entry.created_at.tzinfo is not None
    assert entry.created_at.utcoffset() == dt.timedelta(0)


def test_new_timestamp_is_current(entry):
    assert abs(dt.datetime.now(dt.UTC) - entry.created_at) < dt.timedelta(seconds=5)


def test_updated_at_defaults_to_created_at_when_omitted():
    """Direct construction (as storage.py does when loading) must not leave
    updated_at as None."""
    created = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.UTC)
    constructed = Entry(date=DAY, body="b", created_at=created)
    assert constructed.updated_at == created


# --- immutability ----------------------------------------------------------


@pytest.mark.parametrize("attribute", ["date", "body", "created_at", "updated_at"])
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
    assert entry.edited("New body") is not entry


def test_edited_leaves_the_original_untouched(entry):
    before = (entry.date, entry.body, entry.created_at, entry.updated_at)
    entry.edited("New body")
    assert (entry.date, entry.body, entry.created_at, entry.updated_at) == before


def test_edited_refreshes_updated_at_to_later_than_created_at(entry):
    time.sleep(0.001)
    assert entry.edited("New body").updated_at > entry.created_at


def test_edited_preserves_date_and_created_at(entry):
    """An edit is the same entry -- storage.py replaces its record by date,
    so a changed date would silently duplicate the entry onto another day
    instead."""
    edited = entry.edited("New body")
    assert edited.date == entry.date
    assert edited.created_at == entry.created_at


def test_edited_updates_body(entry):
    assert entry.edited("New body").body == "New body"


def test_edited_can_set_an_empty_body(entry):
    assert entry.edited("").body == ""


def test_edited_is_chainable(entry):
    time.sleep(0.001)
    once = entry.edited("First edit")
    time.sleep(0.001)
    twice = once.edited("Second edit")
    assert twice.body == "Second edit"
    assert twice.date == entry.date
    assert twice.created_at == entry.created_at
    assert twice.updated_at > once.updated_at


# --- JSON round-trip -------------------------------------------------------


def test_json_round_trip_is_exact(entry):
    assert Entry.from_json_bytes(entry.to_json_bytes()) == entry


def test_json_round_trip_preserves_the_date_as_a_date(entry):
    """A datetime here would not compare equal to the date storage.py keys
    the entry by, so the entry would go missing from its own day."""
    restored = Entry.from_json_bytes(entry.to_json_bytes())
    assert type(restored.date) is dt.date
    assert restored.date == DAY


def test_json_round_trip_preserves_microsecond_precision():
    """Truncating to whole seconds would reorder entries edited in quick
    succession."""
    precise = dt.datetime(2026, 3, 4, 5, 6, 7, 891011, tzinfo=dt.UTC)
    original = Entry(date=DAY, body="b", created_at=precise, updated_at=precise)
    restored = Entry.from_json_bytes(original.to_json_bytes())
    assert restored.created_at == precise
    assert restored.created_at.microsecond == 891011


def test_json_round_trip_preserves_timezone(entry):
    restored = Entry.from_json_bytes(entry.to_json_bytes())
    assert restored.created_at.tzinfo is not None
    assert restored.created_at.utcoffset() == dt.timedelta(0)


def test_json_round_trip_distinguishes_created_from_updated(entry):
    time.sleep(0.001)
    edited = entry.edited("Edited")
    restored = Entry.from_json_bytes(edited.to_json_bytes())
    assert restored.created_at == edited.created_at
    assert restored.updated_at == edited.updated_at
    assert restored.updated_at > restored.created_at


@pytest.mark.parametrize(
    "date",
    [dt.date(2024, 2, 29), dt.date(1, 1, 1), dt.date(9999, 12, 31), dt.date(2026, 1, 1)],
    ids=["leap-day", "min", "max", "new-year"],
)
def test_json_round_trip_handles_boundary_dates(date):
    original = Entry.new(date, "b")
    assert Entry.from_json_bytes(original.to_json_bytes()) == original


@pytest.mark.parametrize(
    "body",
    [
        "",
        "unicode ✨ 日本語の本文 🔐",
        'quotes "and" \\backslashes\\',
        "tabs\tand\nnewlines\r\n",
        "not a null: \\u0000 literal",
        "x" * 50_000,
        '{"date": "not really", "body": [1, 2, 3]}',
    ],
    ids=["empty", "unicode", "escapes", "whitespace", "nullish", "long", "json-injection"],
)
def test_json_round_trip_handles_awkward_content(body):
    original = Entry.new(DAY, body)
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
    assert set(payload) == {"date", "body", "created_at", "updated_at"}


def test_from_json_bytes_rejects_invalid_json():
    with pytest.raises(ValueError):
        Entry.from_json_bytes(b"{not json")


@pytest.mark.parametrize("missing", ["date", "body", "created_at", "updated_at"])
def test_from_json_bytes_rejects_missing_field(entry, missing):
    payload = json.loads(entry.to_json_bytes())
    del payload[missing]
    with pytest.raises(ValueError):
        Entry.from_json_bytes(json.dumps(payload).encode("utf-8"))


@pytest.mark.parametrize(
    "date",
    ["definitely-not-a-date", "2026-02-30", "13/08/2026", ""],
    ids=["words", "no-such-day", "wrong-order", "empty"],
)
def test_from_json_bytes_rejects_malformed_date(entry, date):
    payload = json.loads(entry.to_json_bytes())
    payload["date"] = date
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


# --- body snippets (shared by every list that shows an entry) ---------------


def test_snippet_returns_a_short_first_line_unchanged():
    assert body_snippet("A short line\nand more") == "A short line"


def test_snippet_trims_a_long_first_line_and_marks_it():
    snippet = body_snippet("x" * 200, length=20)
    assert len(snippet) == 20
    assert snippet.endswith("…")


def test_snippet_does_not_leave_a_space_before_the_ellipsis():
    """When the cut lands just after a word, the ellipsis follows the word
    rather than floating a space away from it."""
    assert body_snippet("word " * 10, length=11) == "word word…"


def test_snippet_skips_leading_blank_lines():
    assert body_snippet("\n\n   \nThe real first line") == "The real first line"


def test_snippet_of_an_empty_body_is_labelled():
    assert body_snippet("") == EMPTY_BODY
    assert body_snippet("   \n\n  ") == EMPTY_BODY
