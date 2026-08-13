"""On-disk file format and read/write logic for the Zecret diary file.

File format (JSON):
    {
        "version": 2,
        "kdf": {"algo": "argon2id", "salt": "<base64>", "time_cost": 3,
                "memory_cost": 65536, "parallelism": 4},
        "verifier": {"nonce": "<base64>", "ciphertext": "<base64>"},
        "entries": [
            {"date": "YYYY-MM-DD", "nonce": "<base64>",
             "ciphertext": "<base64>"},
            ...
        ]
    }

Version 1 keyed entries by a per-entry UUID and gave each one a title. It
was replaced by the one-entry-per-day model before any diary depended on
it, so there is no migration: _load_document() rejects a version it does
not know rather than misreading it. A future format change adds a
migration here, keyed off `version`.

Note what the record date does and does not give away. Each entry's text is
inside its ciphertext, but the days you wrote on are readable by anyone
holding the file -- it leaks the shape of the habit, not its content. That
is the price of being able to name a record without decrypting it, which is
what makes the outer/inner date check below possible.

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

A save also refuses to overwrite a file that changed since this DiaryFile
last read or wrote it. Two Zecrets open on the same diary each hold the
whole thing in memory, so without that check the second one to save would
write its own copy over the first's and take those entries with it --
silently, since neither would have any reason to complain. The check turns
that into ZecretConflictError.

No plaintext ever touches this module -- it only ever handles the encrypted
JSON structure plus opaque nonce/ciphertext bytes.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from zecret.crypto import KdfParams, ZecretDecryptError, decrypt, derive_key, encrypt
from zecret.models import Entry

DEFAULT_DIARY_PATH = Path.home() / ".zecret" / "diary.enc"
FORMAT_VERSION = 2

FILE_MODE = 0o600
DIR_MODE = 0o700

# Known plaintext encrypted under the derived key, so a wrong password is
# detectable even when the diary holds no entries.
VERIFIER_PLAINTEXT = b"zecret-key-check-v1"


class ZecretConflictError(Exception):
    """Raised when the diary file changed since this session read it.

    Almost always a second Zecret open on the same file. Distinct from an
    OSError: nothing is wrong with the disk, and the save is refused rather
    than failed -- the entries are still in memory, and the file on disk is
    still whatever the other session wrote.
    """


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
    decrypted entries, keyed by date -- one entry per day -- for O(1)
    lookup of the day the user is writing about. Unordered: callers sort
    by date for display.
    """

    path: Path
    kdf_params: KdfParams
    entries: dict[dt.date, Entry]

    # Ciphertexts as they currently exist on disk, and a fingerprint of the
    # key they were produced with. Private: callers work with `entries`.
    _records: dict[dt.date, _Record] = field(default_factory=dict, repr=False)
    _records_key: bytes | None = field(default=None, repr=False)
    # What the file looked like when this session last read or wrote it, so
    # save() can tell whether anyone else has been at it. None until the
    # first successful write.
    _file_stamp: tuple[int, int] | None = field(default=None, repr=False)

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

        entries: dict[dt.date, Entry] = {}
        records: dict[dt.date, _Record] = {}
        for raw in document["entries"]:
            record_date, nonce, ciphertext = _parse_record(raw)
            # Decrypt before trusting anything: ZecretDecryptError from here
            # is what the unlock screen turns into "incorrect password".
            entry = Entry.from_json_bytes(decrypt(key, nonce, ciphertext))
            # The record date sits outside the AEAD and so is
            # unauthenticated; the date inside the ciphertext is
            # authenticated. Requiring them to match keeps a tampered index
            # from filing an entry under the wrong day.
            if entry.date != record_date:
                raise ValueError(f"entry date mismatch for record {record_date}")
            if entry.date in entries:
                raise ValueError(f"duplicate entry for {entry.date}")
            entries[entry.date] = entry
            records[entry.date] = _Record(entry, nonce, ciphertext)

        diary = cls(path=path, kdf_params=kdf_params, entries=entries)
        diary._records = records
        diary._records_key = _key_fingerprint(key)
        diary._file_stamp = _file_stamp(path)
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

        Raises:
            ZecretConflictError: if the file changed since this session
                read or wrote it. In-memory state is left untouched, so the
                caller can report it and keep whatever the user typed.
            OSError: if the write itself fails.
        """
        self._check_unchanged()
        fingerprint = _key_fingerprint(key)
        reusable = self._records if fingerprint == self._records_key else {}

        records: dict[dt.date, _Record] = {}
        payload: list[dict[str, str]] = []
        # Written newest first, so the file's own order matches how the
        # diary reads; nothing depends on it, since unlock() keys by date.
        for date in sorted(self.entries, reverse=True):
            entry = self.entries[date]
            cached = reusable.get(date)
            if cached is not None and cached.entry == entry:
                record = cached
            else:
                nonce, ciphertext = encrypt(key, entry.to_json_bytes())
                record = _Record(entry, nonce, ciphertext)
            records[date] = record
            payload.append(
                {
                    "date": date.isoformat(),
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
        self._file_stamp = _file_stamp(self.path)

    def _check_unchanged(self) -> None:
        """Refuse to write over a file someone else has written.

        Compares the file's modification time and size against what they
        were when this session last read or wrote it. Not a lock: two
        saves in the same filesystem timestamp tick, at the same size,
        would slip through. That needs two Zecrets saving the same diary
        within one clock granularity of each other, which human typing
        does not produce -- and the alternative, holding a lock across an
        interactive session, would leave a stale lockfile behind every
        time the terminal was closed.

        A file that has since been deleted is not a conflict: there is
        nothing to overwrite, and writing it back restores the diary.

        Raises:
            ZecretConflictError: if the file no longer matches.
        """
        if self._file_stamp is None:
            return
        current = _file_stamp(self.path)
        if current is not None and current != self._file_stamp:
            raise ZecretConflictError(
                f"{self.path} changed since it was opened; another Zecret may have it open"
            )

    def entry_for(self, date: dt.date) -> Entry | None:
        """The entry written for `date`, or None if that day is unwritten.

        How the editor decides between creating a day's entry and opening
        the existing one -- a day holds at most one, so this is the whole
        question.
        """
        return self.entries.get(date)

    def add_entry(self, entry: Entry) -> None:
        """Add a new entry to the in-memory store (does not persist to disk).

        Raises:
            ValueError: if that day already has an entry. One entry per
                day is the model, so use update_entry() to replace it.
        """
        if entry.date in self.entries:
            raise ValueError(f"an entry already exists for {entry.date}")
        self.entries[entry.date] = entry

    def update_entry(self, entry: Entry) -> None:
        """Replace an existing entry (matched by entry.date) in the in-memory store.

        Raises:
            KeyError: if that day has no entry yet.
        """
        if entry.date not in self.entries:
            raise KeyError(entry.date)
        self.entries[entry.date] = entry

    def delete_entry(self, date: dt.date) -> None:
        """Remove a day's entry from the in-memory store.

        Raises:
            KeyError: if that day has no entry.
        """
        del self.entries[date]
        # Drop the cached copy too: no reason to keep a deleted entry's
        # plaintext alive in memory until the next save.
        self._records.pop(date, None)

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


def _file_stamp(path: Path) -> tuple[int, int] | None:
    """(mtime, size) for `path`, or None if it is not there to stat.

    Enough to notice another process rewriting the diary, without reading
    it back in full on every save.
    """
    try:
        status = path.stat()
    except OSError:
        return None
    return status.st_mtime_ns, status.st_size


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


def _parse_record(raw: object) -> tuple[dt.date, bytes, bytes]:
    """Pull (date, nonce, ciphertext) out of one on-disk entry record."""
    if not isinstance(raw, dict):
        raise ValueError("entry record must be a JSON object")
    try:
        return (
            dt.date.fromisoformat(raw["date"]),
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
