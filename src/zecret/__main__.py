"""CLI entry point: `zecret` launches the Textual app.

    zecret                              # default diary and preferences
    zecret --path /custom/diary.enc     # override diary location
    zecret --config /custom/prefs.json  # override preferences location
    zecret --version                    # print the version and exit
    (or env vars ZECRET_DIARY_PATH / ZECRET_CONFIG_PATH)

The two paths are independent. Preferences belong to the person rather
than to the file, so a diary opened with --path keeps the usual theme.
--config is for running a different build without writing the preferences
you actually use.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from zecret import __version__
from zecret.app import ZecretApp
from zecret.storage import DEFAULT_DIARY_PATH

ENVIRONMENT_HELP = """\
environment variables:
  ZECRET_DIARY_PATH    same as --path, for every run in this shell
  ZECRET_CONFIG_PATH   same as --config, likewise

A flag wins over the matching variable, and a variable set to nothing at
all counts as unset rather than as the current directory.
"""


def _from_env(name: str) -> str | None:
    """The path environment variable `name` asks for, or None.

    Empty counts as unset: `Path("")` is the current directory. Returned
    as a string so argparse converts it through the argument's `type`, and
    a bad value is the same usage error from either source.
    """
    return os.environ.get(name) or None


def _user_path(value: str) -> Path:
    """`value` as a path, with a leading `~` expanded.

    A shell leaves the tilde alone in `--path=~/diary.enc` and in a quoted
    variable, and a literal `~` directory is not what was meant.

    Raises:
        argparse.ArgumentTypeError: if the home directory it names cannot
            be found.
    """
    try:
        return Path(value).expanduser()
    except RuntimeError as error:
        raise argparse.ArgumentTypeError(f"{value}: {error}") from error


def main() -> None:
    """Parse args/env, construct ZecretApp, and run it."""
    parser = argparse.ArgumentParser(
        prog="zecret",
        description="A modern, encrypted terminal diary.",
        epilog=ENVIRONMENT_HELP,
        # Keeps the epilog's columns.
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"zecret {__version__}",
        help="Show the version and exit.",
    )
    parser.add_argument(
        "--path",
        type=_user_path,
        default=_from_env("ZECRET_DIARY_PATH") or DEFAULT_DIARY_PATH,
        help="Path to the encrypted diary file (default: ~/.zecret/diary.enc).",
    )
    parser.add_argument(
        "--config",
        type=_user_path,
        # None, not DEFAULT_CONFIG_PATH: ZecretApp resolves the default when
        # constructed, which is what lets tests redirect it.
        default=_from_env("ZECRET_CONFIG_PATH"),
        help="Path to the preferences file (default: ~/.zecret/config.json).",
    )
    args = parser.parse_args()

    app = ZecretApp(diary_path=args.path, config_path=args.config)
    app.run()


if __name__ == "__main__":
    main()
