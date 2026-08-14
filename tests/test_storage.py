"""Tests for zecret.storage.

Required coverage:
    - create_new() writes a valid, parseable diary file with zero entries.
    - unlock() with the correct password returns all entries decrypted
      correctly (round-trip through create_new -> add -> save -> unlock).
    - unlock() with the wrong password raises ZecretDecryptError.
    - unlock() on a nonexistent path raises FileNotFoundError.
    - add_entry() + save() + unlock() persists the new entry, and a second
      entry for a day that already has one is refused.
    - update_entry() + save() + unlock() reflects the edit, and confirms
      OTHER entries' ciphertexts are unchanged (proves independent
      per-entry encryption -- edit one entry without touching others).
    - delete_entry() + save() + unlock() confirms the entry is gone and
      no other entries are affected.
    - save() is atomic: simulate/verify no partial file is left if
      interrupted (e.g. check a temp file is used and renamed).
    - create_new() refuses a path that gained a diary while it was busy
      deriving the key, rather than writing over it, and leaves nothing
      behind if the write fails.
    - change_password() + save() + unlock() with the NEW password succeeds,
      and unlock() with the OLD password now fails.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import stat
from pathlib import Path

import pytest

from zecret import storage
from zecret.crypto import KdfParams, ZecretDecryptError, derive_key, encrypt
from zecret.models import Entry
from zecret.storage import (
    DEFAULT_DIARY_PATH,
    FORMAT_VERSION,
    DiaryFile,
    ZecretConflictError,
)

PASSWORD = "correct horse battery staple"
WRONG_PASSWORD = "Correct horse battery staple"
#: The other Zecret in the create-a-diary race.
WINNER_PASSWORD = "the password that got there first"
NEW_PASSWORD = "an entirely different passphrase"

DAYS = [dt.date(2026, 8, 11), dt.date(2026, 8, 12), dt.date(2026, 8, 13)]
UNWRITTEN_DAY = dt.date(2019, 4, 1)

# Argon2 at the real defaults costs ~30ms per derivation, and these tests
# unlock constantly (see tests/conftest.py).
pytestmark = pytest.mark.usefixtures("cheap_kdf")


@pytest.fixture
def diary_path(tmp_path: Path) -> Path:
    return tmp_path / "diary.enc"


def read_document(path: Path) -> dict:
    return json.loads(path.read_bytes().decode("utf-8"))


def ciphertexts_by_date(path: Path) -> dict[str, str]:
    return {rec["date"]: rec["ciphertext"] for rec in read_document(path)["entries"]}


def nonces_by_date(path: Path) -> dict[str, str]:
    return {rec["date"]: rec["nonce"] for rec in read_document(path)["entries"]}


def populated(diary_path: Path) -> tuple[DiaryFile, bytes, list[Entry]]:
    """A saved diary with an entry on each of three consecutive days."""
    diary, key = DiaryFile.create_new(diary_path, PASSWORD)
    entries = [Entry.new(day, f"Body written on {day}") for day in DAYS]
    for entry in entries:
        diary.add_entry(entry)
    diary.save(key)
    return diary, key, entries


# --- create_new ------------------------------------------------------------


def test_create_new_writes_a_file(diary_path):
    DiaryFile.create_new(diary_path, PASSWORD)
    assert diary_path.exists()


def test_create_new_writes_parseable_document_with_zero_entries(diary_path):
    DiaryFile.create_new(diary_path, PASSWORD)
    document = read_document(diary_path)
    assert document["version"] == FORMAT_VERSION
    assert document["entries"] == []
    assert document["kdf"]["algo"] == "argon2id"


def test_create_new_returns_empty_diary_and_usable_key(diary_path):
    diary, key = DiaryFile.create_new(diary_path, PASSWORD)
    assert diary.entries == {}
    assert diary.path == diary_path
    assert len(key) == 32


def test_create_new_key_matches_what_unlock_derives(diary_path):
    _, created_key = DiaryFile.create_new(diary_path, PASSWORD)
    _, unlocked_key = DiaryFile.unlock(diary_path, PASSWORD)
    assert created_key == unlocked_key


def test_create_new_creates_missing_parent_directories(tmp_path):
    nested = tmp_path / "deeply" / "nested" / "diary.enc"
    DiaryFile.create_new(nested, PASSWORD)
    assert nested.exists()


def test_create_new_refuses_to_overwrite_existing_file(diary_path):
    DiaryFile.create_new(diary_path, PASSWORD)
    before = diary_path.read_bytes()
    with pytest.raises(FileExistsError):
        DiaryFile.create_new(diary_path, "some other password")
    assert diary_path.read_bytes() == before, "existing diary must be untouched"


def test_create_new_refuses_a_diary_that_appears_while_it_derives(diary_path, monkeypatch):
    """The gap between "is a diary there?" and writing one is as long as
    Argon2 takes, which is deliberately most of a second. Two Zecrets
    started with no diary can both pass the check and both go on to write;
    without an exclusive create the second lands on top of the first and
    reports success, and the first person's entries are gone.

    The race is reproduced by having the loser's key derivation be when the
    winner creates their diary.
    """
    real_derive = storage.derive_key

    def derive_and_lose_the_race(password, params):
        if password == PASSWORD:
            monkeypatch.setattr(storage, "derive_key", real_derive)
            winner, winner_key = DiaryFile.create_new(diary_path, WINNER_PASSWORD)
            winner.add_entry(Entry.new(DAYS[0], "The winner's first day"))
            winner.save(winner_key)
        return real_derive(password, params)

    monkeypatch.setattr(storage, "derive_key", derive_and_lose_the_race)

    with pytest.raises(FileExistsError):
        DiaryFile.create_new(diary_path, PASSWORD)

    # The winner's diary is still theirs, and still has what they wrote.
    survivor, _ = DiaryFile.unlock(diary_path, WINNER_PASSWORD)
    assert survivor.entry_for(DAYS[0]).body == "The winner's first day"


def test_create_new_leaves_nothing_behind_when_the_write_fails(diary_path, monkeypatch):
    """A stub of a file at a path that was empty a moment ago would send the
    next launch to the unlock screen for a diary that is not there."""

    def no_room(_descriptor):
        raise OSError("no space left on device")

    monkeypatch.setattr(os, "fsync", no_room)

    with pytest.raises(OSError):
        DiaryFile.create_new(diary_path, PASSWORD)
    assert not diary_path.exists()


def test_create_new_uses_a_fresh_salt_per_diary(tmp_path):
    first, _ = DiaryFile.create_new(tmp_path / "a.enc", PASSWORD)
    second, _ = DiaryFile.create_new(tmp_path / "b.enc", PASSWORD)
    assert first.kdf_params.salt != second.kdf_params.salt


def test_created_file_is_not_group_or_world_readable(diary_path):
    DiaryFile.create_new(diary_path, PASSWORD)
    mode = stat.S_IMODE(diary_path.stat().st_mode)
    assert mode & 0o077 == 0, f"diary is readable by others: {mode:o}"


def test_default_diary_path_is_under_home():
    """Sanity check that tests never point at the real diary."""
    assert Path.home() / ".zecret" / "diary.enc" == DEFAULT_DIARY_PATH


# --- unlock ----------------------------------------------------------------


def test_unlock_with_correct_password_returns_entries(diary_path):
    _, _, entries = populated(diary_path)
    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entries == {entry.date: entry for entry in entries}


def test_unlock_keys_entries_by_date(diary_path):
    populated(diary_path)
    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert set(reopened.entries) == set(DAYS)
    assert all(isinstance(day, dt.date) for day in reopened.entries)


def test_unlock_round_trips_entry_content_exactly(diary_path):
    diary, key = DiaryFile.create_new(diary_path, PASSWORD)
    entry = Entry.new(DAYS[0], 'Multi-line\nbody with 日本語 ✨ and "quotes"')
    diary.add_entry(entry)
    diary.save(key)

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    restored = reopened.entries[entry.date]
    assert restored == entry
    assert restored.body == entry.body
    assert restored.created_at == entry.created_at
    assert restored.updated_at == entry.updated_at


def test_unlock_with_wrong_password_raises_decrypt_error(diary_path):
    populated(diary_path)
    with pytest.raises(ZecretDecryptError):
        DiaryFile.unlock(diary_path, WRONG_PASSWORD)


def test_unlock_empty_diary_with_wrong_password_raises(diary_path):
    """An empty diary has no entry ciphertext to authenticate against, so
    without the header verifier any password would open it -- and the next
    save would silently re-key the diary to that wrong password, locking
    the user out of their real one."""
    DiaryFile.create_new(diary_path, PASSWORD)
    with pytest.raises(ZecretDecryptError):
        DiaryFile.unlock(diary_path, WRONG_PASSWORD)


def test_unlock_empty_diary_with_correct_password_succeeds(diary_path):
    DiaryFile.create_new(diary_path, PASSWORD)
    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entries == {}


def test_unlock_rejects_missing_verifier(diary_path):
    """Stripping the verifier must not downgrade to 'anything opens it'."""
    populated(diary_path)
    document = read_document(diary_path)
    del document["verifier"]
    diary_path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        DiaryFile.unlock(diary_path, WRONG_PASSWORD)


def test_unlock_rejects_tampered_verifier(diary_path):
    DiaryFile.create_new(diary_path, PASSWORD)
    document = read_document(diary_path)
    raw = bytearray(base64.b64decode(document["verifier"]["ciphertext"]))
    raw[0] ^= 0x01
    document["verifier"]["ciphertext"] = base64.b64encode(bytes(raw)).decode()
    diary_path.write_text(json.dumps(document))

    with pytest.raises(ZecretDecryptError):
        DiaryFile.unlock(diary_path, PASSWORD)


def test_verifier_uses_a_fresh_nonce_each_save(diary_path):
    """It is encrypted anew on every save; reusing its nonce under the same
    key would be exactly the reuse crypto.encrypt() exists to prevent."""
    diary, key, _ = populated(diary_path)
    first = read_document(diary_path)["verifier"]["nonce"]
    diary.add_entry(Entry.new(UNWRITTEN_DAY, "Body"))
    diary.save(key)
    assert read_document(diary_path)["verifier"]["nonce"] != first


def test_verifier_does_not_reveal_the_password(diary_path):
    DiaryFile.create_new(diary_path, PASSWORD)
    raw = diary_path.read_bytes()
    assert PASSWORD.encode() not in raw
    assert b"zecret-key-check" not in raw, "verifier plaintext must be encrypted"


def test_unlock_on_nonexistent_path_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        DiaryFile.unlock(tmp_path / "no-such-diary.enc", PASSWORD)


def test_unlock_preserves_kdf_params(diary_path):
    diary, _ = DiaryFile.create_new(diary_path, PASSWORD)
    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.kdf_params == diary.kdf_params


def test_unlock_rejects_unknown_format_version(diary_path):
    populated(diary_path)
    document = read_document(diary_path)
    document["version"] = 99
    diary_path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        DiaryFile.unlock(diary_path, PASSWORD)


def test_unlock_rejects_the_retired_version_1_format(diary_path):
    """Version 1 was UUID-and-title keyed. It is not migrated, so it must
    be refused outright rather than half-read as if it were version 2."""
    populated(diary_path)
    document = read_document(diary_path)
    document["version"] = 1
    diary_path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        DiaryFile.unlock(diary_path, PASSWORD)


def test_unlock_rejects_non_json_file(diary_path):
    diary_path.write_bytes(b"this is not a diary")
    with pytest.raises(ValueError):
        DiaryFile.unlock(diary_path, PASSWORD)


def test_unlock_rejects_tampered_ciphertext(diary_path):
    """Flipping a byte of a stored ciphertext must be detected, not
    silently skipped or returned as garbage."""
    populated(diary_path)
    document = read_document(diary_path)
    raw = bytearray(base64.b64decode(document["entries"][1]["ciphertext"]))
    raw[0] ^= 0x01
    document["entries"][1]["ciphertext"] = base64.b64encode(bytes(raw)).decode()
    diary_path.write_text(json.dumps(document))

    with pytest.raises(ZecretDecryptError):
        DiaryFile.unlock(diary_path, PASSWORD)


def test_unlock_rejects_record_date_that_disagrees_with_ciphertext(diary_path):
    """The record date is outside the AEAD; the date inside the entry is
    not. Refiling a record must not silently move an entry to another day."""
    populated(diary_path)
    document = read_document(diary_path)
    document["entries"][0]["date"] = UNWRITTEN_DAY.isoformat()
    diary_path.write_text(json.dumps(document))

    with pytest.raises(ValueError):
        DiaryFile.unlock(diary_path, PASSWORD)


def test_unlock_rejects_duplicated_record(diary_path):
    populated(diary_path)
    document = read_document(diary_path)
    document["entries"].append(document["entries"][0])
    diary_path.write_text(json.dumps(document))

    with pytest.raises(ValueError):
        DiaryFile.unlock(diary_path, PASSWORD)


def test_unlock_rejects_malformed_record(diary_path):
    populated(diary_path)
    document = read_document(diary_path)
    del document["entries"][0]["nonce"]
    diary_path.write_text(json.dumps(document))

    with pytest.raises(ValueError):
        DiaryFile.unlock(diary_path, PASSWORD)


def test_unlock_rejects_malformed_record_date(diary_path):
    populated(diary_path)
    document = read_document(diary_path)
    document["entries"][0]["date"] = "the day before yesterday"
    diary_path.write_text(json.dumps(document))

    with pytest.raises(ValueError):
        DiaryFile.unlock(diary_path, PASSWORD)


# --- add / update / delete -------------------------------------------------


def test_add_entry_then_save_then_unlock_persists_it(diary_path):
    diary, key = DiaryFile.create_new(diary_path, PASSWORD)
    entry = Entry.new(DAYS[0], "Body text")
    diary.add_entry(entry)
    diary.save(key)

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entries == {entry.date: entry}


def test_add_entry_does_not_touch_disk_until_save(diary_path):
    diary, _ = DiaryFile.create_new(diary_path, PASSWORD)
    diary.add_entry(Entry.new(DAYS[0], "Body"))
    assert read_document(diary_path)["entries"] == []


def test_add_entry_rejects_a_second_entry_for_the_same_day(diary_path):
    """One entry per day is the whole model: a second one must be refused,
    not silently replace the first."""
    diary, _ = DiaryFile.create_new(diary_path, PASSWORD)
    diary.add_entry(Entry.new(DAYS[0], "Morning thoughts"))
    with pytest.raises(ValueError):
        diary.add_entry(Entry.new(DAYS[0], "Evening thoughts"))
    assert diary.entries[DAYS[0]].body == "Morning thoughts"


def test_entry_for_returns_the_day_s_entry(diary_path):
    diary, _, entries = populated(diary_path)
    assert diary.entry_for(DAYS[1]) == entries[1]


def test_entry_for_returns_none_for_an_unwritten_day(diary_path):
    diary, _, _ = populated(diary_path)
    assert diary.entry_for(UNWRITTEN_DAY) is None


def test_entry_for_survives_a_round_trip(diary_path):
    populated(diary_path)
    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entry_for(DAYS[2]).body == f"Body written on {DAYS[2]}"


def test_update_entry_then_save_then_unlock_reflects_the_edit(diary_path):
    diary, key, entries = populated(diary_path)
    edited = entries[1].edited("Edited body")
    diary.update_entry(edited)
    diary.save(key)

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entries[edited.date] == edited
    assert reopened.entries[edited.date].body == "Edited body"
    assert len(reopened.entries) == 3


def test_update_entry_leaves_other_ciphertexts_byte_identical(diary_path):
    """CLAUDE.md requirement 6: per-entry independent encryption. Editing
    one day must not re-encrypt any other day's record."""
    diary, key, entries = populated(diary_path)
    before = ciphertexts_by_date(diary_path)
    before_nonces = nonces_by_date(diary_path)

    diary.update_entry(entries[1].edited("Edited body"))
    diary.save(key)

    after = ciphertexts_by_date(diary_path)
    after_nonces = nonces_by_date(diary_path)
    for day in (DAYS[0].isoformat(), DAYS[2].isoformat()):
        assert after[day] == before[day], "unrelated ciphertext was rewritten"
        assert after_nonces[day] == before_nonces[day]
    edited_day = DAYS[1].isoformat()
    assert after[edited_day] != before[edited_day], "edit was not encrypted"


def test_repeated_save_without_changes_rewrites_no_ciphertext(diary_path):
    diary, key, _ = populated(diary_path)
    before = ciphertexts_by_date(diary_path)
    diary.save(key)
    assert ciphertexts_by_date(diary_path) == before


def test_update_entry_reencrypts_with_a_fresh_nonce(diary_path):
    """The edited entry itself must get a new nonce -- never reuse the old
    one with the same key."""
    diary, key, entries = populated(diary_path)
    before = nonces_by_date(diary_path)[DAYS[1].isoformat()]
    diary.update_entry(entries[1].edited("Edited body"))
    diary.save(key)
    assert nonces_by_date(diary_path)[DAYS[1].isoformat()] != before


def test_update_entry_rejects_an_unwritten_day(diary_path):
    diary, _, _ = populated(diary_path)
    with pytest.raises(KeyError):
        diary.update_entry(Entry.new(UNWRITTEN_DAY, "Body"))


def test_delete_entry_then_save_then_unlock_removes_only_that_entry(diary_path):
    diary, key, entries = populated(diary_path)
    diary.delete_entry(DAYS[1])
    diary.save(key)

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert DAYS[1] not in reopened.entries
    assert reopened.entries == {entries[0].date: entries[0], entries[2].date: entries[2]}


def test_delete_entry_leaves_other_ciphertexts_byte_identical(diary_path):
    diary, key, _ = populated(diary_path)
    before = ciphertexts_by_date(diary_path)

    diary.delete_entry(DAYS[1])
    diary.save(key)

    after = ciphertexts_by_date(diary_path)
    assert DAYS[1].isoformat() not in after
    for day in (DAYS[0].isoformat(), DAYS[2].isoformat()):
        assert after[day] == before[day], "unrelated ciphertext was rewritten"


def test_delete_entry_rejects_an_unwritten_day(diary_path):
    diary, _, _ = populated(diary_path)
    with pytest.raises(KeyError):
        diary.delete_entry(UNWRITTEN_DAY)


def test_deleted_entry_does_not_come_back_after_reunlock(diary_path):
    diary, key, _ = populated(diary_path)
    diary.delete_entry(DAYS[0])
    diary.save(key)
    reopened, reopened_key = DiaryFile.unlock(diary_path, PASSWORD)
    reopened.save(reopened_key)
    final, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert DAYS[0] not in final.entries


def test_a_day_can_be_rewritten_after_being_deleted(diary_path):
    """Deleting frees the day: adding it again is a new entry, not a
    duplicate-day error."""
    diary, key, _ = populated(diary_path)
    diary.delete_entry(DAYS[0])
    diary.add_entry(Entry.new(DAYS[0], "Second attempt at that day"))
    diary.save(key)

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entries[DAYS[0]].body == "Second attempt at that day"
    assert len(reopened.entries) == 3


# --- on-disk ordering ------------------------------------------------------


def test_entries_are_written_newest_day_first(diary_path):
    diary, key = DiaryFile.create_new(diary_path, PASSWORD)
    for day in (DAYS[1], DAYS[2], DAYS[0]):  # added out of order
        diary.add_entry(Entry.new(day, f"Body {day}"))
    diary.save(key)

    written = [rec["date"] for rec in read_document(diary_path)["entries"]]
    assert written == [day.isoformat() for day in reversed(DAYS)]


# --- a second session on the same file --------------------------------------


def test_save_refuses_when_the_file_changed_underneath(diary_path):
    """Two Zecrets on one diary: the second to save would otherwise write
    its whole in-memory copy over the first's entries, silently."""
    populated(diary_path)
    first, first_key = DiaryFile.unlock(diary_path, PASSWORD)
    second, second_key = DiaryFile.unlock(diary_path, PASSWORD)

    second.add_entry(Entry.new(UNWRITTEN_DAY, "Written by the other session"))
    second.save(second_key)

    first.add_entry(Entry.new(dt.date(2026, 7, 1), "Written by this one"))
    with pytest.raises(ZecretConflictError):
        first.save(first_key)


def test_a_refused_save_leaves_the_other_sessions_work_alone(diary_path):
    populated(diary_path)
    first, first_key = DiaryFile.unlock(diary_path, PASSWORD)
    second, second_key = DiaryFile.unlock(diary_path, PASSWORD)

    second.add_entry(Entry.new(UNWRITTEN_DAY, "Written by the other session"))
    second.save(second_key)
    after_second = diary_path.read_bytes()

    first.add_entry(Entry.new(dt.date(2026, 7, 1), "Written by this one"))
    with pytest.raises(ZecretConflictError):
        first.save(first_key)

    assert diary_path.read_bytes() == after_second
    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert UNWRITTEN_DAY in reopened.entries
    assert dt.date(2026, 7, 1) not in reopened.entries


def test_a_refused_save_leaves_no_temp_file_behind(diary_path):
    """The check runs before anything is written."""
    populated(diary_path)
    first, first_key = DiaryFile.unlock(diary_path, PASSWORD)
    second, second_key = DiaryFile.unlock(diary_path, PASSWORD)
    second.add_entry(Entry.new(UNWRITTEN_DAY, "Body"))
    second.save(second_key)

    with pytest.raises(ZecretConflictError):
        first.save(first_key)

    leftovers = [p.name for p in diary_path.parent.iterdir() if p != diary_path]
    assert leftovers == []


def test_reopening_clears_the_conflict(diary_path):
    """The way out is to reopen the diary, which is what unlock re-stamps."""
    populated(diary_path)
    first, first_key = DiaryFile.unlock(diary_path, PASSWORD)
    second, second_key = DiaryFile.unlock(diary_path, PASSWORD)
    second.add_entry(Entry.new(UNWRITTEN_DAY, "Body"))
    second.save(second_key)

    with pytest.raises(ZecretConflictError):
        first.save(first_key)

    reopened, key = DiaryFile.unlock(diary_path, PASSWORD)
    reopened.add_entry(Entry.new(dt.date(2026, 7, 1), "Now it lands"))
    reopened.save(key)

    final, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert set(final.entries) == set(DAYS) | {UNWRITTEN_DAY, dt.date(2026, 7, 1)}


def test_a_diary_that_has_never_written_has_nothing_to_conflict_with(diary_path):
    """_file_stamp is None until a write of this session's lands, and a
    DiaryFile that has never written cannot be overwriting anyone.

    create_new() used to be how that state reached save(); it now writes
    exclusively instead and never goes through the conflict check at all.
    The case is still real for a DiaryFile built directly, and is still the
    right answer for it, so it is covered here rather than left to rot.
    """
    diary = DiaryFile(path=diary_path, kdf_params=KdfParams.generate(), entries={})
    key = derive_key(PASSWORD, diary.kdf_params)
    diary.add_entry(Entry.new(DAYS[0], "Written by a hand-built diary"))
    diary.save(key)

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entry_for(DAYS[0]).body == "Written by a hand-built diary"


def test_repeated_saves_from_one_session_never_conflict(diary_path):
    """Each save re-stamps, or a session would trip over its own writes."""
    diary, key, _ = populated(diary_path)
    for day in (dt.date(2026, 7, 1), dt.date(2026, 7, 2), dt.date(2026, 7, 3)):
        diary.add_entry(Entry.new(day, f"Body {day}"))
        diary.save(key)

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert len(reopened.entries) == 6


def test_a_deleted_diary_is_written_back_rather_than_refused(diary_path):
    """Nothing to overwrite, so nothing to lose: this restores the file."""
    diary, key, entries = populated(diary_path)
    diary_path.unlink()

    diary.save(key)

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entries == {entry.date: entry for entry in entries}


def test_an_interrupted_save_does_not_look_like_a_conflict(diary_path, monkeypatch):
    """A failed write leaves the file untouched, so the next attempt must
    still be allowed through."""
    diary, key, _ = populated(diary_path)

    monkeypatch.setattr(os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError("boom")))
    diary.add_entry(Entry.new(UNWRITTEN_DAY, "Body"))
    with pytest.raises(OSError):
        diary.save(key)

    monkeypatch.undo()
    diary.save(key)

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert UNWRITTEN_DAY in reopened.entries


# --- atomic writes ---------------------------------------------------------


def test_save_uses_a_temp_file_and_renames_it(diary_path, monkeypatch):
    """The write must land via os.replace() of a different path, not by
    truncating the live diary in place."""
    diary, key, _ = populated(diary_path)
    calls: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy(src, dst, *args, **kwargs):
        calls.append((str(src), str(dst)))
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", spy)
    diary.add_entry(Entry.new(UNWRITTEN_DAY, "Body"))
    diary.save(key)

    assert len(calls) == 1, "expected exactly one atomic rename"
    src, dst = calls[0]
    assert dst == str(diary_path)
    assert src != str(diary_path)


def test_save_fsyncs_before_renaming(diary_path, monkeypatch):
    """Without fsync the rename can land ahead of the data on a crash."""
    diary, key, _ = populated(diary_path)
    order: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    monkeypatch.setattr(os, "fsync", lambda fd: (order.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(
        os, "replace", lambda s, d: (order.append("replace"), real_replace(s, d))[1]
    )
    diary.add_entry(Entry.new(UNWRITTEN_DAY, "Body"))
    diary.save(key)

    assert order.index("fsync") < order.index("replace")


def test_interrupted_save_leaves_the_original_file_intact(diary_path, monkeypatch):
    diary, key, entries = populated(diary_path)
    before = diary_path.read_bytes()

    def boom(src, dst):
        raise OSError("simulated crash during rename")

    monkeypatch.setattr(os, "replace", boom)
    diary.add_entry(Entry.new(UNWRITTEN_DAY, "Doomed"))
    with pytest.raises(OSError):
        diary.save(key)

    assert diary_path.read_bytes() == before, "diary was damaged by a failed save"
    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entries == {entry.date: entry for entry in entries}


def test_interrupted_save_leaves_no_temp_file_behind(diary_path, monkeypatch):
    diary, key, _ = populated(diary_path)

    monkeypatch.setattr(os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError("boom")))
    diary.add_entry(Entry.new(UNWRITTEN_DAY, "Doomed"))
    with pytest.raises(OSError):
        diary.save(key)

    leftovers = [p.name for p in diary_path.parent.iterdir() if p != diary_path]
    assert leftovers == [], f"temp files left behind: {leftovers}"


def test_failed_save_does_not_poison_the_ciphertext_cache(diary_path, monkeypatch):
    """After a failed save the cache must still describe what is on disk,
    so the next successful save writes a complete, consistent file."""
    diary, key, entries = populated(diary_path)
    new_entry = Entry.new(UNWRITTEN_DAY, "Added during failure")

    monkeypatch.setattr(os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError("boom")))
    diary.add_entry(new_entry)
    with pytest.raises(OSError):
        diary.save(key)

    monkeypatch.undo()
    diary.save(key)

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert set(reopened.entries) == {entry.date for entry in entries} | {new_entry.date}


def test_save_never_writes_plaintext_into_the_file(diary_path):
    """Requirement 4: no plaintext on disk, in any field."""
    diary, key = DiaryFile.create_new(diary_path, PASSWORD)
    diary.add_entry(Entry.new(DAYS[0], "UNIQUEBODYMARKER"))
    diary.save(key)

    raw = diary_path.read_bytes()
    assert b"UNIQUEBODYMARKER" not in raw
    assert PASSWORD.encode() not in raw


# --- change_password -------------------------------------------------------


def test_change_password_then_save_then_unlock_with_new_password(diary_path):
    diary, _, entries = populated(diary_path)
    new_key = diary.change_password(NEW_PASSWORD)
    diary.save(new_key)

    reopened, _ = DiaryFile.unlock(diary_path, NEW_PASSWORD)
    assert reopened.entries == {entry.date: entry for entry in entries}


def test_change_password_makes_the_old_password_fail(diary_path):
    diary, _, _ = populated(diary_path)
    new_key = diary.change_password(NEW_PASSWORD)
    diary.save(new_key)

    with pytest.raises(ZecretDecryptError):
        DiaryFile.unlock(diary_path, PASSWORD)


def test_change_password_returns_a_different_key(diary_path):
    diary, old_key, _ = populated(diary_path)
    assert diary.change_password(NEW_PASSWORD) != old_key


def test_change_password_generates_a_fresh_salt(diary_path):
    """Even reusing the same password must produce a different key."""
    diary, old_key, _ = populated(diary_path)
    old_salt = diary.kdf_params.salt
    new_key = diary.change_password(PASSWORD)
    assert diary.kdf_params.salt != old_salt
    assert new_key != old_key


def test_change_password_reencrypts_every_entry(diary_path):
    """The one case where all ciphertexts must change: they are now under a
    different key."""
    diary, _, _ = populated(diary_path)
    before = ciphertexts_by_date(diary_path)
    new_key = diary.change_password(NEW_PASSWORD)
    diary.save(new_key)

    after = ciphertexts_by_date(diary_path)
    assert set(after) == set(before)
    for day, ciphertext in after.items():
        assert ciphertext != before[day], "entry still encrypted under the old key"


def test_change_password_does_not_persist_until_save(diary_path):
    diary, _, _ = populated(diary_path)
    diary.change_password(NEW_PASSWORD)
    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert len(reopened.entries) == 3


def test_saving_with_the_wrong_key_after_rekey_is_not_silently_mixed(diary_path):
    """Guards the cache-invalidation path: a save with a key that differs
    from the stored ciphertexts' key must re-encrypt everything, never
    leave records readable only by the previous key."""
    diary, old_key, _ = populated(diary_path)
    new_key = diary.change_password(NEW_PASSWORD)
    diary.save(new_key)

    reopened, _ = DiaryFile.unlock(diary_path, NEW_PASSWORD)
    assert len(reopened.entries) == 3
    with pytest.raises(ZecretDecryptError):
        DiaryFile.unlock(diary_path, PASSWORD)
    assert old_key != new_key


def test_full_lifecycle(diary_path):
    """create -> add -> save -> unlock -> edit -> delete -> rekey -> unlock."""
    diary, key = DiaryFile.create_new(diary_path, PASSWORD)
    keep, edit, drop = (Entry.new(day, f"Body {day}") for day in DAYS)
    for entry in (keep, edit, drop):
        diary.add_entry(entry)
    diary.save(key)

    diary, key = DiaryFile.unlock(diary_path, PASSWORD)
    diary.update_entry(diary.entries[edit.date].edited("Edited"))
    diary.delete_entry(drop.date)
    diary.save(key)

    diary, _ = DiaryFile.unlock(diary_path, PASSWORD)
    new_key = diary.change_password(NEW_PASSWORD)
    diary.save(new_key)

    final, _ = DiaryFile.unlock(diary_path, NEW_PASSWORD)
    assert set(final.entries) == {keep.date, edit.date}
    assert final.entries[edit.date].body == "Edited"
    assert final.entries[keep.date] == keep
    assert isinstance(next(iter(final.entries)), dt.date)


# --- verify_password -------------------------------------------------------


def test_verify_password_accepts_the_real_password(diary_path):
    diary, key, _ = populated(diary_path)
    assert diary.verify_password(PASSWORD, key) is True


def test_verify_password_rejects_a_wrong_password(diary_path):
    diary, key, _ = populated(diary_path)
    assert diary.verify_password(WRONG_PASSWORD, key) is False


def test_verify_password_rejects_an_empty_password(diary_path):
    diary, key, _ = populated(diary_path)
    assert diary.verify_password("", key) is False


def test_verify_password_follows_a_password_change(diary_path):
    """After a change the old password must stop verifying and the new one
    must start -- this is what guards the settings screen."""
    diary, _, _ = populated(diary_path)
    new_key = diary.change_password(NEW_PASSWORD)
    diary.save(new_key)
    assert diary.verify_password(NEW_PASSWORD, new_key) is True
    assert diary.verify_password(PASSWORD, new_key) is False


def test_verify_password_rejects_a_key_from_another_diary(tmp_path):
    """Same password, different diary: the salts differ, so the keys do."""
    first, first_key = DiaryFile.create_new(tmp_path / "a.enc", PASSWORD)
    _, second_key = DiaryFile.create_new(tmp_path / "b.enc", PASSWORD)
    assert first.verify_password(PASSWORD, first_key) is True
    assert first.verify_password(PASSWORD, second_key) is False


# --- malformed files, past the shapes already covered above ------------------


@pytest.mark.parametrize(
    "content",
    ['"a string"', "[]", "42", "null"],
    ids=["string", "list", "number", "null"],
)
def test_unlock_rejects_json_that_is_not_an_object(diary_path, content):
    diary_path.write_text(content)
    with pytest.raises(ValueError):
        DiaryFile.unlock(diary_path, PASSWORD)


@pytest.mark.parametrize("section", ["kdf", "entries"])
def test_unlock_rejects_a_missing_section(diary_path, section):
    populated(diary_path)
    document = read_document(diary_path)
    del document[section]
    diary_path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        DiaryFile.unlock(diary_path, PASSWORD)


@pytest.mark.parametrize("section", ["kdf", "verifier", "entries"])
def test_unlock_rejects_a_section_of_the_wrong_type(diary_path, section):
    populated(diary_path)
    document = read_document(diary_path)
    document[section] = "not what belongs here"
    diary_path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        DiaryFile.unlock(diary_path, PASSWORD)


def test_unlock_rejects_a_verifier_that_is_not_base64(diary_path):
    populated(diary_path)
    document = read_document(diary_path)
    document["verifier"]["nonce"] = "not base64!"
    diary_path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        DiaryFile.unlock(diary_path, PASSWORD)


def test_unlock_rejects_a_record_that_is_not_an_object(diary_path):
    populated(diary_path)
    document = read_document(diary_path)
    document["entries"][0] = "not a record"
    diary_path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        DiaryFile.unlock(diary_path, PASSWORD)


def test_a_directory_that_cannot_be_opened_does_not_fail_the_save(diary_path, monkeypatch):
    """The directory fsync is a durability nicety, not a correctness one:
    the file itself is already fsynced and renamed into place."""
    diary, key, _ = populated(diary_path)
    real_open = os.open

    def guarded_open(path, flags, *args, **kwargs):
        # Only the directory handle fails; the temp file still needs to open.
        if os.path.isdir(path):
            raise OSError("cannot open directory")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded_open)
    diary.add_entry(Entry.new(UNWRITTEN_DAY, "Body"))
    diary.save(key)

    monkeypatch.undo()
    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert UNWRITTEN_DAY in reopened.entries


def test_a_failing_directory_fsync_does_not_fail_the_save(diary_path, monkeypatch):
    diary, key, _ = populated(diary_path)
    real_fsync = os.fsync

    def fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("directory fsync unsupported")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    diary.add_entry(Entry.new(UNWRITTEN_DAY, "Body"))
    diary.save(key)

    monkeypatch.undo()
    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert UNWRITTEN_DAY in reopened.entries


def test_unlock_rejects_a_verifier_holding_the_wrong_plaintext(diary_path):
    """Fail closed even when the verifier decrypts cleanly: only the exact
    known plaintext counts as proof that this is the diary's key."""
    populated(diary_path)
    document = read_document(diary_path)
    key = derive_key(PASSWORD, KdfParams.from_dict(document["kdf"]))
    nonce, ciphertext = encrypt(key, b"not the verifier plaintext")
    document["verifier"] = {
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }
    diary_path.write_text(json.dumps(document))

    with pytest.raises(ZecretDecryptError):
        DiaryFile.unlock(diary_path, PASSWORD)
