"""Tests for zecret.config.

Required coverage:
    - A missing config file yields defaults rather than an error: that is
      the ordinary first run.
    - A corrupt, empty, or wrong-shaped file also yields defaults. A
      mangled preference must never be why the diary cannot be opened.
    - save() round-trips through load(), creating the directory if needed.
    - The lock timeout round-trips, and a value that is not a whole
      non-negative number of minutes falls back to the default.
    - Nothing about the diary is written to it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zecret.config import DEFAULT_CONFIG_PATH, DEFAULT_LOCK_AFTER_MINUTES, DEFAULT_THEME, Config


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return tmp_path / "config.json"


# --- loading ---------------------------------------------------------------


def test_missing_file_loads_defaults(config_path):
    config = Config.load(config_path)
    assert config.theme == DEFAULT_THEME
    assert config.path == config_path


def test_missing_file_is_not_created_by_loading(config_path):
    Config.load(config_path)
    assert not config_path.exists(), "reading preferences must not write any"


def test_saved_theme_is_read_back(config_path):
    config_path.write_text(json.dumps({"theme": "gruvbox"}))
    assert Config.load(config_path).theme == "gruvbox"


def test_unknown_keys_are_ignored(config_path):
    """Forward compatibility: a newer Zecret's extra settings must not stop
    an older one from reading the theme."""
    config_path.write_text(json.dumps({"theme": "nord", "something_new": 42}))
    assert Config.load(config_path).theme == "nord"


@pytest.mark.parametrize(
    "content",
    ["", "{not json", "[]", '"a string"', "null", json.dumps({"theme": ""}), json.dumps({})],
    ids=["empty", "invalid", "list", "string", "null", "blank-theme", "no-theme"],
)
def test_unusable_file_falls_back_to_defaults(config_path, content):
    config_path.write_text(content)
    assert Config.load(config_path).theme == DEFAULT_THEME


def test_non_utf8_file_falls_back_to_defaults(config_path):
    config_path.write_bytes(b"\xff\xfe\x00garbage")
    assert Config.load(config_path).theme == DEFAULT_THEME


def test_wrong_typed_theme_falls_back_to_defaults(config_path):
    config_path.write_text(json.dumps({"theme": ["nord"]}))
    assert Config.load(config_path).theme == DEFAULT_THEME


def test_unreadable_file_falls_back_to_defaults(tmp_path):
    """A directory where the file should be: still no reason to fail."""
    directory = tmp_path / "config.json"
    directory.mkdir()
    assert Config.load(directory).theme == DEFAULT_THEME


# --- saving ----------------------------------------------------------------


def test_save_round_trips(config_path):
    config = Config.load(config_path)
    config.theme = "solarized-light"
    config.save()
    assert Config.load(config_path).theme == "solarized-light"


def test_save_creates_the_directory(tmp_path):
    nested = tmp_path / "deeply" / "nested" / "config.json"
    config = Config(path=nested, theme="nord")
    config.save()
    assert nested.exists()


def test_save_writes_only_preferences(config_path):
    """The one file Zecret writes in the clear says nothing about the
    diary -- no entries, no dates, no password."""
    config = Config(path=config_path, theme="nord", lock_after_minutes=5)
    config.save()
    # Spelled out rather than checked key by key: this is the assertion
    # that would catch anything about the diary being added to the file.
    assert json.loads(config_path.read_text()) == {"theme": "nord", "lock_after_minutes": 5}


def test_save_overwrites_an_existing_file(config_path):
    Config(path=config_path, theme="nord").save()
    Config(path=config_path, theme="dracula").save()
    assert Config.load(config_path).theme == "dracula"


def test_save_replaces_a_corrupt_file(config_path):
    config_path.write_text("{not json")
    config = Config.load(config_path)
    config.theme = "nord"
    config.save()
    assert Config.load(config_path).theme == "nord"


# --- the real path ---------------------------------------------------------


def test_default_config_path_is_under_home():
    """Sanity check that tests never point at the user's own preferences."""
    assert Path.home() / ".zecret" / "config.json" == DEFAULT_CONFIG_PATH


def test_the_lock_timeout_round_trips(config_path):
    Config(path=config_path, lock_after_minutes=30).save()
    assert Config.load(config_path).lock_after_minutes == 30


def test_never_locking_round_trips(config_path):
    """Zero is a real choice, not a missing value."""
    Config(path=config_path, lock_after_minutes=0).save()
    assert Config.load(config_path).lock_after_minutes == 0


@pytest.mark.parametrize(
    "value",
    [-1, "15", 15.5, True, None, [], {"minutes": 15}],
    ids=["negative", "string", "fraction", "bool", "null", "list", "object"],
)
def test_a_lock_timeout_that_is_not_minutes_falls_back(config_path, value):
    """A negative wait would lock the diary the instant it opened, and a
    bool is an int in Python without being a number of minutes."""
    config_path.write_text(json.dumps({"lock_after_minutes": value}))
    assert Config.load(config_path).lock_after_minutes == DEFAULT_LOCK_AFTER_MINUTES


def test_a_bad_lock_timeout_does_not_cost_the_theme(config_path):
    """Each preference falls back on its own; one bad value must not throw
    away the rest of the file."""
    config_path.write_text(json.dumps({"theme": "nord", "lock_after_minutes": -5}))
    config = Config.load(config_path)
    assert config.theme == "nord"
    assert config.lock_after_minutes == DEFAULT_LOCK_AFTER_MINUTES
