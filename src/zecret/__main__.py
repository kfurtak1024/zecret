"""CLI entry point: `zecret` launches the Textual app.

Supports:
    zecret                              # default diary and preferences
    zecret --path /custom/diary.enc     # override diary location
    zecret --config /custom/prefs.json  # override preferences location
    (or env vars ZECRET_DIARY_PATH / ZECRET_CONFIG_PATH)

The two are independent, and neither implies the other. Preferences are
settings for the person rather than for the file, so a diary opened with
--path still uses the same theme -- that is why config.py has a fixed path
of its own, and it stays the default here.

--config is for the case that rule does not cover: running a *different
build* of Zecret. Pointing --path at a scratch diary keeps development
away from what you wrote, but without this the same run would still read
and write the real preferences file, so testing the settings screen
changes the theme you actually use. Which file to develop against is not a
preference; it is a property of the run.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from zecret.app import ZecretApp
from zecret.storage import DEFAULT_DIARY_PATH


def _from_env(name: str) -> Path | None:
    """The path environment variable `name` asks for, or None if it is silent.

    Unset and empty mean the same thing here -- nothing. `Path("")` is
    `Path(".")`, so treating them differently would read `ZECRET_DIARY_PATH=`
    as a request to open a diary named after the current directory.
    """
    value = os.environ.get(name)
    return Path(value) if value else None


def main() -> None:
    """Parse args/env, construct ZecretApp, and run it."""
    parser = argparse.ArgumentParser(
        prog="zecret", description="A modern, encrypted terminal diary."
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=_from_env("ZECRET_DIARY_PATH") or DEFAULT_DIARY_PATH,
        help="Path to the encrypted diary file (default: ~/.zecret/diary.enc).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        # Falls through as None rather than naming DEFAULT_CONFIG_PATH here.
        # ZecretApp resolves that default when it is constructed, which is
        # what lets the tests redirect it; spelling it out at this end would
        # hand the app a real path and route around them.
        default=_from_env("ZECRET_CONFIG_PATH"),
        help="Path to the preferences file (default: ~/.zecret/config.json).",
    )
    args = parser.parse_args()

    app = ZecretApp(diary_path=args.path, config_path=args.config)
    app.run()


if __name__ == "__main__":
    main()
