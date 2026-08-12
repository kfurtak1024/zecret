"""On-disk file format and read/write logic for the Zecret diary file.

File format (JSON):
    {
        "version": 1,
        "kdf": {"algo": "argon2id", "salt": "<base64>", "time_cost": 3,
                "memory_cost": 65536, "parallelism": 4},
        "verifier": {"nonce": "<base64>", "ciphertext": "<base64>"},
        "entries": [
            {"id": "<uuid>", "nonce": "<base64>", "ciphertext": "<base64>"},
            ...
        ]
    }

The verifier is a fixed known plaintext encrypted under the derived key.
Without it, a diary holding no entries has no ciphertext to authenticate
against, so any password would "open" it and the next save would silently
re-key the file to that wrong password. Checking it makes unlock() reject a
wrong password even for an empty diary (CLAUDE.md requirement 7: never
default to an empty diary).

Each entry's ciphertext independently decrypts (via crypto.decrypt) to the
JSON produced by Entry.to_json_bytes(). This means editing or deleting one
entry never requires touching any other entry's ciphertext: save() reuses
the stored nonce/ciphertext verbatim for every entry whose plaintext has
not changed, and only encrypts entries that are new or modified. A password
change re-keys the whole file, which is the one case where every record is
necessarily re-encrypted.

Writes are always atomic: content is written to a temp file in the same
directory, fsync'd, then renamed over the target path. This guarantees the
diary file is never left half-written if the process is interrupted.

No plaintext ever touches this module -- it only ever handles the encrypted
JSON structure plus opaque nonce/ciphertext bytes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self
from uuid import UUID

from zecret.crypto import KdfParams, ZecretDecryptError, decrypt, derive_key, encrypt
from zecret.models import Entry

DEFAULT_DIARY_PATH = Path.home() / ".zecret" / "diary.enc"
FORMAT_VERSION = 1

FILE_MODE = 0o600
DIR_MODE = 0o700

# Known plaintext encrypted under the derived key, so a wrong password is
# detectable even when the diary holds no entries.
VERIFIER_PLAINTEXT = b"zecret-key-check-v1"


@dataclass(frozen=True, slots=True)
class _Record:
    """A stored entry: the ciphertext plus the entry it encrypts.

    Entry is frozen, so holding the reference is enough for save() to tell
    whether an entry changed since it was last encrypted -- an edit produces
    a new instance -- and unchanged entries keep their existing bytes.
    """

    entry: Entry
    nonce: bytes
    ciphertext: bytes


@dataclass(slots=True)
class DiaryFile:
    """In-memory representation of an unlocked diary.

    Holds the KDF params (needed if the password is ever changed) and the
    decrypted entries, keyed by id for O(1) edit/delete lookup.
    """

    path: Path
    kdf_params: KdfParams
    entries: dict[UUID, Entry]

    # Ciphertexts as they currently exist on disk, and a fingerprint of the
    # key they were produced with. Private: callers work with `entries`.
    _records: dict[UUID, _Record] = field(default_factory=dict, repr=False)
    _records_key: bytes | None = field(default=None, repr=False)

    @classmethod
    def create_new(cls, path: Path, password: str) -> tuple[Self, bytes]:
        """Initialize a brand-new, empty diary at `path` protected by `password`.

        Generates fresh KdfParams, derives the key, and writes an empty
        diary file to disk. Raises if a file already exists at `path`.

        Returns:
            The new DiaryFile and the derived key. The key is returned
            rather than stored on the instance because screens may not call
            crypto.derive_key() themselves -- they hold it as `app.key` and
            pass it back to save().

        Raises:
            FileExistsError: if `path` already exists. Overwriting would
                destroy a diary whose password we have not verified.
        """
        if path.exists():
            raise FileExistsError(f"a diary already exists at {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        _restrict(path.parent, DIR_MODE)

        kdf_params = KdfParams.generate()
        key = derive_key(password, kdf_params)
        diary = cls(path=path, kdf_params=kdf_params, entries={})
        diary.save(key)
        return diary, key

    @classmethod
    def unlock(cls, path: Path, password: str) -> tuple[Self, bytes]:
        """Open an existing diary file and decrypt all entries with `password`.

        Returns:
            The unlocked DiaryFile and the derived key (see create_new()
            for why the key comes back to the caller).

        Raises:
            FileNotFoundError: if no diary exists at `path`.
            zecret.crypto.ZecretDecryptError: if the password is wrong.
            ValueError: if the file is not a diary we can parse, or is a
                format version this build does not understand.
        """
        document = _load_document(path)
        kdf_params = KdfParams.from_dict(document["kdf"])
        key = derive_key(password, kdf_params)
        _check_verifier(key, document["verifier"])

        entries: dict[UUID, Entry] = {}
        records: dict[UUID, _Record] = {}
        for raw in document["entries"]:
            record_id, nonce, ciphertext = _parse_record(raw)
            # Decrypt before trusting anything: ZecretDecryptError from here
            # is what the unlock screen turns into "incorrect password".
            entry = Entry.from_json_bytes(decrypt(key, nonce, ciphertext))
            # The record id sits outside the AEAD and so is unauthenticated;
            # the id inside the ciphertext is authenticated. Requiring them
            # to match keeps a tampered index from repointing an entry.
            if entry.id != record_id:
                raise ValueError(f"entry id mismatch for record {record_id}")
            if entry.id in entries:
                raise ValueError(f"duplicate entry id: {entry.id}")
            entries[entry.id] = entry
            records[entry.id] = _Record(entry, nonce, ciphertext)

        diary = cls(path=path, kdf_params=kdf_params, entries=entries)
        diary._records = records
        diary._records_key = _key_fingerprint(key)
        return diary, key

    def save(self, key: bytes) -> None:
        """Encrypt any new or modified entries under `key` and atomically
        write the whole diary to self.path.

        Entries whose plaintext is unchanged since they were loaded or last
        saved keep their existing nonce and ciphertext byte-for-byte, so
        editing one entry never re-encrypts any other (CLAUDE.md security
        requirement 6). When `key` differs from the key the stored
        ciphertexts were produced with -- i.e. after change_password() --
        every entry is necessarily re-encrypted.

        Called after any add/edit/delete, and after a password change (with
        the new key and new self.kdf_params already set).
        """
        fingerprint = _key_fingerprint(key)
        reusable = self._records if fingerprint == self._records_key else {}

        records: dict[UUID, _Record] = {}
        payload: list[dict[str, str]] = []
        for entry_id, entry in self.entries.items():
            cached = reusable.get(entry_id)
            if cached is not None and cached.entry == entry:
                record = cached
            else:
                nonce, ciphertext = encrypt(key, entry.to_json_bytes())
                record = _Record(entry, nonce, ciphertext)
            records[entry_id] = record
            payload.append(
                {
                    "id": str(entry_id),
                    "nonce": _b64(record.nonce),
                    "ciphertext": _b64(record.ciphertext),
                }
            )

        verifier_nonce, verifier_ciphertext = encrypt(key, VERIFIER_PLAINTEXT)
        document = {
            "version": FORMAT_VERSION,
            "kdf": self.kdf_params.to_dict(),
            "verifier": {
                "nonce": _b64(verifier_nonce),
                "ciphertext": _b64(verifier_ciphertext),
            },
            "entries": payload,
        }
        _atomic_write(self.path, json.dumps(document).encode("utf-8"))

        # Only adopt the new records once the write has actually landed, so
        # a failed save leaves the cache describing what is really on disk.
        self._records = records
        self._records_key = fingerprint

    def add_entry(self, entry: Entry) -> None:
        """Add a new entry to the in-memory store (does not persist to disk).

        Raises:
            ValueError: if an entry with this id is already present. Use
                update_entry() to replace one.
        """
        if entry.id in self.entries:
            raise ValueError(f"entry already exists: {entry.id}")
        self.entries[entry.id] = entry

    def update_entry(self, entry: Entry) -> None:
        """Replace an existing entry (matched by entry.id) in the in-memory store.

        Raises:
            KeyError: if no entry with this id exists.
        """
        if entry.id not in self.entries:
            raise KeyError(entry.id)
        self.entries[entry.id] = entry

    def delete_entry(self, entry_id: UUID) -> None:
        """Remove an entry from the in-memory store by id.

        Raises:
            KeyError: if no entry with this id exists.
        """
        del self.entries[entry_id]
        # Drop the cached copy too: no reason to keep a deleted entry's
        # plaintext alive in memory until the next save.
        self._records.pop(entry_id, None)

    def verify_password(self, password: str, key: bytes) -> bool:
        """Whether `password` derives `key` under this diary's KDF params.

        Screens may not call crypto.derive_key() themselves, so this is how
        the settings screen re-checks the current password before allowing
        a change. Compared in constant time.

        Args:
            password: The password to check.
            key: The key the session was unlocked with (app.key).
        """
        return hmac.compare_digest(derive_key(password, self.kdf_params), key)

    def change_password(self, new_password: str) -> bytes:
        """Rotate to a new password: generate new KdfParams, derive new key.

        A fresh salt is generated, so the new key is unrelated to the old
        one even if the user reuses a password.

        Returns the new key. Caller must still call save(new_key) to persist
        the diary re-encrypted under the new key.
        """
        self.kdf_params = KdfParams.generate()
        return derive_key(new_password, self.kdf_params)


def _key_fingerprint(key: bytes) -> bytes:
    """A short, non-reversible tag identifying a key.

    Lets save() notice that it was handed a different key than the stored
    ciphertexts were made with, without DiaryFile retaining key material.
    """
    return hashlib.blake2b(key, digest_size=16, person=b"zecret-keyid").digest()


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _load_document(path: Path) -> dict[str, Any]:
    """Read and structurally validate the diary file at `path`.

    Raises:
        FileNotFoundError: if `path` does not exist.
        ValueError: if the contents are not a diary of a known version.
    """
    raw = path.read_bytes()
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"not a readable diary file: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("diary file must contain a JSON object")

    version = document.get("version")
    if version != FORMAT_VERSION:
        # Keyed off `version` by design: future formats add a migration
        # here rather than silently misreading an old file.
        raise ValueError(f"unsupported diary format version: {version!r}")
    if not isinstance(document.get("kdf"), dict):
        raise ValueError("diary file is missing its kdf header")
    if not isinstance(document.get("verifier"), dict):
        raise ValueError("diary file is missing its key verifier")
    if not isinstance(document.get("entries"), list):
        raise ValueError("diary file is missing its entries list")
    return document


def _check_verifier(key: bytes, verifier: dict[str, Any]) -> None:
    """Confirm `key` is the diary's key before reading any entries.

    Raises:
        ZecretDecryptError: if the password is wrong. Raised for a verifier
            that fails to decrypt *and* for one that decrypts to the wrong
            constant, so neither case can be mistaken for a valid unlock.
        ValueError: if the verifier record itself is malformed.
    """
    try:
        nonce = base64.b64decode(verifier["nonce"], validate=True)
        ciphertext = base64.b64decode(verifier["ciphertext"], validate=True)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed key verifier: {exc}") from exc

    if decrypt(key, nonce, ciphertext) != VERIFIER_PLAINTEXT:
        raise ZecretDecryptError("diary key verifier did not match")


def _parse_record(raw: object) -> tuple[UUID, bytes, bytes]:
    """Pull (id, nonce, ciphertext) out of one on-disk entry record."""
    if not isinstance(raw, dict):
        raise ValueError("entry record must be a JSON object")
    try:
        return (
            UUID(raw["id"]),
            base64.b64decode(raw["nonce"], validate=True),
            base64.b64decode(raw["ciphertext"], validate=True),
        )
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"malformed entry record: {exc}") from exc


def _atomic_write(path: Path, data: bytes) -> None:
    """Write `data` to `path` atomically, never leaving a partial file.

    Writes to a temp file in the same directory (same filesystem, so the
    rename is atomic), fsyncs it, then os.replace()s it over the target. On
    any failure the temp file is removed and the existing file is left
    exactly as it was.
    """
    directory = path.parent
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _restrict(tmp_path, FILE_MODE)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    _fsync_directory(directory)


def _restrict(target: Path, mode: int) -> None:
    """Best-effort chmod: the diary is private to its owner.

    Best-effort because some filesystems (e.g. a Windows or FAT-backed
    mount) do not support POSIX modes; the diary is still encrypted there.
    """
    with suppress(OSError):
        os.chmod(target, mode)


def _fsync_directory(directory: Path) -> None:
    """Best-effort fsync of a directory, so the rename itself is durable."""
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)
