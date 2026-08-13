"""Tests for the CLI entry point.

Required coverage:
    - --path wins over ZECRET_DIARY_PATH, which wins over the default.
    - The app is constructed with that path and then run.

CI additionally runs `zecret --help` against an installed copy, which is
the only way to catch the console script being wired up wrongly; these
cover the resolution logic that flag cannot see.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import zecret.__main__ as entry_point
from zecret.storage import DEFAULT_DIARY_PATH


@pytest.fixture
def launched(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Capture the diary path each ZecretApp would have been built with,
    without starting a terminal app."""
    paths: list[Path] = []

    class StubApp:
        def __init__(self, diary_path: Path) -> None:
            paths.append(diary_path)

        def run(self) -> None:
            paths.append(Path("ran"))

    monkeypatch.setattr(entry_point, "ZecretApp", StubApp)
    monkeypatch.delenv("ZECRET_DIARY_PATH", raising=False)
    return paths


def test_default_path_is_used_when_nothing_is_given(launched, monkeypatch):
    monkeypatch.setattr("sys.argv", ["zecret"])
    entry_point.main()
    assert launched[0] == DEFAULT_DIARY_PATH


def test_the_app_is_actually_run(launched, monkeypatch):
    monkeypatch.setattr("sys.argv", ["zecret"])
    entry_point.main()
    assert launched[-1] == Path("ran"), "constructing the app is not enough"


def test_env_var_overrides_the_default(launched, monkeypatch, tmp_path):
    from_env = tmp_path / "from-env.enc"
    monkeypatch.setenv("ZECRET_DIARY_PATH", str(from_env))
    monkeypatch.setattr("sys.argv", ["zecret"])
    entry_point.main()
    assert launched[0] == from_env


def test_flag_overrides_the_env_var(launched, monkeypatch, tmp_path):
    """The flag is the more specific of the two, and the one you reach for
    to open a second diary just once."""
    from_flag = tmp_path / "from-flag.enc"
    monkeypatch.setenv("ZECRET_DIARY_PATH", str(tmp_path / "from-env.enc"))
    monkeypatch.setattr("sys.argv", ["zecret", "--path", str(from_flag)])
    entry_point.main()
    assert launched[0] == from_flag


def test_an_unknown_flag_is_refused(launched, monkeypatch):
    monkeypatch.setattr("sys.argv", ["zecret", "--wat"])
    with pytest.raises(SystemExit):
        entry_point.main()
    assert launched == [], "nothing may launch on a bad command line"
