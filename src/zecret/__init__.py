"""Zecret: a modern, encrypted terminal diary."""

from importlib.metadata import PackageNotFoundError, version

try:
    # Read from the installed distribution, so pyproject.toml stays the one
    # place the version is written. A second copy here would eventually
    # disagree with it, and the help screen shows this one to the user.
    __version__ = version("zecret")
except PackageNotFoundError:  # pragma: no cover - only when run uninstalled
    __version__ = "0.0.0+unknown"
