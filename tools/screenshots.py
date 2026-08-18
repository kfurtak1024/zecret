"""Regenerate the screenshots in assets/.

    uv run python tools/screenshots.py

Screenshots are the one piece of documentation nothing can test: no check
fails when a picture shows a footer from three keybindings ago. So they are
generated rather than taken by hand, and regenerating them is one command
that anyone can run without setting a scene first.

Each shot drives the real app through Textual's Pilot against a throwaway
diary in a temp directory -- never ~/.zecret, which belongs to whoever is
running this. Textual writes SVG; the PNGs the README and the product page
embed are rendered from that with inkscape or rsvg-convert.

The sample diary is written here rather than loaded from a fixture on
purpose: these images end up on a public page, so what they say should be
dull, plausible and nobody's actual life.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from textual.pilot import Pilot

from zecret.app import ZecretApp
from zecret.models import Entry
from zecret.storage import DiaryFile

REPO = Path(__file__).resolve().parents[1]
ASSETS = REPO / "assets"

PASSWORD = "a passphrase nobody uses"

#: Columns every shot is taken at. Wide enough for the whole footer.
COLUMNS = 100

#: Rows, per screen. One size for all of them either leaves the short
#: screens half empty or cuts the help popup off mid-list, and a shot of a
#: popup that runs off the bottom reads as a bug rather than as a feature.
ROWS = {
    "entries": 18,
    "editor": 20,
    "date": 18,
    "search": 20,
    # The whole popup: logo, every key -- navigation included, which is
    # most of them -- and the notes underneath. Two columns of keys brought
    # this down from 50; it is the height the popup stops scrolling at, so
    # it tracks the layout rather than being padded for safety. Guarded by
    # SHOT_ROWS in tests/test_help_screen.py, since a cropped screenshot is
    # not something any test can see.
    "help": 34,
}

#: Width of the rendered PNGs, matching what the README embeds.
PNG_WIDTH = 1365

#: (theme name in Textual, suffix on the filename).
THEMES = [("textual-dark", "dark"), ("textual-light", "light")]

#: A fortnight of unremarkable days across two months, so the month
#: headings and their counts both have something to show.
SAMPLE = [
    (
        dt.date(2026, 8, 13),
        "Long walk once the rain stopped. The lane past the mill was under\n"
        "water again, so I went up the hill instead and found an orchard\n"
        "nobody seems to be picking.\n"
        "\n"
        "Came back the long way. Worth it.",
    ),
    (
        dt.date(2026, 8, 12),
        "Finished the book about lighthouse keepers. The last chapter was\nworth the slow middle.",
    ),
    (
        dt.date(2026, 8, 9),
        "Coffee with Sam. We talked about moving north again, and this time\n"
        "it sounded less like talking.",
    ),
    (
        dt.date(2026, 8, 4),
        "Bread came out flat. Too impatient with the second prove, which is\n"
        "the same mistake as last time.",
    ),
    (dt.date(2026, 8, 1), "Quiet start to the month. Spent the evening fixing the gate."),
    (dt.date(2026, 7, 29), "Swam before breakfast. Cold, then not. Rain came in by noon."),
    (dt.date(2026, 7, 24), "Turned the desk to face the window. Better already."),
    (dt.date(2026, 7, 18), "Rain all day. Made soup, read, did not go out once."),
]

#: What the search shot has been typed into it. Narrows eight days to three,
#: which shows the filter doing something -- "the" matches almost
#: everything and demonstrates nothing.
SEARCH_QUERY = "rain"


def seed(path: Path) -> None:
    """Write the sample diary the screenshots are taken of."""
    diary, key = DiaryFile.create_new(path, PASSWORD)
    for date, body in SAMPLE:
        diary.add_entry(Entry.new(date, body))
    diary.save(key)


async def unlock(pilot: Pilot[None]) -> None:
    from textual.widgets import Input

    pilot.app.screen.query_one("#password", Input).value = PASSWORD
    await pilot.press("enter")
    await pilot.pause()
    await pilot.pause()


async def entries(pilot: Pilot[None]) -> None:
    """The diary itself: days under month headings, most recent first."""


async def editor(pilot: Pilot[None]) -> None:
    """Writing a day."""
    await pilot.press("enter")
    await pilot.pause()


async def date(pilot: Pilot[None]) -> None:
    """The which-day modal."""
    await pilot.press("g")
    await pilot.pause()


async def search(pilot: Pilot[None]) -> None:
    """Live filtering."""
    await pilot.press("slash")
    await pilot.pause()
    await pilot.pause()
    from textual.widgets import Input

    pilot.app.screen.query_one("#query", Input).value = SEARCH_QUERY
    await pilot.pause()
    await pilot.pause()


async def help_popup(pilot: Pilot[None]) -> None:
    """Every key, over the diary rather than instead of it."""
    await pilot.press("question_mark")
    await pilot.pause()
    await pilot.pause()


SHOTS: dict[str, Callable[[Pilot[None]], Awaitable[None]]] = {
    "entries": entries,
    "editor": editor,
    "date": date,
    "search": search,
    "help": help_popup,
}


async def capture(name: str, theme: str, suffix: str, diary_path: Path, workspace: Path) -> Path:
    """Drive the app to one screen and save it as SVG."""
    config_path = workspace / f"config-{suffix}.json"
    config_path.write_text(json.dumps({"theme": theme, "lock_after_minutes": 15}))

    app = ZecretApp(diary_path=diary_path, config_path=config_path)
    svg = workspace / f"{name}-{suffix}.svg"
    async with app.run_test(size=(COLUMNS, ROWS[name])) as pilot:
        await unlock(pilot)
        await SHOTS[name](pilot)
        app.save_screenshot(str(svg))
    return svg


def to_png(svg: Path, png: Path) -> None:
    """Render an SVG to PNG with whichever converter is installed."""
    if shutil.which("rsvg-convert"):
        command = ["rsvg-convert", "-w", str(PNG_WIDTH), "-o", str(png), str(svg)]
    elif shutil.which("inkscape"):
        command = [
            "inkscape",
            str(svg),
            "--export-type=png",
            f"--export-filename={png}",
            f"--export-width={PNG_WIDTH}",
        ]
    else:  # pragma: no cover - depends on the machine, not on Zecret
        raise SystemExit(
            "Need rsvg-convert (librsvg) or inkscape to turn the SVG into a PNG.\n"
            "  Debian/Ubuntu: sudo apt install librsvg2-bin\n"
            "  macOS:         brew install librsvg"
        )
    subprocess.run(command, check=True, capture_output=True)


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="zecret-shots-") as scratch:
        workspace = Path(scratch)
        diary_path = workspace / "diary.enc"
        seed(diary_path)

        for name in SHOTS:
            for theme, suffix in THEMES:
                svg = await capture(name, theme, suffix, diary_path, workspace)
                png = ASSETS / f"{name}-{suffix}.png"
                to_png(svg, png)
                print(f"  {png.relative_to(REPO)}")

    print("\nScreenshots regenerated. Check them before committing -- a shot")
    print("of the wrong screen still looks like a screenshot.")


if __name__ == "__main__":
    if not ASSETS.is_dir():
        sys.exit(f"no assets directory at {ASSETS}")
    asyncio.run(main())
