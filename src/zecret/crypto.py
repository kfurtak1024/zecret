"""Key derivation and authenticated encryption primitives for Zecret.

Security model:
    - The master key is derived from the user's password via Argon2id.
    - Each entry is encrypted independently with its own random nonce,
      using an AEAD cipher. XChaCha20-Poly1305 is the preferred choice,
      but `cryptography` does not expose it, so this module uses the
      documented fallback: AES-256-GCM with a fresh 96-bit random nonce
      per call. This means editing one entry never requires decrypting
      or re-encrypting any other entry.
    - The cipher is fixed, not negotiated: the on-disk format records no
      cipher identifier, so switching ciphers here would silently make
      existing diary files undecryptable. Any change needs a format
      version bump and a migration (see storage.py).
    - Plaintext must never be written to disk. Callers are responsible
      for keeping decrypted data in memory only.
    - The derived key should be treated as sensitive: avoid copying it
      more than necessary, and let it go out of scope when no longer
      needed.

This module has no knowledge of the on-disk file format (see
storage.py) or of entry semantics (see models.py). It only knows how
to turn a password into a key, and how to encrypt/decrypt bytes with
that key.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any, Self

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KDF_ALGO = "argon2id"
SALT_SIZE = 16
KEY_SIZE = 32
NONCE_SIZE = 12


class ZecretDecryptError(Exception):
    """Raised when decryption fails: wrong password or corrupted/tampered data.

    Callers (e.g. the unlock screen) should catch this specifically to show
    a user-friendly "incorrect password" message rather than a raw
    cryptography traceback.
    """


@dataclass(frozen=True, slots=True)
class KdfParams:
    """Argon2id parameters, stored alongside the diary so it can be
    re-derived deterministically on unlock.

    Attributes:
        salt: Random salt, generated once per diary file, stored as raw bytes.
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
        """Generate fresh KdfParams with a new random salt and sane defaults.

        Used when creating a brand new diary file.
        """
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
            ValueError: if the header names a KDF other than Argon2id, or
                if a required field is missing or malformed. Unknown
                algorithms are rejected rather than assumed — a diary we
                cannot derive the right key for must fail loudly.
        """
        algo = data.get("algo", KDF_ALGO)
        if algo != KDF_ALGO:
            raise ValueError(f"unsupported KDF algorithm: {algo!r}")
        try:
            return cls(
                salt=base64.b64decode(data["salt"], validate=True),
                time_cost=int(data["time_cost"]),
                memory_cost=int(data["memory_cost"]),
                parallelism=int(data["parallelism"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"malformed KDF header: {exc}") from exc


def derive_key(password: str, params: KdfParams) -> bytes:
    """Derive a symmetric key from a password using Argon2id.

    Args:
        password: The user's master password (plaintext, in memory only).
        params: KDF parameters (salt + cost factors) from the diary header.

    Returns:
        A 32-byte key suitable for use with encrypt()/decrypt().
    """
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=params.salt,
        time_cost=params.time_cost,
        memory_cost=params.memory_cost,
        parallelism=params.parallelism,
        hash_len=KEY_SIZE,
        type=Type.ID,
    )


def encrypt(key: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
    """Encrypt plaintext under the given key using an AEAD cipher.

    A fresh random nonce is generated internally for every call — callers
    must never reuse a nonce with the same key.

    Args:
        key: 32-byte symmetric key, as returned by derive_key().
        plaintext: The serialized entry data to encrypt (UTF-8 JSON bytes).

    Returns:
        A (nonce, ciphertext) tuple, both raw bytes, to be stored
        alongside each other in the entry record. The ciphertext includes
        the AEAD authentication tag.

    Raises:
        ValueError: if `key` is not KEY_SIZE bytes. This is a programming
            error, not a decryption failure, so it is not wrapped in
            ZecretDecryptError.
    """
    _validate_key(key)
    nonce = os.urandom(NONCE_SIZE)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return nonce, ciphertext


def decrypt(key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    """Decrypt a ciphertext previously produced by encrypt().

    Args:
        key: 32-byte symmetric key.
        nonce: The nonce that was generated for this specific ciphertext.
        ciphertext: The encrypted bytes.

    Returns:
        The original plaintext bytes.

    Raises:
        ZecretDecryptError: if the key is wrong, the nonce is the wrong
            size, or the nonce/ciphertext has been tampered with or
            truncated. Every authentication failure surfaces as this one
            exception — decryption fails closed and never returns
            unauthenticated bytes. This is also how wrong-password
            detection works on unlock.
        ValueError: if `key` is not KEY_SIZE bytes (a programming error,
            deliberately distinct from a decryption failure).
    """
    _validate_key(key)
    if len(nonce) != NONCE_SIZE:
        raise ZecretDecryptError(f"nonce must be {NONCE_SIZE} bytes, got {len(nonce)}")
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, None)
    except InvalidTag as exc:
        raise ZecretDecryptError("decryption failed: wrong password or corrupted data") from exc


def _validate_key(key: bytes) -> None:
    """Guard against a mis-sized key reaching the cipher."""
    if len(key) != KEY_SIZE:
        raise ValueError(f"key must be {KEY_SIZE} bytes, got {len(key)}")
