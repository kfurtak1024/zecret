"""CLI entry point: `zecret` launches the Textual app.

Supports:
    zecret                              # default diary and preferences
    zecret --path /custom/diary.enc     # override diary location
    zecret --config /custom/prefs.json  # override preferences location
    zecret --version                    # print the version and exit
    (or env vars ZECRET_DIARY_PATH / ZECRET_CONFIG_PATH)

Both environment variables are named in `--help`'s epilog rather than left
to this docstring. A variable nothing prints is a variable nobody finds:
`--help` is the only description of the command line a user ever sees, and
until they can read it there, the flags look like the whole interface.

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
    """The path environment variable `name` asks for, or None if it is silent.

    Unset and empty mean the same thing here -- nothing. `Path("")` is
    `Path(".")`, so treating them differently would read `ZECRET_DIARY_PATH=`
    as a request to open a diary named after the current directory.

    Handed back as the string it is, for argparse to convert: a string
    default goes through the argument's `type` the same as a typed value,
    so a path that cannot be made sense of is the same usage error from
    either place rather than a traceback from this one.
    """
    return os.environ.get(name) or None


def _user_path(value: str) -> Path:
    """`value` as a path, with a leading `~` meaning the home directory.

    A shell expands `~` only where it is unquoted and starts a word, so
    `export ZECRET_DIARY_PATH="~/diary.enc"` and `--path=~/diary.enc` both
    arrive with the tilde intact. Taken literally that is a directory named
    `~` under the current one, and Zecret offered to create a new, empty
    diary there -- to someone whose real one was exactly where they said.

    Raises:
        argparse.ArgumentTypeError: if the home directory it names cannot
            be found -- `~nobody/`, or no HOME and no password entry.
            expanduser() raises RuntimeError for that, which argparse
            would let through as a traceback.
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
        # The epilog is laid out in columns; the default formatter would
        # reflow it into a paragraph.
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"zecret {__version__}",
        # The help popup shows this too, but only once the diary is open --
        # so without this, saying which version misbehaved means first
        # unlocking it. What you run should be answerable without a password.
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
