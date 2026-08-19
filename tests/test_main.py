"""Tests for the CLI entry point.

Required coverage:
    - --path wins over ZECRET_DIARY_PATH, which wins over the default.
    - --config wins over ZECRET_CONFIG_PATH, which wins over the default.
    - The two are independent: neither flag implies anything about the other.
    - An empty environment variable counts as unset, not as `.`.
    - The app is constructed with those paths and then run.
    - --version prints the installed version and launches nothing.
    - --help names both environment variables, which is the only place a
      user can discover them.

CI additionally runs `zecret --help` against an installed copy, which is
the only way to catch the console script being wired up wrongly; these
cover the resolution logic that flag cannot see.

The preferences default is deliberately not asserted to be
DEFAULT_CONFIG_PATH: main() leaves it as None and ZecretApp resolves it,
so None here *is* "the default", and asserting a path would be asserting
that main() had taken the resolution away from the app.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

import zecret.__main__ as entry_point
from zecret import __version__
from zecret.storage import DEFAULT_DIARY_PATH


@dataclass
class Launch:
    """What a run of main() did, without starting a terminal app."""

    diary_paths: list[Path] = field(default_factory=list)
    config_paths: list[Path | None] = field(default_factory=list)
    runs: int = 0


@pytest.fixture
def launched(monkeypatch: pytest.MonkeyPatch) -> Launch:
    """Capture the paths each ZecretApp would have been built with."""
    record = Launch()

    class StubApp:
        def __init__(self, diary_path: Path, config_path: Path | None = None) -> None:
            record.diary_paths.append(diary_path)
            record.config_paths.append(config_path)

        def run(self) -> None:
            record.runs += 1

    monkeypatch.setattr(entry_point, "ZecretApp", StubApp)
    monkeypatch.delenv("ZECRET_DIARY_PATH", raising=False)
    monkeypatch.delenv("ZECRET_CONFIG_PATH", raising=False)
    return record


def test_default_path_is_used_when_nothing_is_given(launched, monkeypatch):
    monkeypatch.setattr("sys.argv", ["zecret"])
    entry_point.main()
    assert launched.diary_paths[0] == DEFAULT_DIARY_PATH


def test_the_app_is_actually_run(launched, monkeypatch):
    monkeypatch.setattr("sys.argv", ["zecret"])
    entry_point.main()
    assert launched.runs == 1, "constructing the app is not enough"


def test_env_var_overrides_the_default(launched, monkeypatch, tmp_path):
    from_env = tmp_path / "from-env.enc"
    monkeypatch.setenv("ZECRET_DIARY_PATH", str(from_env))
    monkeypatch.setattr("sys.argv", ["zecret"])
    entry_point.main()
    assert launched.diary_paths[0] == from_env


def test_flag_overrides_the_env_var(launched, monkeypatch, tmp_path):
    """The flag is the more specific of the two, and the one you reach for
    to open a second diary just once."""
    from_flag = tmp_path / "from-flag.enc"
    monkeypatch.setenv("ZECRET_DIARY_PATH", str(tmp_path / "from-env.enc"))
    monkeypatch.setattr("sys.argv", ["zecret", "--path", str(from_flag)])
    entry_point.main()
    assert launched.diary_paths[0] == from_flag


def test_an_unknown_flag_is_refused(launched, monkeypatch):
    monkeypatch.setattr("sys.argv", ["zecret", "--wat"])
    with pytest.raises(SystemExit):
        entry_point.main()
    assert launched.runs == 0, "nothing may launch on a bad command line"


def test_version_is_printed_and_nothing_is_launched(launched, monkeypatch, capsys):
    """Asking what you are running must not open a diary to answer -- the
    help popup already covers the case where you are past the password."""
    monkeypatch.setattr("sys.argv", ["zecret", "--version"])
    with pytest.raises(SystemExit) as exit_code:
        entry_point.main()
    assert exit_code.value.code == 0
    assert capsys.readouterr().out.strip() == f"zecret {__version__}"
    assert launched.runs == 0


def test_help_names_both_environment_variables(launched, monkeypatch, capsys):
    """--help is the only description of the command line a user reads, so a
    variable missing from it is a variable nobody finds."""
    monkeypatch.setattr("sys.argv", ["zecret", "--help"])
    with pytest.raises(SystemExit):
        entry_point.main()
    printed = capsys.readouterr().out
    assert "ZECRET_DIARY_PATH" in printed
    assert "ZECRET_CONFIG_PATH" in printed
    assert launched.runs == 0


def test_preferences_are_left_to_the_app_by_default(launched, monkeypatch):
    """None means "you decide", which is how the real default gets applied
    -- and how the tests keep it off the user's own config file."""
    monkeypatch.setattr("sys.argv", ["zecret"])
    entry_point.main()
    assert launched.config_paths[0] is None


def test_config_env_var_overrides_the_default(launched, monkeypatch, tmp_path):
    from_env = tmp_path / "prefs-from-env.json"
    monkeypatch.setenv("ZECRET_CONFIG_PATH", str(from_env))
    monkeypatch.setattr("sys.argv", ["zecret"])
    entry_point.main()
    assert launched.config_paths[0] == from_env


def test_config_flag_overrides_the_config_env_var(launched, monkeypatch, tmp_path):
    from_flag = tmp_path / "prefs-from-flag.json"
    monkeypatch.setenv("ZECRET_CONFIG_PATH", str(tmp_path / "prefs-from-env.json"))
    monkeypatch.setattr("sys.argv", ["zecret", "--config", str(from_flag)])
    entry_point.main()
    assert launched.config_paths[0] == from_flag


def test_the_diary_and_the_preferences_move_independently(launched, monkeypatch, tmp_path):
    """A scratch diary does not drag the preferences somewhere with it, and
    a scratch config does not redirect the diary. Pointing --path at a
    second diary while keeping your own theme is the whole reason the
    preferences path is separate."""
    diary = tmp_path / "scratch.enc"
    monkeypatch.setattr("sys.argv", ["zecret", "--path", str(diary)])
    entry_point.main()
    assert launched.diary_paths[0] == diary
    assert launched.config_paths[0] is None

    prefs = tmp_path / "scratch-prefs.json"
    monkeypatch.setattr("sys.argv", ["zecret", "--config", str(prefs)])
    entry_point.main()
    assert launched.diary_paths[1] == DEFAULT_DIARY_PATH
    assert launched.config_paths[1] == prefs


@pytest.mark.parametrize(
    ("variable", "read"),
    [
        ("ZECRET_DIARY_PATH", lambda launch: launch.diary_paths[0]),
        ("ZECRET_CONFIG_PATH", lambda launch: launch.config_paths[0]),
    ],
)
def test_an_empty_env_var_counts_as_unset(launched, monkeypatch, variable, read):
    """`Path("")` is `Path(".")`, so an exported-but-empty variable must not
    be read as a request to open the current directory."""
    monkeypatch.setenv(variable, "")
    monkeypatch.setattr("sys.argv", ["zecret"])
    entry_point.main()
    assert read(launched) != Path(".")
