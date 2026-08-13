"""Shared fixtures.

Two things worth doing once rather than per file:

Keeping every test away from the real ~/.zecret. Diary paths are already
passed explicitly everywhere (tmp_path), but the preferences path has a
default that a test constructing ZecretApp would otherwise fall through to
-- reading, and on a theme change writing, the user's own config file.

And keeping Argon2 at test cost. Every test that opens a diary derives a
key at least twice, and at the real parameters (64 MiB, three passes) that
is most of the suite's runtime. `cheap_kdf` is opt-in rather than autouse
on purpose: test_crypto.py asserts that generate() produces the OWASP cost
factors, and a blanket patch would leave that assertion passing against
whatever cheap numbers it had quietly been handed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import zecret.app
from zecret.crypto import KdfParams

#: Real Argon2id, at cost factors that keep the suite quick. The code path
#: is identical; only the work factor changes.
CHEAP_KDF = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the default preferences path at a throwaway file.

    ZecretApp resolves the default when constructed rather than at import
    time, so patching it here covers tests that pass no config_path.
    """
    path = tmp_path / "zecret-config.json"
    monkeypatch.setattr(zecret.app, "DEFAULT_CONFIG_PATH", path)
    return path


@pytest.fixture
def cheap_kdf(monkeypatch: pytest.MonkeyPatch) -> None:
    """Derive keys at test speed.

    Request it with `pytestmark = pytest.mark.usefixtures("cheap_kdf")` in
    any module that opens diaries. Patches only generate(), so the params
    written into a new diary header are the cheap ones and unlock reads
    them straight back out.
    """
    original = KdfParams.generate

    def generate() -> KdfParams:
        return KdfParams(salt=original().salt, **CHEAP_KDF)

    monkeypatch.setattr(KdfParams, "generate", staticmethod(generate))
