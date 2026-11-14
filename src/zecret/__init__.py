"""Zecret: a modern, encrypted terminal diary."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    # From the installed distribution: pyproject.toml is the only place
    # the version is written.
    __version__ = version("zecret")
except PackageNotFoundError:  # pragma: no cover - only when run uninstalled
    __version__ = "0.0.0+unknown"
