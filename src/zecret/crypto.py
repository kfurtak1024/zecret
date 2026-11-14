"""Key derivation and authenticated encryption primitives for Zecret.

The master key is derived from the password with Argon2id. Each entry is
encrypted on its own with AES-256-GCM and a fresh random 96-bit nonce.
(`cryptography` does not expose XChaCha20-Poly1305, the preferred choice.)

The cipher is fixed, not negotiated: the file format records no cipher id,
so changing it here needs a format version bump and a migration.

This module knows nothing about files (storage.py) or entries (models.py):
bytes in, bytes out. Callers keep plaintext and the key in memory only.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any, Self

from argon2.exceptions import Argon2Error
from argon2.low_level import Type, error_to_str, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KDF_ALGO = "argon2id"
SALT_SIZE = 16
KEY_SIZE = 32
NONCE_SIZE = 12

#: How argon2-cffi words a failed allocation. It raises one exception type
#: for every failure, told apart only by this text, so the text is asked of
#: the library. -22 is ARGON2_MEMORY_ALLOCATION_ERROR in argon2.h.
_OUT_OF_MEMORY = error_to_str(-22)


class ZecretDecryptError(Exception):
    """Decryption failed: wrong key, or corrupted or tampered data."""


@dataclass(frozen=True, slots=True)
class KdfParams:
    """Argon2id parameters, stored in the diary header so the key can be
    re-derived on unlock.

    Attributes:
        salt: Random salt, generated once per diary file.
        time_cost: Argon2 iteration count.
        memory_cost: Argon2 memory usage in KiB.
        parallelism: Argon2 parallelism degree.
    """

    salt: bytes
    time_cost: int = 3
    memory_cost: int = 65536
    parallelism: int = 4

    @classmethod
    def generate(cls) -> Self:
        """Fresh params with a new random salt and the default costs."""
        return cls(salt=os.urandom(SALT_SIZE))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict (salt as base64) for the file header."""
        return {
            "algo": KDF_ALGO,
            "salt": base64.b64encode(self.salt).decode("ascii"),
            "time_cost": self.time_cost,
            "memory_cost": self.memory_cost,
            "parallelism": self.parallelism,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Reconstruct KdfParams from the file header's JSON dict.

        Raises:
            ValueError: if the header names no KDF or one other than
                Argon2id, or a field is missing or malformed.
        """
        algo = data.get("algo")
        if algo != KDF_ALGO:
            raise ValueError(f"unsupported KDF algorithm: {algo!r}")
        try:
            return cls(
                salt=base64.b64decode(data["salt"], validate=True),
                time_cost=_whole_number(data["time_cost"]),
                memory_cost=_whole_number(data["memory_cost"]),
                parallelism=_whole_number(data["parallelism"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"malformed KDF header: {exc}") from exc


def _whole_number(value: object) -> int:
    """`value` if it is an int, with nothing coerced: `int()` would accept
    "3", 3.9 and True."""
    if type(value) is not int:
        raise TypeError(f"expected a whole number, got {value!r}")
    return value


def derive_key(password: str, params: KdfParams) -> bytes:
    """Derive a 32-byte key from a password using Argon2id.

    The params come from the diary's own header, so a corrupted one reaches
    here. Argon2 owns the rules for what is usable; its refusals are
    converted rather than the rules restated in from_dict().

    Raises:
        ValueError: if Argon2 will not accept these parameters. Not a
            ZecretDecryptError: the password was never the problem.
        MemoryError: if the parameters are usable and the memory they ask
            for could not be allocated.
    """
    try:
        return hash_secret_raw(
            secret=password.encode("utf-8"),
            salt=params.salt,
            time_cost=params.time_cost,
            memory_cost=params.memory_cost,
            parallelism=params.parallelism,
            hash_len=KEY_SIZE,
            type=Type.ID,
        )
    except (Argon2Error, OverflowError, TypeError) as exc:
        if str(exc) == _OUT_OF_MEMORY:
            raise MemoryError(
                f"Argon2id needs {params.memory_cost // 1024} MiB and could not get it"
            ) from exc
        raise ValueError(f"unusable KDF parameters: {exc}") from exc


def encrypt(key: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
    """Encrypt `plaintext` under `key`, returning (nonce, ciphertext).

    The nonce is generated here, fresh for every call, and is never taken
    from the caller. The ciphertext includes the authentication tag.

    Raises:
        ValueError: if `key` is not KEY_SIZE bytes (a programming error).
    """
    _validate_key(key)
    nonce = os.urandom(NONCE_SIZE)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return nonce, ciphertext


def decrypt(key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    """Decrypt a ciphertext produced by encrypt().

    Raises:
        ZecretDecryptError: if the key is wrong, the nonce is the wrong
            size, or the data was tampered with or truncated. Never
            returns unauthenticated bytes.
        ValueError: if `key` is not KEY_SIZE bytes (a programming error).
    """
    _validate_key(key)
    if len(nonce) != NONCE_SIZE:
        raise ZecretDecryptError(f"nonce must be {NONCE_SIZE} bytes, got {len(nonce)}")
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, None)
    except InvalidTag as exc:
        raise ZecretDecryptError("decryption failed: wrong password or corrupted data") from exc


def _validate_key(key: bytes) -> None:
    if len(key) != KEY_SIZE:
        raise ValueError(f"key must be {KEY_SIZE} bytes, got {len(key)}")
