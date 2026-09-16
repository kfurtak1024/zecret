"""Tests for strength.py: how strong a master password is said to be.

This is the one piece of Zecret that hands the master password to code
nobody here wrote, and the reason it does is that the alternative lies.
So what is worth guarding is not that a number comes back -- it is that
the ratings are the right way round on the passwords a heuristic gets
backwards, and that nothing it returns can break the single fixed row it
has to be drawn on.

Required coverage:
    - A passphrase rates strong and a common password does not. This is
      the whole reason for the dependency: "Password1234" has twelve
      characters and three character classes, so length-and-classes would
      call it strong, and it is among the first few thousand guesses
      anyone makes.
    - A long run of one character is not strong either. It is what
      "length is strength" gets wrong, and what a prefix catches.
    - A password longer than zxcvbn will accept is rated rather than
      refused. zxcvbn raises ValueError past its own limit, so a naive
      call would take the screen down on the next keystroke.
    - Rating a prefix is a floor, never a claim: a long password is never
      rated lower than what its first characters would score alone.
    - An empty field is not rated at all -- there is nothing yet to have
      an opinion about.
    - A rating that cannot be made says nothing rather than guessing. The
      fallback exists because zxcvbn raises past its own length guard, and
      it must never fail towards "strong".
    - The line always fits the width it was built for, for any password
      and any width a card might have. The row is fixed at one line and
      clips rather than wraps, so a line that overruns loses its end with
      nothing to say it happened.
    - The bar is always the full number of segments wide, so the text
      after it starts in the same column whatever the score.
    - A warning is rewritten to continue the sentence it is joined to
      rather than to open one. The capital comes off a word that was only
      capitalised for being first, and stays on an initialism.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import zecret.strength
from zecret.strength import (
    HOLLOW,
    LABELS,
    MAX_SCORED,
    NEEDS_HELP,
    SEGMENTS,
    Strength,
    _sentence,
    rate,
)

#: The narrowest row this is ever drawn on -- the create screen's card,
#: which is narrower than the password dialog's. Measured against the real
#: widget in tests/test_password_screen.py; used here as the width the
#: wording has to survive.
NARROWEST = 54


def test_a_passphrase_is_strong() -> None:
    strength = rate("correct horse battery staple", NARROWEST)
    assert strength is not None
    assert strength.score == SEGMENTS
    assert strength.label == "Strong"


def test_a_common_password_dressed_up_is_not_strong() -> None:
    """The case that decides the whole design. Twelve characters, upper,
    lower and digits -- every signal a home-grown meter can see says
    strong, and it is one of the first guesses anyone makes."""
    strength = rate("Password1234", NARROWEST)
    assert strength is not None
    assert strength.score <= NEEDS_HELP
    assert strength.label != "Strong"


def test_a_long_run_of_one_character_is_not_strong() -> None:
    """What "length is strength" gets wrong, and why a password past the
    scoring limit is rated on a prefix rather than waved through."""
    strength = rate("x" * 100, NARROWEST)
    assert strength is not None
    assert strength.score == 0


def test_a_password_past_the_scoring_limit_is_rated_not_refused() -> None:
    """zxcvbn raises ValueError beyond its own maximum length, so a plain
    call would take the screen down on the keystroke after it."""
    strength = rate("correct horse battery staple " * 8, NARROWEST)
    assert strength is not None
    assert strength.score == SEGMENTS


def test_rating_a_prefix_never_overstates_a_long_password() -> None:
    """A password is never weaker than its own opening, so the prefix's
    score is a floor under the real one rather than a guess at it."""
    prefix = "correct horse battery staple and a few more words besides now"[:MAX_SCORED]
    longer = prefix + "and then a great deal more text after it entirely"
    floor = rate(prefix, NARROWEST)
    whole = rate(longer, NARROWEST)
    assert floor is not None and whole is not None
    assert whole.score >= floor.score


def test_an_empty_field_is_not_rated() -> None:
    assert rate("", NARROWEST) is None


def test_a_weak_password_is_told_what_to_do_about_it() -> None:
    strength = rate("hunter2", NARROWEST)
    assert strength is not None
    assert strength.reason, "a weak password should carry advice"


def test_a_strong_password_is_not_nagged() -> None:
    strength = rate("correct horse battery staple", NARROWEST)
    assert strength is not None
    assert strength.reason == ""


def test_a_warning_reads_as_part_of_the_sentence_it_is_joined_to() -> None:
    """zxcvbn's warnings open a sentence and this one continues one, after
    a dash, so the capital has to come off.

    "A word by itself is easy to guess." is the case that gets this wrong:
    str.isupper() ignores uncased characters, so "A " is upper by that
    measure and a guard that looks at the first two characters together
    leaves the capital on. Every other warning has a lowercase second
    letter and so was lowercased correctly, which is what hid it.
    """
    strength = rate("dictionary", NARROWEST)
    assert strength is not None
    assert strength.reason.startswith("a word by itself"), strength.reason


def test_an_initialism_keeps_its_capitals() -> None:
    """What the guard is actually for -- only a capital that is there for
    being first comes off."""
    assert _sentence("NIST says otherwise.") == "NIST says otherwise."
    assert _sentence("This is a very common password.") == "this is a very common password."


def test_a_rating_that_cannot_be_made_says_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """If zxcvbn's own length guard ever moves under MAX_SCORED, the call
    starts raising. Saying nothing is the safe way to be wrong: a line that
    vanishes is a smaller failure than one claiming a password is strong
    because the rating never ran."""

    def refuses(_password: str) -> dict[str, object]:
        raise ValueError("Password exceeds max length")

    monkeypatch.setattr(zecret.strength, "zxcvbn", refuses)
    assert rate("correct horse battery staple", NARROWEST) is None


def test_the_bar_is_always_the_full_width() -> None:
    """So the label after it starts in the same column at every score."""
    for password in ("x" * 100, "hunter2", "diary2024", "correct horse battery staple"):
        strength = rate(password, NARROWEST)
        assert strength is not None
        assert len(strength.bar) == SEGMENTS


def test_an_empty_bar_still_reads_as_a_bar() -> None:
    """Score zero is four hollow segments, not an empty string -- the row
    should not appear to lose its bar at the worst rating of all."""
    assert Strength(0, LABELS[0], "").bar == HOLLOW * SEGMENTS


@settings(max_examples=200, deadline=None)
@given(
    password=st.text(min_size=1, max_size=120),
    width=st.integers(min_value=15, max_value=120),
)
def test_the_line_always_fits_the_width_it_was_built_for(password: str, width: int) -> None:
    """The row is one fixed line and clips rather than wraps, so a line
    that overruns loses its end with nothing to say it happened.

    Fifteen is where the floor sits: the bar, its gap and the longest
    label come to that, and below it there is nothing left to give back --
    the advice has already gone. Every card in the app is far wider.
    """
    strength = rate(password, width)
    if strength is None:
        return
    assert len(strength.line()) <= width
