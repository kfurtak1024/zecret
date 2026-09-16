"""How strong a master password is, for the two screens that choose one.

Rating a password honestly needs a dictionary. Length and the mix of
character classes are what a home-grown meter can see, and they are the
wrong things to look at: "Password1234" has twelve characters and three
classes and is among the first few thousand guesses anyone makes, while
"correct horse battery staple" has one class and is past anything a
guesser reaches. A meter built on what is visible would call the first
strong and would be telling the writer of a diary with no password
recovery exactly the wrong thing.

So this defers to zxcvbn, which scores against lists of real passwords,
words, names, keyboard runs and dates, and returns how many guesses it
thinks the password is worth. **This module is the only place the master
password is handed to third-party code.** It is in-process and zxcvbn does
no I/O of its own, but the chokepoint is deliberate: one import, one call
site, one place to look if that ever has to be reconsidered.

Nothing here is a rule. The screens show what comes back and go on to
accept whatever was typed -- see FormScreen.advise_on_password.
"""

from __future__ import annotations

from typing import NamedTuple

from zxcvbn import zxcvbn

#: The bar, drawn in filled and hollow blocks. Both are one cell wide, so
#: the bar's width in cells is its width in characters and a line built
#: from it can be measured with len() the way the rest of this module
#: does. They also differ in shape as well as in weight, which is what
#: keeps the bar readable where the colour does not arrive -- the same
#: bargain the editor's emphasis makes with bold.
FILLED = "▰"
HOLLOW = "▱"

#: One segment per step of zxcvbn's 0-4 score, which is four segments and
#: five readings: an empty bar is "very weak" rather than "no opinion",
#: and the field being empty shows no bar at all instead.
SEGMENTS = 4

#: What each score is called. zxcvbn's own scale, named in the app's
#: voice rather than in numbers -- a score of 3/4 says nothing to someone
#: choosing a password.
LABELS = ("Very weak", "Weak", "Fair", "Good", "Strong")

#: Scores at or below this get told what to do about it. Above it the bar
#: has said enough, and a suggestion attached to "Good" would be nagging.
NEEDS_HELP = 2

#: Said when zxcvbn has no specific complaint, or has one too long to fit
#: the row. It is the advice that is right in almost every case: length
#: made of words is what a guesser cannot cheaply enumerate.
GENERIC_HELP = "use a few more words."

#: zxcvbn 4.5.0 refuses a password longer than this, raising ValueError --
#: so it must never be handed one. A longer password is rated on its
#: first MAX_SCORED characters instead of being waved through: a password
#: is never weaker than its own prefix, so the prefix's score is a floor
#: rather than a guess, and the floor is the safe end to be wrong at.
#:
#: Waving it through was tried first and is wrong. "Length is strength"
#: holds for a passphrase and not for a hundred of the same letter, which
#: the prefix catches and a length check calls strong.
MAX_SCORED = 72


class Strength(NamedTuple):
    """A rated password: the score, and what to say about it.

    `reason` is already trimmed to fit whatever width it was built for,
    and is empty when there is nothing to add -- either because the
    password is good enough to need no advice or because zxcvbn's own
    wording was too long for the row and the generic advice took its
    place.
    """

    score: int
    label: str
    reason: str

    @property
    def bar(self) -> str:
        """The score as a row of blocks, always SEGMENTS cells wide."""
        return FILLED * self.score + HOLLOW * (SEGMENTS - self.score)

    def line(self) -> str:
        """The whole thing as one line, ready for the row it goes on."""
        if not self.reason:
            return f"{self.bar}  {self.label}"
        return f"{self.bar}  {self.label} — {self.reason}"


def rate(password: str, width: int) -> Strength | None:
    """Rate `password`, in a line that fits `width` cells. None to say
    nothing at all.

    Nothing is said for an empty field: there is no password yet to have
    an opinion about, and a bar sitting at "very weak" over an untouched
    field would be a complaint about not having started.

    A password longer than MAX_SCORED is rated on its first MAX_SCORED
    characters, which reads as a floor under the real score rather than
    as an estimate of it -- see that constant.

    `width` is passed in rather than assumed because the two screens that
    call this have cards of different widths, and the row they write on is
    a single fixed row -- a line too long for it is cut off at the edge
    rather than wrapped, which would lose the end of the sentence with
    nothing to say it happened. The advice is dropped back to something
    shorter instead, so the line is always whole.
    """
    if not password:
        return None
    try:
        result = zxcvbn(password[:MAX_SCORED])
    except ValueError:
        # zxcvbn's own guard on the length, which MAX_SCORED is supposed
        # to have kept us the right side of. If that ever drifts, saying
        # nothing is the safe way to be wrong: an advisory line that
        # vanishes is a smaller failure than one that claims a password is
        # strong because the rating never ran.
        return None

    score = int(result["score"])
    label = LABELS[score]
    if score > NEEDS_HELP:
        return Strength(score, label, "")

    # Room left for the advice, once the bar, the gap, the label and the
    # dash that joins them have taken theirs.
    room = width - len(FILLED * SEGMENTS) - len("  ") - len(label) - len(" — ")
    warning = str(result["feedback"]["warning"] or "")
    reason = _sentence(warning) if warning else ""
    if not reason or len(reason) > room:
        # zxcvbn's specific complaint is the more useful of the two and is
        # preferred whenever it fits; several of its longer ones do not,
        # and are better replaced than truncated mid-word.
        reason = GENERIC_HELP if len(GENERIC_HELP) <= room else ""
    return Strength(score, label, reason)


def _sentence(warning: str) -> str:
    """zxcvbn's warning, reworded to follow a dash rather than open a line.

    Only the first letter changes, and only when it is one that was
    capitalised for being first: "This is a very common password." becomes
    "this is a very common password.", which is what the line needs after
    "Weak — ". Left alone otherwise, so a warning that starts with a name
    or an initialism keeps it.

    The second character is tested with `warning[1:2]` and not with
    `warning[:2]`, which is the same test for almost every warning and
    wrong for the one that matters. `str.isupper()` ignores uncased
    characters and asks only that the cased ones are capitals, so "A " is
    upper by that measure -- and zxcvbn's "A word by itself is easy to
    guess." was the one warning that reached the row with a capital still
    on it, mid-sentence, after a dash.
    """
    if warning[:1].isupper() and not warning[1:2].isupper():
        return warning[0].lower() + warning[1:]
    return warning
