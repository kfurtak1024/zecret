"""Shared fixtures.

The one thing worth doing suite-wide: keep every test away from the real
~/.zecret. Diary paths are already passed explicitly everywhere (tmp_path),
but the preferences path has a default that a test constructing ZecretApp
would otherwise fall through to -- reading, and on a theme change writing,
the user's own config file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import zecret.app


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the default preferences path at a throwaway file.

    ZecretApp resolves the default when constructed rather than at import
    time, so patching it here covers tests that pass no config_path.
    """
    path = tmp_path / "zecret-config.json"
    monkeypatch.setattr(zecret.app, "DEFAULT_CONFIG_PATH", path)
    return path
