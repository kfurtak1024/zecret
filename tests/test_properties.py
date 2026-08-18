"""Property-based tests over the parts that take input they did not write.

The example-based suites cover the malformations someone thought of. These
cover the ones nobody did. Everything here is a pure function over bytes or
JSON-shaped values -- no screens, no diaries, no filesystem -- which is
exactly the shape Hypothesis is good at and the layer where a mistake is
most expensive.

Required coverage:
    - Entry survives a round trip through JSON exactly, for any body, date
      and pair of timestamps -- the diary is only as good as this.
    - Entry.from_json_bytes() is total over arbitrary bytes: an Entry or a
      ValueError, never a half-built object and never another exception.
    - KdfParams survives a round trip through its header dict, and
      from_dict() is total over arbitrary dicts.
    - _parse_record() and _load_document() are total the same way, since
      both read a file this program may not have written.
    - encrypt()/decrypt() round-trips any plaintext, and any tampering with
      the ciphertext is caught.
    - body_snippet() honours its length bound for any body at all.

"Total" is the property that matters for the parsers. The screens catch
ValueError and report a file they cannot read; anything else -- a
TypeError, an AttributeError, a KeyError escaping -- reaches the user as a
traceback over their diary.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
from typing import Any

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from zecret.crypto import KEY_SIZE, NONCE_SIZE, KdfParams, ZecretDecryptError, decrypt, encrypt
from zecret.models import Entry
from zecret.screens.base import EMPTY_BODY, SNIPPET_CAP, body_snippet
from zecret.storage import _load_document, _parse_record

# Zecret stores UTC timestamps and local dates, and a diary may hold any
# text at all -- other alphabets, emoji, control characters someone pasted.
timestamps = st.datetimes(
    min_value=dt.datetime(1900, 1, 1),
    max_value=dt.datetime(2999, 12, 31),
    timezones=st.just(dt.UTC),
)
bodies = st.text()
dates = st.dates()


@st.composite
def entries(draw: st.DrawFn) -> Entry:
    """An arbitrary Entry, including ones no UI would produce."""
    created = draw(timestamps)
    return Entry(
        date=draw(dates),
        body=draw(bodies),
        created_at=created,
        # Usually at or after created_at, but the model does not enforce
        # that and neither does this.
        updated_at=draw(st.one_of(st.just(created), timestamps)),
    )


#: JSON-shaped values, for feeding the parsers things a file could contain.
json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(),
    lambda children: st.lists(children) | st.dictionaries(st.text(), children),
    max_leaves=8,
)


# --- Entry round trip ------------------------------------------------------


@given(entry=entries())
def test_an_entry_survives_the_round_trip_exactly(entry: Entry):
    """What comes back out of the ciphertext has to be what went in --
    every character of the body, and every microsecond of the timestamps."""
    assert Entry.from_json_bytes(entry.to_json_bytes()) == entry


@given(entry=entries())
def test_the_round_trip_keeps_the_date_a_date(entry: Entry):
    """A date that came back as a datetime would still compare equal to
    nothing and sort oddly against the rest of the diary."""
    restored = Entry.from_json_bytes(entry.to_json_bytes())
    assert type(restored.date) is dt.date
    assert restored.date == entry.date


# --- the parsers are total -------------------------------------------------


@given(data=st.binary(max_size=256))
def test_from_json_bytes_is_an_entry_or_a_value_error(data: bytes):
    try:
        entry = Entry.from_json_bytes(data)
    except ValueError:
        return
    assert isinstance(entry, Entry)


@given(payload=json_values)
def test_from_json_bytes_is_total_over_json_that_parses(payload: Any):
    """Past the JSON decode, where the interesting failures live: a dict
    with the right keys and wrong types, a list, a bare string."""
    data = json.dumps(payload).encode("utf-8")
    try:
        entry = Entry.from_json_bytes(data)
    except ValueError:
        return
    assert isinstance(entry, Entry)


@given(raw=json_values)
def test_parse_record_is_a_triple_or_a_value_error(raw: Any):
    try:
        date, nonce, ciphertext = _parse_record(raw)
    except ValueError:
        return
    assert isinstance(date, dt.date)
    assert isinstance(nonce, bytes)
    assert isinstance(ciphertext, bytes)


@given(document=json_values)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_load_document_is_a_diary_or_a_value_error(document: Any, tmp_path):
    path = tmp_path / "diary.enc"
    path.write_bytes(json.dumps(document).encode("utf-8"))
    try:
        loaded = _load_document(path)
    except ValueError:
        return
    assert isinstance(loaded, dict)


@given(data=st.binary(max_size=256))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_load_document_is_total_over_arbitrary_bytes(data: bytes, tmp_path):
    path = tmp_path / "diary.enc"
    path.write_bytes(data)
    try:
        loaded = _load_document(path)
    except ValueError:
        return
    assert isinstance(loaded, dict)


# --- KdfParams -------------------------------------------------------------


@given(
    salt=st.binary(min_size=1, max_size=64),
    time_cost=st.integers(min_value=1, max_value=16),
    memory_cost=st.integers(min_value=8, max_value=1 << 20),
    parallelism=st.integers(min_value=1, max_value=16),
)
def test_kdf_params_survive_the_header_round_trip(
    salt: bytes, time_cost: int, memory_cost: int, parallelism: int
):
    """A salt that did not come back byte for byte would derive a different
    key, and lock the diary against the password that made it."""
    params = KdfParams(
        salt=salt, time_cost=time_cost, memory_cost=memory_cost, parallelism=parallelism
    )
    assert KdfParams.from_dict(params.to_dict()) == params


@given(header=st.dictionaries(st.text(), json_values))
def test_kdf_from_dict_is_params_or_a_value_error(header: dict[str, Any]):
    try:
        params = KdfParams.from_dict(header)
    except ValueError:
        return
    assert isinstance(params, KdfParams)


# --- crypto ----------------------------------------------------------------


@given(key=st.binary(min_size=KEY_SIZE, max_size=KEY_SIZE), plaintext=st.binary(max_size=4096))
def test_encrypt_decrypt_round_trips_any_plaintext(key: bytes, plaintext: bytes):
    nonce, ciphertext = encrypt(key, plaintext)
    assert len(nonce) == NONCE_SIZE
    assert decrypt(key, nonce, ciphertext) == plaintext


@given(
    key=st.binary(min_size=KEY_SIZE, max_size=KEY_SIZE),
    plaintext=st.binary(max_size=512),
    index=st.integers(min_value=0),
    flip=st.integers(min_value=1, max_value=255),
)
def test_any_tampering_with_the_ciphertext_is_caught(
    key: bytes, plaintext: bytes, index: int, flip: int
):
    """The AEAD guarantee, over every byte position rather than the one a
    hand-written test happened to pick."""
    nonce, ciphertext = encrypt(key, plaintext)
    position = index % len(ciphertext)
    tampered = bytearray(ciphertext)
    tampered[position] ^= flip

    with pytest.raises(ZecretDecryptError):
        decrypt(key, nonce, bytes(tampered))


@given(
    key=st.binary(min_size=KEY_SIZE, max_size=KEY_SIZE),
    other=st.binary(min_size=KEY_SIZE, max_size=KEY_SIZE),
    plaintext=st.binary(max_size=512),
)
def test_the_wrong_key_never_decrypts(key: bytes, other: bytes, plaintext: bytes):
    assume(key != other)
    nonce, ciphertext = encrypt(key, plaintext)
    with pytest.raises(ZecretDecryptError):
        decrypt(other, nonce, ciphertext)


@given(
    key=st.binary(min_size=KEY_SIZE, max_size=KEY_SIZE),
    nonce=st.binary(max_size=32),
    ciphertext=st.binary(max_size=256),
)
def test_decrypt_fails_closed_on_anything_it_is_handed(key: bytes, nonce: bytes, ciphertext: bytes):
    """Wrong nonce length, truncated ciphertext, bytes that were never a
    ciphertext at all: one exception for all of it, and never plaintext."""
    try:
        decrypt(key, nonce, ciphertext)
    except ZecretDecryptError:
        return
    pytest.fail("decrypt() returned bytes it never encrypted")


@given(salt=st.binary(min_size=1, max_size=64))
def test_the_salt_survives_base64(salt: bytes):
    encoded = KdfParams(salt=salt).to_dict()["salt"]
    assert base64.b64decode(encoded, validate=True) == salt


# --- presentation ----------------------------------------------------------


@given(body=bodies, length=st.integers(min_value=2, max_value=200))
def test_a_snippet_never_exceeds_its_length(body: str, length: int):
    """The row is trimmed to the window at render time, so this bound is
    not what the reader sees -- it is the guard that keeps one pasted
    paragraph with no newline out of a label. Overshooting it would defeat
    the only thing standing between the list and an unbounded string."""
    assert len(body_snippet(body, length)) <= max(length, len(EMPTY_BODY))


@given(body=bodies)
def test_a_snippet_is_never_blank(body: str):
    """Every row has to say something, or the day looks like a gap."""
    assert body_snippet(body, SNIPPET_CAP).strip()
