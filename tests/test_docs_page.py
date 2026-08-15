"""Tests that the product page still describes the app it is selling.

docs/index.html is hand-written marketing copy, which is exactly the kind
of file that quietly goes stale: nothing breaks when a binding is renamed
or a theme is dropped, and nobody re-reads a landing page they wrote
months ago. So the few claims on it that mirror the code are checked here,
the same way the in-app help page is generated from BINDINGS rather than
typed out.

Prose is deliberately not checked. What is checked are the facts a reader
would act on: which keys exist, how many themes there are, the Argon2
parameters, and which Python it needs.

On keys the check runs both ways but is not symmetric: every key the app
puts in its footer must be on the page, and no key on the page may be one
the app does not have. In between sit the bindings that never reach the
footer -- navigation, mostly -- which the page is free to describe in prose
rather than to tabulate.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from textual.binding import Binding

from zecret.crypto import KdfParams
from zecret.screens.editor import EditorScreen
from zecret.screens.entry_list import EntryListScreen
from zecret.screens.help import documented_bindings
from zecret.screens.settings import THEMES

REPO = Path(__file__).resolve().parents[1]
PAGE = REPO / "docs" / "index.html"


@pytest.fixture(scope="module")
def page() -> str:
    return PAGE.read_text(encoding="utf-8")


def key_display(binding: Binding) -> str:
    """How the page writes a binding's key.

    Mirrors App.get_key_display closely enough for the names this app
    actually binds, without needing a running app to ask.
    """
    if binding.key_display:
        return binding.key_display
    return {"escape": "esc", "ctrl+s": "ctrl+s"}.get(binding.key, binding.key)


def page_keys(page: str) -> set[str]:
    """Every key the page's table advertises, as written there.

    A row spells a chord across several <kbd> elements, so they are joined
    back up: <kbd>ctrl</kbd> + <kbd>s</kbd> is the one key "ctrl+s".
    """
    table = re.search(r'<section id="keys">.*?</section>', page, re.S)
    assert table, "the page should still have a keys section"

    keys = set()
    for row in re.findall(r"<tr>(.*?)</tr>", table.group(0), re.S):
        chord = re.findall(r"<kbd>(.*?)</kbd>", row)
        if chord:
            keys.add("+".join(part.strip() for part in chord))
    return keys


def app_keys() -> set[str]:
    """Every key the app binds on the two screens the page covers.

    The page may list any of these; it may not list anything else.
    """
    return {
        key_display(binding)
        for screen in (EntryListScreen, EditorScreen)
        for binding in documented_bindings(screen.BINDINGS)
    }


def required_keys() -> set[str]:
    """The keys the page must carry: the ones the app puts in its footer.

    Not the whole keymap. Getting around the list takes eight bindings that
    pair up into four ideas, and spelling each out would turn a table
    someone skims into one they skip -- the page says what they are in
    prose instead, and the in-app help popup is the exhaustive reference.
    What must never happen is the page naming a key the app does not have,
    or dropping one the app puts in front of every user.
    """
    return {
        key_display(binding)
        for screen in (EntryListScreen, EditorScreen)
        for binding in documented_bindings(screen.BINDINGS)
        if binding.show
    }


# --- keys ------------------------------------------------------------------


def test_the_page_lists_every_key_the_app_puts_in_its_footer(page):
    missing = required_keys() - page_keys(page)
    assert not missing, f"docs/index.html does not mention: {sorted(missing)}"


def test_the_page_invents_no_keys(page):
    """A binding removed from the app must not linger on the page."""
    invented = page_keys(page) - app_keys()
    assert not invented, f"docs/index.html advertises keys the app lacks: {sorted(invented)}"


# --- other claims a reader would act on ------------------------------------


def test_the_theme_count_is_right(page):
    counted = len(THEMES)
    words = {8: "Eight", 9: "Nine", 10: "Ten", 6: "Six", 7: "Seven"}
    assert words.get(counted, str(counted)).lower() in page.lower(), (
        f"the page should say there are {counted} themes"
    )


def test_the_argon2_parameters_match(page):
    defaults = KdfParams.generate()
    assert f"time_cost {defaults.time_cost}" in page
    assert f"parallelism {defaults.parallelism}" in page
    assert f"{defaults.memory_cost // 1024} MiB" in page


def test_the_python_requirement_matches(page):
    metadata = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    floor = metadata["project"]["requires-python"].lstrip(">=~^ ")
    assert f"Python {floor}" in page, f"the page should ask for Python {floor}"


def test_the_default_diary_path_is_right(page):
    assert "~/.zecret/diary.enc" in page


# --- the page keeps its own promises ---------------------------------------


def test_the_page_loads_nothing_from_anywhere_else(page):
    """No fonts, scripts or stylesheets from other hosts: the page makes a
    point of not tracking anyone, and third-party requests are how that
    stops being true by accident."""
    resources = re.findall(r'<(?:script|link|img|iframe)[^>]*\s(?:src|href)="([^"]+)"', page)
    remote = [
        url
        for url in resources
        if url.startswith(("http://", "//"))
        or (url.startswith("https://") and "raw.githubusercontent.com" not in url)
    ]
    assert not remote, f"the page pulls in remote resources: {remote}"


def test_the_page_has_no_analytics(page):
    for tracker in ("google-analytics", "googletagmanager", "plausible", "umami", "gtag("):
        assert tracker not in page.lower(), f"analytics found on the page: {tracker}"
