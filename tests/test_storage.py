"""Tests for zecret.storage.

Required coverage (fill in as storage.py is implemented):
    - create_new() writes a valid, parseable diary file with zero entries.
    - unlock() with the correct password returns all entries decrypted
      correctly (round-trip through create_new -> add -> save -> unlock).
    - unlock() with the wrong password raises ZecretDecryptError.
    - unlock() on a nonexistent path raises FileNotFoundError.
    - add_entry() + save() + unlock() persists the new entry.
    - update_entry() + save() + unlock() reflects the edit, and confirms
      OTHER entries' ciphertexts are unchanged (proves independent
      per-entry encryption -- edit one entry without touching others).
    - delete_entry() + save() + unlock() confirms the entry is gone and
      no other entries are affected.
    - save() is atomic: simulate/verify no partial file is left if
      interrupted (e.g. check a temp file is used and renamed).
    - change_password() + save() + unlock() with the NEW password succeeds,
      and unlock() with the OLD password now fails.
"""

from __future__ import annotations

import base64
import json
import os
import stat
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from zecret.crypto import KdfParams, ZecretDecryptError
from zecret.models import Entry
from zecret.storage import DEFAULT_DIARY_PATH, FORMAT_VERSION, DiaryFile

PASSWORD = "correct horse battery staple"
WRONG_PASSWORD = "Correct horse battery staple"
NEW_PASSWORD = "an entirely different passphrase"

# Argon2 at the real defaults costs ~30ms per derivation, and these tests
# unlock constantly. Patch the cost factors down; the code path is
# identical, only the work factor changes.
CHEAP_KDF = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


@pytest.fixture(autouse=True)
def cheap_kdf(monkeypatch):
    """Keep real Argon2id, but at test-speed cost factors."""
    original = KdfParams.generate

    def generate() -> KdfParams:
        return KdfParams(salt=original().salt, **CHEAP_KDF)

    monkeypatch.setattr(KdfParams, "generate", staticmethod(generate))


@pytest.fixture
def diary_path(tmp_path: Path) -> Path:
    return tmp_path / "diary.enc"


def read_document(path: Path) -> dict:
    return json.loads(path.read_bytes().decode("utf-8"))


def ciphertexts_by_id(path: Path) -> dict[str, str]:
    return {rec["id"]: rec["ciphertext"] for rec in read_document(path)["entries"]}


def nonces_by_id(path: Path) -> dict[str, str]:
    return {rec["id"]: rec["nonce"] for rec in read_document(path)["entries"]}


def populated(diary_path: Path) -> tuple[DiaryFile, bytes, list[Entry]]:
    """A saved diary with three entries."""
    diary, key = DiaryFile.create_new(diary_path, PASSWORD)
    entries = [Entry.new(f"Title {i}", f"Body of entry {i}") for i in range(3)]
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
    assert reopened.entries == {entry.id: entry for entry in entries}


def test_unlock_round_trips_entry_content_exactly(diary_path):
    diary, key = DiaryFile.create_new(diary_path, PASSWORD)
    entry = Entry.new("Título ✨", 'Multi-line\nbody with 日本語 and "quotes"')
    diary.add_entry(entry)
    diary.save(key)

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    restored = reopened.entries[entry.id]
    assert restored == entry
    assert restored.title == entry.title
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
    diary.add_entry(Entry.new("Another", "Body"))
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


def test_unlock_rejects_record_id_that_disagrees_with_ciphertext(diary_path):
    """The record id is outside the AEAD; the id inside the entry is not.
    Repointing a record must not silently relabel an entry."""
    populated(diary_path)
    document = read_document(diary_path)
    document["entries"][0]["id"] = str(uuid4())
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


# --- add / update / delete -------------------------------------------------


def test_add_entry_then_save_then_unlock_persists_it(diary_path):
    diary, key = DiaryFile.create_new(diary_path, PASSWORD)
    entry = Entry.new("A new entry", "Body text")
    diary.add_entry(entry)
    diary.save(key)

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entries == {entry.id: entry}


def test_add_entry_does_not_touch_disk_until_save(diary_path):
    diary, _ = DiaryFile.create_new(diary_path, PASSWORD)
    diary.add_entry(Entry.new("Unsaved", "Body"))
    assert read_document(diary_path)["entries"] == []


def test_add_entry_rejects_duplicate_id(diary_path):
    diary, _ = DiaryFile.create_new(diary_path, PASSWORD)
    entry = Entry.new("Title", "Body")
    diary.add_entry(entry)
    with pytest.raises(ValueError):
        diary.add_entry(entry)


def test_update_entry_then_save_then_unlock_reflects_the_edit(diary_path):
    diary, key, entries = populated(diary_path)
    edited = entries[1].edited(title="Edited title", body="Edited body")
    diary.update_entry(edited)
    diary.save(key)

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entries[edited.id] == edited
    assert reopened.entries[edited.id].title == "Edited title"
    assert len(reopened.entries) == 3


def test_update_entry_leaves_other_ciphertexts_byte_identical(diary_path):
    """CLAUDE.md requirement 6: per-entry independent encryption. Editing
    one entry must not re-encrypt any other entry's record."""
    diary, key, entries = populated(diary_path)
    before = ciphertexts_by_id(diary_path)
    before_nonces = nonces_by_id(diary_path)

    diary.update_entry(entries[1].edited(body="Edited body"))
    diary.save(key)

    after = ciphertexts_by_id(diary_path)
    after_nonces = nonces_by_id(diary_path)
    untouched = [str(entries[0].id), str(entries[2].id)]
    for entry_id in untouched:
        assert after[entry_id] == before[entry_id], "unrelated ciphertext was rewritten"
        assert after_nonces[entry_id] == before_nonces[entry_id]
    assert after[str(entries[1].id)] != before[str(entries[1].id)], "edit was not encrypted"


def test_repeated_save_without_changes_rewrites_no_ciphertext(diary_path):
    diary, key, _ = populated(diary_path)
    before = ciphertexts_by_id(diary_path)
    diary.save(key)
    assert ciphertexts_by_id(diary_path) == before


def test_update_entry_reencrypts_with_a_fresh_nonce(diary_path):
    """The edited entry itself must get a new nonce -- never reuse the old
    one with the same key."""
    diary, key, entries = populated(diary_path)
    before = nonces_by_id(diary_path)[str(entries[1].id)]
    diary.update_entry(entries[1].edited(body="Edited body"))
    diary.save(key)
    assert nonces_by_id(diary_path)[str(entries[1].id)] != before


def test_update_entry_rejects_unknown_id(diary_path):
    diary, _, _ = populated(diary_path)
    with pytest.raises(KeyError):
        diary.update_entry(Entry.new("Never added", "Body"))


def test_delete_entry_then_save_then_unlock_removes_only_that_entry(diary_path):
    diary, key, entries = populated(diary_path)
    diary.delete_entry(entries[1].id)
    diary.save(key)

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert entries[1].id not in reopened.entries
    assert reopened.entries == {entries[0].id: entries[0], entries[2].id: entries[2]}


def test_delete_entry_leaves_other_ciphertexts_byte_identical(diary_path):
    diary, key, entries = populated(diary_path)
    before = ciphertexts_by_id(diary_path)

    diary.delete_entry(entries[1].id)
    diary.save(key)

    after = ciphertexts_by_id(diary_path)
    assert str(entries[1].id) not in after
    for entry_id in (str(entries[0].id), str(entries[2].id)):
        assert after[entry_id] == before[entry_id], "unrelated ciphertext was rewritten"


def test_delete_entry_rejects_unknown_id(diary_path):
    diary, _, _ = populated(diary_path)
    with pytest.raises(KeyError):
        diary.delete_entry(uuid4())


def test_deleted_entry_does_not_come_back_after_reunlock(diary_path):
    diary, key, entries = populated(diary_path)
    diary.delete_entry(entries[0].id)
    diary.save(key)
    reopened, reopened_key = DiaryFile.unlock(diary_path, PASSWORD)
    reopened.save(reopened_key)
    final, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert entries[0].id not in final.entries


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
    diary.add_entry(Entry.new("Another", "Body"))
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
    diary.add_entry(Entry.new("Another", "Body"))
    diary.save(key)

    assert order.index("fsync") < order.index("replace")


def test_interrupted_save_leaves_the_original_file_intact(diary_path, monkeypatch):
    diary, key, entries = populated(diary_path)
    before = diary_path.read_bytes()

    def boom(src, dst):
        raise OSError("simulated crash during rename")

    monkeypatch.setattr(os, "replace", boom)
    diary.add_entry(Entry.new("Doomed", "Body"))
    with pytest.raises(OSError):
        diary.save(key)

    assert diary_path.read_bytes() == before, "diary was damaged by a failed save"
    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert reopened.entries == {entry.id: entry for entry in entries}


def test_interrupted_save_leaves_no_temp_file_behind(diary_path, monkeypatch):
    diary, key, _ = populated(diary_path)

    monkeypatch.setattr(os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError("boom")))
    diary.add_entry(Entry.new("Doomed", "Body"))
    with pytest.raises(OSError):
        diary.save(key)

    leftovers = [p.name for p in diary_path.parent.iterdir() if p != diary_path]
    assert leftovers == [], f"temp files left behind: {leftovers}"


def test_failed_save_does_not_poison_the_ciphertext_cache(diary_path, monkeypatch):
    """After a failed save the cache must still describe what is on disk,
    so the next successful save writes a complete, consistent file."""
    diary, key, entries = populated(diary_path)
    new_entry = Entry.new("Added during failure", "Body")

    monkeypatch.setattr(os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError("boom")))
    diary.add_entry(new_entry)
    with pytest.raises(OSError):
        diary.save(key)

    monkeypatch.undo()
    diary.save(key)

    reopened, _ = DiaryFile.unlock(diary_path, PASSWORD)
    assert set(reopened.entries) == {entry.id for entry in entries} | {new_entry.id}


def test_save_never_writes_plaintext_into_the_file(diary_path):
    """Requirement 4: no plaintext on disk, in any field."""
    diary, key = DiaryFile.create_new(diary_path, PASSWORD)
    entry = Entry.new("UNIQUETITLEMARKER", "UNIQUEBODYMARKER")
    diary.add_entry(entry)
    diary.save(key)

    raw = diary_path.read_bytes()
    assert b"UNIQUETITLEMARKER" not in raw
    assert b"UNIQUEBODYMARKER" not in raw
    assert PASSWORD.encode() not in raw


# --- change_password -------------------------------------------------------


def test_change_password_then_save_then_unlock_with_new_password(diary_path):
    diary, _, entries = populated(diary_path)
    new_key = diary.change_password(NEW_PASSWORD)
    diary.save(new_key)

    reopened, _ = DiaryFile.unlock(diary_path, NEW_PASSWORD)
    assert reopened.entries == {entry.id: entry for entry in entries}


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
    before = ciphertexts_by_id(diary_path)
    new_key = diary.change_password(NEW_PASSWORD)
    diary.save(new_key)

    after = ciphertexts_by_id(diary_path)
    assert set(after) == set(before)
    for entry_id, ciphertext in after.items():
        assert ciphertext != before[entry_id], "entry still encrypted under the old key"


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
    keep, edit, drop = (Entry.new(f"T{i}", f"B{i}") for i in range(3))
    for entry in (keep, edit, drop):
        diary.add_entry(entry)
    diary.save(key)

    diary, key = DiaryFile.unlock(diary_path, PASSWORD)
    diary.update_entry(diary.entries[edit.id].edited(title="Edited"))
    diary.delete_entry(drop.id)
    diary.save(key)

    diary, _ = DiaryFile.unlock(diary_path, PASSWORD)
    new_key = diary.change_password(NEW_PASSWORD)
    diary.save(new_key)

    final, _ = DiaryFile.unlock(diary_path, NEW_PASSWORD)
    assert set(final.entries) == {keep.id, edit.id}
    assert final.entries[edit.id].title == "Edited"
    assert final.entries[keep.id] == keep
    assert isinstance(next(iter(final.entries)), UUID)


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
