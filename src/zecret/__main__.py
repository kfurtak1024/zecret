"""CLI entry point: `zecret` launches the Textual app.

Supports:
    zecret                          # use default diary path
    zecret --path /custom/diary.enc # override diary location
    (or env var ZECRET_DIARY_PATH)

Only the diary is configurable here. Preferences live at a fixed per-user
path (see config.py): they are settings for the person, not for the file,
so a diary opened with --path still uses the same theme.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from zecret.app import ZecretApp
from zecret.storage import DEFAULT_DIARY_PATH


def main() -> None:
    """Parse args/env, construct ZecretApp, and run it."""
    parser = argparse.ArgumentParser(
        prog="zecret", description="A modern, encrypted terminal diary."
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path(os.environ.get("ZECRET_DIARY_PATH", DEFAULT_DIARY_PATH)),
        help="Path to the encrypted diary file (default: ~/.zecret/diary.enc).",
    )
    args = parser.parse_args()

    app = ZecretApp(diary_path=args.path)
    app.run()


if __name__ == "__main__":
    main()
