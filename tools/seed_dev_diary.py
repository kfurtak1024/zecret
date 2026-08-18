"""Build a throwaway diary to develop against.

    uv run python tools/seed_dev_diary.py

Development needs a diary with something in it. Three days of "test test
test" will not show you that a month heading wraps, that a snippet is
truncated in the wrong place, or that search is slow -- and the only other
diary on the machine with enough in it to show those things is the one
that belongs to whoever is running this. So this writes a fake one: a few
hundred days of dull, plausible, nobody's-actual-life entries at a path
that is not the real diary, behind a password printed on the terminal.

It **refuses to write anywhere near ~/.zecret**, which is the point of it
existing rather than being a paragraph in the README telling you to be
careful. Pass --path to put it somewhere else, --force to replace one you
already made.

Deterministic: the same --seed gives the same diary, so a layout bug you
found once is still there after you regenerate. The generated prose is
assembled from fragments rather than written out, because the interesting
thing about it is its *shape* -- how long, how many, how spread out --
and shape is what fragments can produce a lot of cheaply.

A handful of days get deliberately awkward entries instead (see
EDGE_CASES): the empty-ish one, the enormous one, the one that is a single
unbroken line. Those are the ones that break a layout, and hunting for
them is easier when the tool tells you which days they landed on.

Today is deliberately left unwritten, so "n" -- write about today -- has
something to do the moment the diary opens.
"""

from __future__ import annotations

import argparse
import datetime as dt
import random
import sys
from pathlib import Path

from zecret.models import Entry
from zecret.storage import DEFAULT_DIARY_PATH, DiaryFile

REPO = Path(__file__).resolve().parents[1]

#: Inside the checkout rather than in $HOME, and gitignored. Deleting the
#: clone takes the dev diary with it instead of orphaning it, and a git
#: worktree gets one of its own rather than sharing main's. Resolved from
#: this file rather than the working directory, so where you run it from
#: does not change where it lands.
DEFAULT_DEV_PATH = REPO / ".zecret-dev" / "diary.enc"

#: Weak on purpose and printed on the terminal: this diary is furniture.
DEFAULT_PASSWORD = "dev"

#: Roughly ten months back, which gives the entry list enough month
#: headings to scroll through and search enough to narrow down.
DEFAULT_DAYS = 300

#: Days that get an entry. Not 1.0: the gaps are what make the list look
#: like a diary rather than a log, and an entry list with no gaps never
#: shows you what a missing month looks like.
DENSITY = 0.62

WEATHER = [
    "Rain most of the morning, then a bright hour around four.",
    "Cold enough for the good coat.",
    "Grey all day without ever quite raining.",
    "Warm again. The garden has decided it is summer.",
    "Wind got up overnight and took a fence panel with it.",
    "Fog until noon, and then a completely different day underneath it.",
    "First frost. The car took ten minutes to see out of.",
    "Too hot to do anything useful before evening.",
]

DOINGS = [
    "Walked as far as the market and back the long way.",
    "Spent most of the afternoon on the shelves. Two more to go.",
    "Made soup out of what was left in the drawer. Better than it deserved.",
    "Long call with Mum, mostly about the neighbours.",
    "Finally returned the library books, only three weeks late.",
    "Sorted the box of cables. Kept four, and I suspect that was three too many.",
    "Bread again. Better crumb this time, still pale on the bottom.",
    "Took the bike out for the first time since spring. Everything creaked, me included.",
    "Sat in the garden with a book and got through eleven pages.",
    "Cleared the gutter over the back door, which had become a small ecosystem.",
    "Coffee with Sam. We talked about moving north again.",
    "Repotted the big plant. It looked offended.",
    "Watched the second half of a film I had already forgotten the first half of.",
    "Cooked properly for once, and ate it at the table like a person.",
    "Went to the market early and came back with far too much fruit.",
]

REFLECTIONS = [
    "A good day, in the ordinary way that does not make a story.",
    "Slept badly and it showed in everything I tried to do.",
    "Quiet. I am learning not to mind that.",
    "Felt behind all day without being able to say what on.",
    "Nothing much happened and I am not complaining about it.",
    "Kept catching myself planning next week instead of being in this one.",
    "Tired in the good way for once.",
    "I keep meaning to start earlier and keep not doing it.",
]

#: A long entry that has to be handled somewhere, so it may as well be
#: one you can search for.
LONG_BODY = "\n\n".join(
    [
        "Woke early without meaning to, and rather than lie there arguing "
        "with myself about it I got up and went out while the street was "
        "still empty. There is a particular quiet to a town that has not "
        "started yet, and I do not see it often enough to have got used to "
        "it.",
        "Walked the long loop: down past the mill, along the water as far "
        "as the second bridge, then back up through the allotments. The "
        "allotments are the best part. Everyone there has built something "
        "slightly wrong out of pallets and netting, and every one of those "
        "wrong things is clearly the result of a long private argument "
        "with a specific pest.",
        "Stopped for coffee on the way back and sat outside even though it "
        "was too cold to, because sitting inside felt like giving the "
        "morning back. Read a few pages, mostly watched people arrive at "
        "work.",
        "The rest of the day did not live up to it, which I think is fine. "
        "Not every day has to be evenly good throughout. This one front-"
        "loaded everything and I got the benefit of it before nine.",
        "Long way of saying: get up early more often. I will not, but I should.",
    ]
)

#: (days back from the newest entry, what makes it awkward, the body).
#: These replace the generated entry for that day.
EDGE_CASES: list[tuple[int, str, str]] = [
    (0, "very long, many paragraphs", LONG_BODY),
    (1, "a single word", "Rain."),
    (2, "unicode and emoji", "Café, then the market. 🌧️ → ☀️ by four.\nBought pierogi. Świetnie."),
    (
        3,
        "one unbroken line, no spaces to wrap on",
        "Nothing worth writing down today except this: "
        + "a" * 40
        + "-"
        + "b" * 40
        + "-"
        + "c" * 40,
    ),
    (4, "blank lines around the text", "\n\n   Short, and padded with whitespace.   \n\n"),
    (5, "trailing newlines only", "Fine.\n\n\n"),
]


def build_body(rng: random.Random) -> str:
    """Assemble one ordinary day out of fragments."""
    sentences = [rng.choice(DOINGS)]
    if rng.random() < 0.55:
        sentences.insert(0, rng.choice(WEATHER))
    if rng.random() < 0.45:
        sentences.append(rng.choice(REFLECTIONS))

    body = " ".join(sentences)
    if rng.random() < 0.25:
        body += "\n\n" + rng.choice(REFLECTIONS)
    return body


def build_entries(days: int, seed: int, newest: dt.date) -> list[Entry]:
    """Generate the diary, newest entry on `newest` and going back `days`.

    Timestamps are put on the evening of the day they belong to rather than
    at the moment this runs. Nothing displays them, but a diary where every
    entry was created within the same millisecond is a lie that will be
    confusing to whoever first writes something that does read them.
    """
    rng = random.Random(seed)
    awkward = {offset: body for offset, _, body in EDGE_CASES}
    entries: list[Entry] = []

    for offset in range(days):
        date = newest - dt.timedelta(days=offset)
        if offset in awkward:
            body = awkward[offset]
        elif rng.random() >= DENSITY:
            continue
        else:
            body = build_body(rng)

        written = dt.datetime.combine(
            date, dt.time(hour=rng.randrange(18, 23), minute=rng.randrange(60)), tzinfo=dt.UTC
        )
        entries.append(Entry(date=date, body=body, created_at=written, updated_at=written))

    return entries


def refuse_the_real_diary(path: Path) -> None:
    """Stop before writing anything if `path` is the user's own diary.

    Checks the whole directory rather than just the filename. This tool
    exists to keep development away from a real diary, and "~/.zecret but a
    different filename" is close enough to that diary to be a mistake
    someone is making rather than a location they meant.
    """
    real = DEFAULT_DIARY_PATH.expanduser().resolve()
    target = path.expanduser().resolve()
    if real.parent in target.parents:
        sys.exit(
            f"refusing to seed {target}: that is inside {real.parent}, where the\n"
            f"real diary lives. Seed somewhere else -- {DEFAULT_DEV_PATH} is the default."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="seed_dev_diary",
        description="Write a throwaway diary with enough in it to develop against.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_DEV_PATH,
        help=f"Where to write it (default: {DEFAULT_DEV_PATH}).",
    )
    parser.add_argument(
        "--password",
        default=DEFAULT_PASSWORD,
        help=f"Master password for the throwaway diary (default: {DEFAULT_PASSWORD!r}).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"How many days back to go (default: {DEFAULT_DAYS}).",
    )
    parser.add_argument(
        "--seed", type=int, default=0, help="Random seed; the same seed gives the same diary."
    )
    parser.add_argument(
        "--force", action="store_true", help="Replace an existing diary at that path."
    )
    args = parser.parse_args()

    if args.days < 1:
        sys.exit("--days must be at least 1")

    path: Path = args.path.expanduser()
    refuse_the_real_diary(path)

    if path.exists():
        if not args.force:
            sys.exit(f"{path} already exists. Pass --force to replace it.")
        path.unlink()

    # Yesterday, so that today is still unwritten and "n" has something to
    # do the moment the diary opens.
    newest = dt.date.today() - dt.timedelta(days=1)
    entries = build_entries(args.days, args.seed, newest)

    diary, key = DiaryFile.create_new(path, args.password)
    for entry in entries:
        diary.add_entry(entry)
    diary.save(key)

    oldest = min(entry.date for entry in entries)
    print(f"Wrote {len(entries)} entries to {path}")
    print(f"  password:  {args.password}")
    print(f"  covering:  {oldest} to {newest} (today is left unwritten)")
    print("\nAwkward days on purpose:")
    for offset, label, _ in sorted(EDGE_CASES):
        print(f"  {newest - dt.timedelta(days=offset)}  {label}")
    print("\nOpen it, with preferences of its own so settings stay out of yours:")
    print(f"  uv run zecret --path {path} --config {path.parent / 'config.json'}")
    print("\n./zecret-dev.sh does both, and seeds this for you when it is missing.")


if __name__ == "__main__":
    main()
