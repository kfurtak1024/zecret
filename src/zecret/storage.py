"""On-disk file format and read/write logic for the Zecret diary file.

File format (JSON):
    {
        "version": 1,
        "kdf": {"algo": "argon2id", "salt": "<base64>", "time_cost": 3,
                "memory_cost": 65536, "parallelism": 4},
        "verifier": {"nonce": "<base64>", "ciphertext": "<base64>"},
        "entries": [
            {"date": "YYYY-MM-DD", "nonce": "<base64>",
             "ciphertext": "<base64>"},
            ...
        ]
    }

**Version.** The format is version 1 and that number is frozen. A change
to the format bumps it and adds a migration here, keyed off `version`.
_load_document() refuses any version it does not know.

**Record dates** sit outside the ciphertext, so the file reveals which days
have entries, though nothing of what they say. That is what lets a record
be named without decrypting it, and the date inside the ciphertext is
checked against it.

**The verifier** is a fixed plaintext encrypted under the derived key. It
is what makes a wrong password detectable on a diary with no entries, and
it is checked before any entry is read.

**Per-entry encryption.** Each entry decrypts on its own to the JSON from
Entry.to_json_bytes(). save() reuses the stored nonce and ciphertext for
every unchanged entry and encrypts only new or modified ones. A password
change re-encrypts everything.

**Integrity is per record, not per file.** Nothing authenticates the list
of records as a whole: a record removed from the file, or replaced by an
older ciphertext of the same day, still opens. See SECURITY.md.

**Writes are atomic**: a temp file in the same directory, fsync, then a
rename over the target. Creating a diary is the exception; see
_create_exclusively().

**Conflicts.** A save refuses to overwrite a file that changed since this
DiaryFile last read or wrote it (ZecretConflictError), so two Zecrets open
on one diary cannot silently write over each other.

No plaintext is written by this module.
"""

from __future__ import annotations

import base64
import datetime as dt
import glob
import hashlib
import hmac
import json
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from zecret.crypto import KdfParams, ZecretDecryptError, decrypt, derive_key, encrypt
from zecret.models import Entry

DEFAULT_DIARY_PATH = Path.home() / ".zecret" / "diary.enc"
FORMAT_VERSION = 1

FILE_MODE = 0o600
DIR_MODE = 0o700

TEMP_SUFFIX = ".tmp"
#: How old a leftover temp file must be before a save removes it. A write
#: takes milliseconds, so anything this old belongs to a process that died.
STALE_TEMP_SECONDS = 60

# Known plaintext encrypted under the derived key, so a wrong password is
# detectable even when the diary holds no entries.
VERIFIER_PLAINTEXT = b"zecret-key-check-v1"


class ZecretDamagedError(ValueError):
    """The password is right but the diary file is damaged.

    Raised only after the key verifier has decrypted, which proves the
    key. A record that then fails to decrypt or parse, disagrees with its
    own date, or repeats a day is damage, not a wrong password.

    Still a refusal: the diary does not open. A ValueError, so code that
    catches an unreadable file catches this too.
    """


class ZecretVersionError(ValueError):
    """The diary was written in a format newer than this build reads.

    The remedy is to upgrade; nothing is wrong with the file. Checked
    before any key is derived.
    """


class ZecretConflictError(Exception):
    """The diary file changed since this session read it.

    Almost always a second Zecret open on the same file. The save is
    refused rather than failed: the entries are still in memory, and the
    file is whatever the other session wrote.
    """


@dataclass(frozen=True, slots=True)
class _Record:
    """A stored entry: the ciphertext plus the entry it encrypts.

    Entry is frozen, so save() can tell from this whether an entry changed
    since it was last encrypted.
    """

    entry: Entry
    nonce: bytes
    ciphertext: bytes


@dataclass(slots=True)
class DiaryFile:
    """An unlocked diary in memory.

    Holds the KDF params and the decrypted entries keyed by date.
    Unordered: callers sort for display.
    """

    path: Path
    kdf_params: KdfParams
    # Out of the repr, as Entry.body is: a traceback has no business
    # printing the diary.
    entries: dict[dt.date, Entry] = field(repr=False)

    # The ciphertexts as they are on disk, and a fingerprint of the key
    # they were produced with.
    _records: dict[dt.date, _Record] = field(default_factory=dict, repr=False)
    _records_key: bytes | None = field(default=None, repr=False)
    # (mtime, size) of the file when this session last read or wrote it.
    _file_stamp: tuple[int, int] | None = field(default=None, repr=False)

    @classmethod
    def create_new(cls, path: Path, password: str) -> tuple[Self, bytes]:
        """Create an empty diary at `path` protected by `password`.

        Returns:
            The new DiaryFile and the derived key. The key is returned
            because screens may not call crypto.derive_key() themselves.

        Raises:
            FileExistsError: if `path` already exists. The check below
                only fails fast, before paying for Argon2; what makes this
                safe is the exclusive write in _write().
        """
        if path.exists():
            raise FileExistsError(f"a diary already exists at {path}")
        _make_private_directory(path.parent)

        kdf_params = KdfParams.generate()
        key = derive_key(password, kdf_params)
        diary = cls(path=path, kdf_params=kdf_params, entries={})
        diary._write(key, exclusive=True)
        return diary, key

    @classmethod
    def unlock(cls, path: Path, password: str) -> tuple[Self, bytes]:
        """Open an existing diary and decrypt all entries with `password`.

        Returns:
            The unlocked DiaryFile and the derived key.

        Raises:
            FileNotFoundError: if no diary exists at `path`.
            zecret.crypto.ZecretDecryptError: if the password is wrong.
            ZecretDamagedError: if the password is right and the file is
                damaged past the verifier.
            ZecretVersionError: if a newer Zecret wrote the file.
            ValueError: if the file is not a diary we can parse.
            MemoryError: if Argon2 could not get the memory it needs.
        """
        document, stamp = _load_document(path)
        kdf_params = KdfParams.from_dict(document["kdf"])
        key = derive_key(password, kdf_params)
        return cls._decrypted(path, document, stamp, kdf_params, key), key

    @classmethod
    def reopen(cls, path: Path, key: bytes) -> Self:
        """Read the diary again with a key this session already holds.

        For picking up what another Zecret wrote, without retyping a
        password. If the other session changed the password, this key
        opens nothing and ZecretDecryptError says so.

        Returns:
            A new DiaryFile. The old one is left alone, so a reload that
            fails does not empty the diary the session holds.

        Raises:
            FileNotFoundError: if the diary has since been deleted.
            zecret.crypto.ZecretDecryptError: if `key` no longer opens it.
            ZecretDamagedError, ZecretVersionError: as for unlock().
            ValueError: if the file is not a diary we can parse.
        """
        document, stamp = _load_document(path)
        kdf_params = KdfParams.from_dict(document["kdf"])
        return cls._decrypted(path, document, stamp, kdf_params, key)

    @classmethod
    def _decrypted(
        cls,
        path: Path,
        document: dict[str, Any],
        stamp: tuple[int, int],
        kdf_params: KdfParams,
        key: bytes,
    ) -> Self:
        """Turn a loaded document into an open diary, given its key.

        `stamp` is the file's (mtime, size) as of the read that produced
        `document`, not as of now. A stamp taken after the slow decryption
        would adopt another Zecret's save in that time as this session's
        own, and the next save() would write over it.

        The verifier is checked first, and its failure is the only one
        that means a wrong key. Anything that fails after it is damage.
        """
        _check_verifier(key, document["verifier"])

        entries: dict[dt.date, Entry] = {}
        records: dict[dt.date, _Record] = {}
        try:
            for raw in document["entries"]:
                record_date, nonce, ciphertext = _parse_record(raw)
                entry = Entry.from_json_bytes(decrypt(key, nonce, ciphertext))
                # The record date is outside the AEAD; the one inside is
                # authenticated. Requiring a match keeps a tampered index
                # from filing an entry under the wrong day.
                if entry.date != record_date:
                    raise ValueError(f"entry date mismatch for record {record_date}")
                if entry.date in entries:
                    raise ValueError(f"duplicate entry for {entry.date}")
                entries[entry.date] = entry
                records[entry.date] = _Record(entry, nonce, ciphertext)
        except (ZecretDecryptError, ValueError) as exc:
            raise ZecretDamagedError(f"diary file is damaged: {exc}") from exc

        diary = cls(path=path, kdf_params=kdf_params, entries=entries)
        diary._records = records
        diary._records_key = _key_fingerprint(key)
        diary._file_stamp = stamp
        return diary

    def save(self, key: bytes) -> None:
        """Encrypt new or modified entries under `key` and atomically write
        the whole diary to self.path.

        Unchanged entries keep their nonce and ciphertext byte for byte.
        When `key` is not the key the stored ciphertexts were made with
        (after change_password()), every entry is re-encrypted.

        Screens save through saving(), which also undoes the change if
        this fails.

        Raises:
            ZecretConflictError: if the file changed since this session
                read or wrote it. In-memory state is left untouched.
            OSError: if the write itself fails.
        """
        self._check_unchanged()
        self._write(key)

    @contextmanager
    def saving(self, key: bytes) -> Iterator[None]:
        """Make the changes in the `with` block, then save them, or neither.

            with diary.saving(key):
                diary.delete_entry(day)

        If the block or the save raises, the entries and the ciphertext
        cache are put back as they were and the exception propagates.
        Memory then still matches the file, and a restored day keeps its
        on-disk ciphertext.

        Use it on the event loop, not from a worker thread: the undo
        empties and refills self.entries in place.

        Raises:
            ZecretConflictError, OSError: as save() does.
        """
        entries = dict(self.entries)
        records = dict(self._records)
        try:
            yield
            self.save(key)
        except BaseException:
            # Refilled rather than replaced, so anything holding this dict
            # sees the restored entries.
            self.entries.clear()
            self.entries.update(entries)
            self._records = records
            raise

    def _write(self, key: bytes, *, exclusive: bool = False) -> None:
        """Encrypt what needs encrypting and put the whole diary on disk.

        save() without the conflict check. `exclusive` is what
        create_new() passes instead: the file must not already exist, and
        the write itself decides that, since another Zecret can create the
        diary while this one derives its key.

        Raises:
            FileExistsError: if `exclusive` and the file now exists.
            OSError: if the write itself fails.
        """
        fingerprint = _key_fingerprint(key)
        reusable = self._records if fingerprint == self._records_key else {}

        records: dict[dt.date, _Record] = {}
        payload: list[dict[str, str]] = []
        # Newest first, to match how the diary reads. Nothing depends on it.
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
        encoded = json.dumps(document).encode("utf-8")
        if exclusive:
            stamp = _create_exclusively(self.path, encoded)
        else:
            stamp = _atomic_write(self.path, encoded)

        # Adopted only once the write has landed, so a failed save leaves
        # the cache describing what is really on disk.
        self._records = records
        self._records_key = fingerprint
        self._file_stamp = stamp

    def _check_unchanged(self) -> None:
        """Refuse to write over a file someone else has written.

        Compares the file's mtime and size with what they were when this
        session last read or wrote it. Not a lock: two saves in one
        timestamp tick at the same size would slip through, which human
        typing does not produce. A lock held across a session would leave
        a stale lockfile whenever the terminal was closed.

        A deleted file is not a conflict; writing restores the diary.

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
        """The entry written for `date`, or None if that day is unwritten."""
        return self.entries.get(date)

    def add_entry(self, entry: Entry) -> None:
        """Add a new entry in memory (does not persist).

        Raises:
            ValueError: if that day already has an entry.
        """
        if entry.date in self.entries:
            raise ValueError(f"an entry already exists for {entry.date}")
        self.entries[entry.date] = entry

    def update_entry(self, entry: Entry) -> None:
        """Replace the entry for entry.date in memory.

        Raises:
            KeyError: if that day has no entry yet.
        """
        if entry.date not in self.entries:
            raise KeyError(entry.date)
        self.entries[entry.date] = entry

    def delete_entry(self, date: dt.date) -> None:
        """Remove a day's entry in memory.

        Raises:
            KeyError: if that day has no entry.
        """
        del self.entries[date]
        # The cached record holds the plaintext too; saving() restores it
        # from its own copy if the deletion is undone.
        self._records.pop(date, None)

    def verify_password(self, password: str, key: bytes) -> bool:
        """Whether `password` derives `key` under this diary's KDF params.

        For re-checking the current password before a change, since
        screens may not call derive_key(). Compared in constant time.
        """
        return hmac.compare_digest(derive_key(password, self.kdf_params), key)

    def change_password(self, new_password: str) -> bytes:
        """Rotate to a new password and save the diary re-encrypted under it.

        A fresh salt is generated and every entry is re-encrypted.

        Returns the new key.

        Raises:
            ZecretConflictError, OSError: if the save fails. The diary is
                then still under the old password, on disk and in memory.
        """
        previous = self.kdf_params
        self.kdf_params = KdfParams.generate()
        new_key = derive_key(new_password, self.kdf_params)
        # Its own undo rather than saving(): this runs in a worker thread
        # and changes no entries. Left in place after a failed save, the
        # new params would be written over old ciphertext by the next save
        # under the old key, and neither password would open the file.
        try:
            self.save(new_key)
        except BaseException:
            self.kdf_params = previous
            raise
        return new_key


def _file_stamp(path: Path) -> tuple[int, int] | None:
    """(mtime, size) for `path`, or None if it cannot be stat-ed."""
    try:
        return _stamp_of(path.stat())
    except OSError:
        return None


def _stamp_of(status: os.stat_result) -> tuple[int, int]:
    """The (mtime, size) pair the conflict check compares.

    A read takes its stamp with fstat() on the descriptor it read from, so
    the stamp describes exactly the bytes read.
    """
    return status.st_mtime_ns, status.st_size


def _key_fingerprint(key: bytes) -> bytes:
    """A short, non-reversible tag identifying a key, so save() can notice
    a different key without DiaryFile retaining key material."""
    return hashlib.blake2b(key, digest_size=16, person=b"zecret-keyid").digest()


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _load_document(path: Path) -> tuple[dict[str, Any], tuple[int, int]]:
    """Read and structurally validate the diary file at `path`.

    Returns the document and the file's stamp, both from the same open
    descriptor.

    Raises:
        FileNotFoundError: if `path` does not exist.
        ZecretVersionError: if the file names a format newer than this one.
        ValueError: if the contents are not a diary of a known version.
    """
    with path.open("rb") as handle:
        raw = handle.read()
        stamp = _stamp_of(os.fstat(handle.fileno()))
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"not a readable diary file: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("diary file must contain a JSON object")

    version = document.get("version")
    # `type is int`, not `==`: True == 1 and 1.0 == 1, and neither is a
    # format version. A future format adds a branch here.
    if type(version) is int and version > FORMAT_VERSION:
        raise ZecretVersionError(f"diary format {version} is newer than this Zecret reads")
    if type(version) is not int or version != FORMAT_VERSION:
        raise ValueError(f"unsupported diary format version: {version!r}")
    if not isinstance(document.get("kdf"), dict):
        raise ValueError("diary file is missing its kdf header")
    if not isinstance(document.get("verifier"), dict):
        raise ValueError("diary file is missing its key verifier")
    if not isinstance(document.get("entries"), list):
        raise ValueError("diary file is missing its entries list")
    return document, stamp


def _check_verifier(key: bytes, verifier: dict[str, Any]) -> None:
    """Confirm `key` is the diary's key before reading any entries.

    Raises:
        ZecretDecryptError: if the verifier fails to decrypt, or decrypts
            to the wrong constant.
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


def _atomic_write(path: Path, data: bytes) -> tuple[int, int]:
    """Write `data` to `path` atomically, never leaving a partial file.

    Temp file in the same directory, fsync, then os.replace() over the
    target. On failure the temp file is removed and the existing file is
    untouched.

    A symlink is resolved first and its target replaced. Renaming over the
    link would swap it for a regular file and cut a diary kept in a synced
    folder loose from it. Resolving also puts the temp file on the real
    file's filesystem.

    Returns the written file's stamp, taken from the temp file just before
    the rename (a rename keeps mtime and size, and a later stat of the path
    could see another process's write). Taken after the close, because
    some filesystems (SMB, some FUSE mounts) set the mtime on close.
    """
    path = path.resolve()
    directory = path.parent
    _sweep_stale_temps(directory, path.name)
    fd, tmp_name = tempfile.mkstemp(
        dir=directory, prefix=_temp_prefix(path.name), suffix=TEMP_SUFFIX
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _restrict(tmp_path, FILE_MODE)
        stamp = _stamp_of(tmp_path.stat())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    _fsync_directory(directory)
    return stamp


def _temp_prefix(name: str) -> str:
    """What every temp file for the diary called `name` starts with."""
    return f".{name}."


def _sweep_stale_temps(directory: Path, name: str) -> None:
    """Remove temp files an earlier, killed save left beside the diary.

    A save killed outright (SIGKILL, power loss) cannot clean up after
    itself. Ciphertext only, so litter rather than a leak.

    Only files older than STALE_TEMP_SECONDS go: a younger one may be
    another Zecret's save in flight. Best-effort, so a sweep that cannot
    run never fails a save.
    """
    cutoff = time.time() - STALE_TEMP_SECONDS
    with suppress(OSError):
        for candidate in directory.glob(f"{glob.escape(_temp_prefix(name))}*{TEMP_SUFFIX}"):
            with suppress(OSError):
                if candidate.stat().st_mtime < cutoff:
                    candidate.unlink()


def _create_exclusively(path: Path, data: bytes) -> tuple[int, int] | None:
    """Write `data` to `path`, refusing a path that already holds a file.

    O_EXCL makes "is it there?" and "claim it" one step that another
    process cannot get between. Used only to create a diary.

    Written straight to the target, not through a temp file: there is
    nothing on disk to protect, and the rename is the step that would
    flatten a diary someone else had just created. A failed write removes
    the stub it started.

    Returns the new file's stamp, or None if it could not be stat-ed.

    Raises:
        FileExistsError: if something is already at `path`.
        OSError: if the write fails for any other reason.
    """
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, FILE_MODE)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    # O_EXCL honours the mode only where the umask allows it.
    _restrict(path, FILE_MODE)
    # _file_stamp() rather than a bare stat: the diary exists by now, and a
    # failed stat must not report the creation as failed. No stamp only
    # skips the conflict check until the next save takes one.
    stamp = _file_stamp(path)
    _fsync_directory(path.parent)
    return stamp


def _make_private_directory(directory: Path) -> None:
    """Create `directory` private to its owner, or leave an existing one be.

    Only a directory Zecret creates, or ~/.zecret itself, is narrowed to
    DIR_MODE. Any other existing directory belongs to whoever made it:
    `--path ~/diary.enc` must not chmod the home directory. The diary file
    is 0600 either way.
    """
    try:
        directory.mkdir(parents=True, mode=DIR_MODE)
    except FileExistsError:
        if not _is_zecret_s_own(directory):
            return
    # mkdir's mode is filtered through the umask; make it exact.
    _restrict(directory, DIR_MODE)


def _is_zecret_s_own(directory: Path) -> bool:
    """Whether an existing `directory` is ~/.zecret itself.

    The same directory on disk, however the path spells it. A symlink at
    ~/.zecret is not Zecret's to narrow: chmod would follow it into a
    folder someone else chose.
    """
    if directory.is_symlink() or not directory.is_dir():
        return False
    try:
        return directory.samefile(DEFAULT_DIARY_PATH.parent)
    except OSError:
        return False


def _restrict(target: Path, mode: int) -> None:
    """Best-effort chmod. Some filesystems (FAT, Windows mounts) have no
    POSIX modes; the diary is still encrypted there."""
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
