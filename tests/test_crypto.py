"""Tests for zecret.crypto.

Required coverage (fill in as crypto.py is implemented):
    - KdfParams.generate() produces a random salt each call.
    - KdfParams to_dict()/from_dict() round-trips exactly.
    - derive_key() is deterministic for the same password + params.
    - derive_key() produces different keys for different passwords.
    - encrypt()/decrypt() round-trips arbitrary bytes correctly.
    - encrypt() never reuses a nonce across two calls (statistical check
      over many calls, or assert nonce length matches expected size).
    - decrypt() raises ZecretDecryptError on wrong key.
    - decrypt() raises ZecretDecryptError on tampered ciphertext
      (flip a byte, confirm it's detected -- this is the AEAD integrity
      guarantee, critical to verify).
"""

from __future__ import annotations

import json
import os

import pytest
from argon2.low_level import Type, hash_secret_raw

from zecret.crypto import (
    KEY_SIZE,
    NONCE_SIZE,
    SALT_SIZE,
    KdfParams,
    ZecretDecryptError,
    decrypt,
    derive_key,
    encrypt,
)


@pytest.fixture(scope="module")
def key() -> bytes:
    """A random key for cipher-level tests.

    encrypt()/decrypt() only care that the key is KEY_SIZE bytes, so these
    tests skip the (deliberately slow) KDF entirely.
    """
    return os.urandom(KEY_SIZE)


@pytest.fixture(scope="module")
def cheap_params() -> KdfParams:
    """KdfParams with minimal cost factors, for tests that call derive_key
    repeatedly and are checking behavior rather than cost settings."""
    return KdfParams(salt=b"\x00" * SALT_SIZE, time_cost=1, memory_cost=8, parallelism=1)


# --- KdfParams -------------------------------------------------------------


def test_generate_produces_random_salt_each_call():
    salts = {KdfParams.generate().salt for _ in range(20)}
    assert len(salts) == 20, "generate() must produce a fresh random salt per call"


def test_generate_salt_has_expected_length():
    assert len(KdfParams.generate().salt) == SALT_SIZE


def test_generate_uses_owasp_default_cost_factors():
    """CLAUDE.md pins these as non-negotiable minimums."""
    params = KdfParams.generate()
    assert params.time_cost == 3
    assert params.memory_cost == 65536
    assert params.parallelism == 4


def test_to_dict_from_dict_round_trips_exactly():
    params = KdfParams.generate()
    assert KdfParams.from_dict(params.to_dict()) == params


def test_to_dict_round_trips_non_default_cost_factors():
    params = KdfParams(salt=os.urandom(SALT_SIZE), time_cost=5, memory_cost=131072, parallelism=2)
    assert KdfParams.from_dict(params.to_dict()) == params


def test_to_dict_is_json_safe():
    """The header is written straight into the diary's JSON, so every value
    must survive a json round-trip unchanged (salt as base64 text)."""
    params = KdfParams.generate()
    data = params.to_dict()
    assert isinstance(data["salt"], str)
    assert KdfParams.from_dict(json.loads(json.dumps(data))) == params


def test_to_dict_declares_argon2id():
    assert KdfParams.generate().to_dict()["algo"] == "argon2id"


def test_from_dict_rejects_other_kdf_algorithms():
    """Fail closed: a header naming a KDF we don't implement must not be
    silently treated as Argon2id."""
    data = KdfParams.generate().to_dict()
    data["algo"] = "pbkdf2"
    with pytest.raises(ValueError):
        KdfParams.from_dict(data)


@pytest.mark.parametrize("missing", ["salt", "time_cost", "memory_cost", "parallelism"])
def test_from_dict_rejects_incomplete_header(missing):
    data = KdfParams.generate().to_dict()
    del data[missing]
    with pytest.raises(ValueError):
        KdfParams.from_dict(data)


def test_from_dict_rejects_malformed_salt():
    data = KdfParams.generate().to_dict()
    data["salt"] = "not!valid!base64!"
    with pytest.raises(ValueError):
        KdfParams.from_dict(data)


# --- derive_key ------------------------------------------------------------


def test_derive_key_is_deterministic():
    params = KdfParams.generate()
    assert derive_key("correct horse battery staple", params) == derive_key(
        "correct horse battery staple", params
    )


def test_derive_key_returns_key_of_expected_size():
    assert len(derive_key("hunter2", KdfParams.generate())) == KEY_SIZE


def test_derive_key_uses_argon2id_variant(cheap_params):
    """Argon2id specifically -- not Argon2i or Argon2d. Verified by
    reproducing the key with each variant and asserting only id matches."""

    def reference(variant: Type) -> bytes:
        return hash_secret_raw(
            secret=b"master password",
            salt=cheap_params.salt,
            time_cost=cheap_params.time_cost,
            memory_cost=cheap_params.memory_cost,
            parallelism=cheap_params.parallelism,
            hash_len=KEY_SIZE,
            type=variant,
        )

    derived = derive_key("master password", cheap_params)
    assert derived == reference(Type.ID)
    assert derived != reference(Type.I)
    assert derived != reference(Type.D)


def test_derive_key_differs_for_different_passwords(cheap_params):
    assert derive_key("password-a", cheap_params) != derive_key("password-b", cheap_params)


def test_derive_key_differs_for_different_salts():
    """Two diaries created with the same password must not share a key."""
    password = "same password"
    assert derive_key(password, KdfParams.generate()) != derive_key(password, KdfParams.generate())


def test_derive_key_differs_for_different_cost_factors(cheap_params):
    stronger = KdfParams(salt=cheap_params.salt, time_cost=2, memory_cost=8, parallelism=1)
    assert derive_key("pw", cheap_params) != derive_key("pw", stronger)


def test_derive_key_handles_unicode_passwords(cheap_params):
    """Passwords are encoded as UTF-8, so non-ASCII must work and stay
    distinct from a similar-looking ASCII password."""
    assert derive_key("pässwörd 🔐", cheap_params) == derive_key("pässwörd 🔐", cheap_params)
    assert derive_key("pässwörd 🔐", cheap_params) != derive_key("passwörd 🔐", cheap_params)


def test_derive_key_is_case_sensitive(cheap_params):
    assert derive_key("Secret", cheap_params) != derive_key("secret", cheap_params)


def test_derived_key_works_with_cipher(cheap_params):
    """The KDF and the cipher agree on key size -- derive_key output is
    directly usable, with no massaging by the caller."""
    derived = derive_key("master password", cheap_params)
    nonce, ciphertext = encrypt(derived, b"diary entry")
    assert decrypt(derived, nonce, ciphertext) == b"diary entry"


# --- encrypt / decrypt round-trip -----------------------------------------


@pytest.mark.parametrize(
    "plaintext",
    [
        b"",
        b"a",
        b"a short diary entry",
        "unicode: éèê \U0001f512 日本語".encode("utf-8"),
        b"\x00\x01\x02\xfd\xfe\xff",
        os.urandom(4096),
        b"x" * 100_000,
    ],
    ids=["empty", "one-byte", "ascii", "unicode", "binary", "random-4k", "large"],
)
def test_encrypt_decrypt_round_trip(key, plaintext):
    nonce, ciphertext = encrypt(key, plaintext)
    assert decrypt(key, nonce, ciphertext) == plaintext


def test_ciphertext_does_not_contain_plaintext(key):
    plaintext = b"the plaintext of a very private diary entry"
    _, ciphertext = encrypt(key, plaintext)
    assert plaintext not in ciphertext


def test_ciphertext_is_authenticated(key):
    """AEAD: the ciphertext carries a tag, so it is longer than the
    plaintext. Without this there is no tamper detection at all."""
    _, ciphertext = encrypt(key, b"")
    assert len(ciphertext) == 16, "expected a 16-byte authentication tag"


def test_encrypt_returns_expected_nonce_size(key):
    nonce, _ = encrypt(key, b"payload")
    assert len(nonce) == NONCE_SIZE


def test_encrypt_rejects_wrong_size_key():
    with pytest.raises(ValueError):
        encrypt(os.urandom(16), b"payload")


# --- nonce uniqueness ------------------------------------------------------


def test_encrypt_never_reuses_a_nonce(key):
    """Nonce reuse under a single key breaks AES-GCM catastrophically, so
    every call must generate a fresh one."""
    nonces = [encrypt(key, b"same plaintext every time")[0] for _ in range(2000)]
    assert len(set(nonces)) == len(nonces)


def test_encrypt_is_randomized(key):
    """Same key, same plaintext, different ciphertext -- an observer cannot
    tell that two entries have identical content."""
    plaintext = b"identical content"
    first_nonce, first_ct = encrypt(key, plaintext)
    second_nonce, second_ct = encrypt(key, plaintext)
    assert first_nonce != second_nonce
    assert first_ct != second_ct


def test_nonce_cannot_be_supplied_by_caller(key):
    """The nonce is generated inside encrypt() by design; there must be no
    parameter allowing a caller to pin it."""
    with pytest.raises(TypeError):
        encrypt(key, b"payload", b"\x00" * NONCE_SIZE)


# --- failure modes: everything must be a ZecretDecryptError ----------------


def test_decrypt_raises_on_wrong_key(key):
    nonce, ciphertext = encrypt(key, b"secret entry")
    with pytest.raises(ZecretDecryptError):
        decrypt(os.urandom(KEY_SIZE), nonce, ciphertext)


def test_decrypt_raises_on_key_derived_from_wrong_password(cheap_params):
    """The wrong-password path exactly as the unlock screen hits it."""
    right = derive_key("the right password", cheap_params)
    wrong = derive_key("the wrong password", cheap_params)
    nonce, ciphertext = encrypt(right, b"secret entry")
    with pytest.raises(ZecretDecryptError):
        decrypt(wrong, nonce, ciphertext)


@pytest.mark.parametrize("index", [0, 1, 7, -1])
def test_decrypt_raises_on_tampered_ciphertext(key, index):
    """Flip a single bit anywhere in the ciphertext (including the tag at
    the end) and decryption must refuse to return anything."""
    nonce, ciphertext = encrypt(key, b"a diary entry worth protecting")
    tampered = bytearray(ciphertext)
    tampered[index] ^= 0x01
    with pytest.raises(ZecretDecryptError):
        decrypt(key, nonce, bytes(tampered))


def test_decrypt_raises_on_every_single_byte_flip(key):
    """Exhaustive integrity check: no byte of the ciphertext can be altered
    without detection."""
    nonce, ciphertext = encrypt(key, b"short entry")
    for i in range(len(ciphertext)):
        tampered = bytearray(ciphertext)
        tampered[i] ^= 0xFF
        with pytest.raises(ZecretDecryptError):
            decrypt(key, nonce, bytes(tampered))


def test_decrypt_raises_on_tampered_nonce(key):
    nonce, ciphertext = encrypt(key, b"a diary entry")
    tampered = bytearray(nonce)
    tampered[0] ^= 0x01
    with pytest.raises(ZecretDecryptError):
        decrypt(key, bytes(tampered), ciphertext)


def test_decrypt_raises_on_truncated_ciphertext(key):
    nonce, ciphertext = encrypt(key, b"a diary entry")
    with pytest.raises(ZecretDecryptError):
        decrypt(key, nonce, ciphertext[:-1])


def test_decrypt_raises_on_empty_ciphertext(key):
    """A zeroed-out or missing record must not decrypt to empty plaintext."""
    nonce, _ = encrypt(key, b"a diary entry")
    with pytest.raises(ZecretDecryptError):
        decrypt(key, nonce, b"")


def test_decrypt_raises_on_wrong_size_nonce(key):
    """A corrupt header/record shouldn't leak a raw cryptography error."""
    _, ciphertext = encrypt(key, b"a diary entry")
    with pytest.raises(ZecretDecryptError):
        decrypt(key, b"\x00" * (NONCE_SIZE - 1), ciphertext)


def test_decrypt_raises_on_swapped_nonce(key):
    """Nonce and ciphertext are stored as a pair; pairing a ciphertext with
    another record's nonce must fail."""
    _, first_ct = encrypt(key, b"entry one")
    second_nonce, _ = encrypt(key, b"entry two")
    with pytest.raises(ZecretDecryptError):
        decrypt(key, second_nonce, first_ct)


def test_decrypt_error_message_does_not_leak_secrets(key):
    """The unlock screen surfaces this; it must not carry key material."""
    nonce, ciphertext = encrypt(key, b"private content here")
    with pytest.raises(ZecretDecryptError) as excinfo:
        decrypt(os.urandom(KEY_SIZE), nonce, ciphertext)
    message = str(excinfo.value)
    assert key.hex() not in message
    assert "private content" not in message


def test_zecret_decrypt_error_is_catchable_as_exception():
    assert issubclass(ZecretDecryptError, Exception)
