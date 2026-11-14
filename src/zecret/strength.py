"""How strong a master password is, for the two screens that choose one.

Rated with zxcvbn, which scores against lists of real passwords, words,
names, keyboard runs and dates. Length and character classes are the wrong
things to look at: "Password1234" passes them and is among the first
guesses made.

This module is the only place the master password is handed to third-party
code: one import, one call site.

Advisory only. The screens show the rating and accept whatever was typed.
"""

from __future__ import annotations

from typing import NamedTuple

from zxcvbn import zxcvbn

#: The bar's blocks. Both are one cell wide, so len() measures the line,
#: and they differ in shape so the bar reads without colour.
FILLED = "▰"
HOLLOW = "▱"

#: One segment per step of zxcvbn's 0-4 score.
SEGMENTS = 4

#: What each score is called.
LABELS = ("Very weak", "Weak", "Fair", "Good", "Strong")

#: Scores at or below this come with advice.
NEEDS_HELP = 2

#: Said when zxcvbn has no specific complaint, or one too long for the row.
GENERIC_HELP = "use a few more words."

#: zxcvbn raises ValueError past this length. A longer password is rated on
#: its first MAX_SCORED characters: it is never weaker than its own prefix,
#: so that score is a floor.
MAX_SCORED = 72


class Strength(NamedTuple):
    """A rated password: the score, and what to say about it.

    `reason` already fits the width it was built for, and is empty when
    there is nothing to add.
    """

    score: int
    label: str
    reason: str

    @property
    def bar(self) -> str:
        """The score as a row of blocks, always SEGMENTS cells wide."""
        return FILLED * self.score + HOLLOW * (SEGMENTS - self.score)

    def line(self) -> str:
        """The whole reading as one line."""
        if not self.reason:
            return f"{self.bar}  {self.label}"
        return f"{self.bar}  {self.label} — {self.reason}"


def rate(password: str, width: int) -> Strength | None:
    """Rate `password` in a line that fits `width` cells, or None for an
    empty field.

    The row this goes on is one fixed line that cuts off what does not
    fit, so advice too long for `width` is replaced by shorter advice, or
    dropped, rather than truncated.
    """
    if not password:
        return None
    try:
        result = zxcvbn(password[:MAX_SCORED])
    except ValueError:
        # zxcvbn's length guard, should MAX_SCORED ever drift. Saying
        # nothing is safer than a rating that never ran.
        return None

    score = int(result["score"])
    label = LABELS[score]
    if score > NEEDS_HELP:
        return Strength(score, label, "")

    # Room left once the bar, the gap, the label and the dash have theirs.
    room = width - len(FILLED * SEGMENTS) - len("  ") - len(label) - len(" — ")
    warning = str(result["feedback"]["warning"] or "")
    reason = _sentence(warning) if warning else ""
    if not reason or len(reason) > room:
        reason = GENERIC_HELP if len(GENERIC_HELP) <= room else ""
    return Strength(score, label, reason)


def _sentence(warning: str) -> str:
    """zxcvbn's warning, lower-cased to follow a dash.

    Only a first letter capitalised for being first is changed, so an
    initialism keeps its capitals. The second character is tested alone
    (`[1:2]`): `"A ".isupper()` is True, since isupper() ignores the space.
    """
    if warning[:1].isupper() and not warning[1:2].isupper():
        return warning[0].lower() + warning[1:]
    return warning
