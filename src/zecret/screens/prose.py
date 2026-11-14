"""What the editor reads out of a line of prose, as plain functions.

Where the words are (for the mask), where an *emphasised phrase* is (for
the colour), and what counts as a word character (for moving by a word).
No Textual and no widget: a line in, offsets out.
"""

from __future__ import annotations

from typing import NamedTuple

#: What a covered character is drawn as. One cell wide, which is what lets
#: it be swapped in for a character without changing the line's width.
BAR = "▆"

#: What a phrase is wrapped in to emphasise it: *like this*.
STRONG = "*"


def is_word(character: str) -> bool:
    """Whether `character` is one that words are made of: what `\\w` matches."""
    return character.isalnum() or character == "_"


def word_runs(line: str) -> list[tuple[int, int]]:
    """Every maximal run of non-blank characters in `line`, as [start, end).

    A "word" here is anything with no space in it. "don't" and "well-worn"
    are not split and trailing punctuation stays inside, because each run
    is covered by one bar and a bar that broke at an apostrophe would show
    where the apostrophes are.

    The gaps between runs stay uncovered, so masked text keeps the shape
    of the writing. That leaks every word's length: the mask is a screen
    against a glance, not a cipher.
    """
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, character in enumerate(line):
        if character.isspace():
            if start is not None:
                runs.append((start, index))
                start = None
        elif start is None:
            start = index
    if start is not None:
        runs.append((start, len(line)))
    return runs


def run_at(runs: list[tuple[int, int]], column: int) -> tuple[int, int] | None:
    """The run the cursor is touching, if any.

    Both ends count: while typing, the cursor sits just past the last
    letter of the word being written. Runs are separated by at least one
    blank, so no two can claim the same column.
    """
    for start, end in runs:
        if start <= column <= end:
            return (start, end)
    return None


class StrongSpan(NamedTuple):
    """Where one *emphasised phrase* sits in a line, in character offsets.

    `start`..`text_start` is the opening run of asterisks,
    `text_start`..`text_end` the phrase, `text_end`..`end` the closing run.
    """

    start: int
    text_start: int
    text_end: int
    end: int


def strong_spans(line: str) -> list[StrongSpan]:
    """Every *emphasised phrase* in `line`, left to right and never nested.

    Markdown's flanking rule, cut down: a run of asterisks opens a phrase
    if a non-space follows it, and closes one if a non-space precedes it.
    A run is taken whole, so `**bold**` marks a phrase as `*bold*` does.

    One deliberate departure: a phrase may not open straight after a
    digit. Flanking alone leaves "2 * 3" alone but emphasises "4 packs and
    2" in "3*4 packs and 2*6 bottles". Digits only, not letters, so a
    script written without spaces can still emphasise mid-line.

    A run that could only open while a phrase is already open is passed
    over, and an unclosed phrase is not a phrase. Spans never cross a
    line: an asterisk left open would otherwise colour the rest of the
    day. There is no escape for a literal asterisk; a mispaired one costs
    a phrase its colour and nothing else.
    """
    spans: list[StrongSpan] = []
    opened: tuple[int, int] | None = None
    length = len(line)
    index = 0
    while (start := line.find(STRONG, index)) != -1:
        # find() rather than a character at a time: this runs on every
        # line drawn, and almost no line holds an asterisk.
        index = start + 1
        while index < length and line[index] == STRONG:
            index += 1
        closes = start > 0 and not line[start - 1].isspace()
        opens = (
            index < length
            and not line[index].isspace()
            and (start == 0 or not line[start - 1].isdigit())
        )
        if opened is not None:
            if closes:
                spans.append(StrongSpan(opened[0], opened[1], start, index))
                opened = None
        elif opens:
            opened = (start, index)
    return spans
