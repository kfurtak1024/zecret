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

The hero's terminal is checked too, and it is the reason this note exists:
that picture is hand-drawn HTML rather than a screenshot, so it drifts
exactly the way a screenshot does and nothing renders differently when it
has. It had lost a key -- the app advertised eight and the page drew seven,
missing the one that locks the diary.

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


# --- the hero's terminal ---------------------------------------------------


def bar_key(binding: Binding) -> str:
    """How the key bar spells a binding, which is not how the table does.

    The bar is a picture of a terminal, so it says what the terminal says:
    Textual's footer writes a chord in caret notation, where the table
    below spells it out in <kbd> elements.
    """
    key = key_display(binding)
    return f"^{key.removeprefix('ctrl+')}" if key.startswith("ctrl+") else key


def drawn_bar(page: str, section: str | None = None) -> list[tuple[str, str]]:
    """The key bar of one drawn terminal, as (key, what it says it does).

    `section` names the <section> to look inside; the hero is not in one,
    so it is found by being the first bar on the page.
    """
    if section is not None:
        found = re.search(rf'<section id="{section}">.*?</section>', page, re.S)
        assert found, f"the page should still have a {section} section"
        page = found.group(0)
    bar = re.search(r'<span class="bar">(.*?)</span>\s*</pre>', page, re.S)
    assert bar, "that terminal should draw a key bar"
    pairs = re.findall(r'<span class="key">(.*?)</span>([^<]*)', bar.group(1))
    return [(key, description.strip()) for key, description in pairs]


def footer_bar(screen: type) -> list[tuple[str, str]]:
    """What a screen's own key bar holds, in the order it holds it."""
    return [
        (bar_key(binding), binding.description)
        for binding in documented_bindings(screen.BINDINGS)
        if binding.show
    ]


def test_the_hero_draws_the_key_bar_the_app_has(page):
    """Every key, worded the same and in the same order.

    The hero is a drawing of the entry list, and a drawing that shows keys
    the app does not have -- or misses one it does -- is worse than no
    picture, because it is read as a screenshot.
    """
    assert drawn_bar(page) == footer_bar(EntryListScreen)


def test_the_covered_page_draws_the_editors_key_bar(page):
    """The same check for the other terminal the page draws with a bar of
    its own: it is a picture of the editor, so it answers to the editor's
    bindings."""
    assert drawn_bar(page, "covered") == footer_bar(EditorScreen)


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
    stops being true by accident.

    The page's own address is not somewhere else, which is what lets it
    carry a canonical link: Pages answers on both the domain in docs/CNAME
    and the github.io address, and naming the real one is how a search
    engine is told they are one page rather than two. Read from CNAME
    rather than written here, so moving the domain moves this with it.
    Still strict about everything else, `http://` on that domain included.
    """
    own_site = (REPO / "docs" / "CNAME").read_text(encoding="utf-8").strip()
    resources = re.findall(r'<(?:script|link|img|iframe)[^>]*\s(?:src|href)="([^"]+)"', page)
    remote = [
        url
        for url in resources
        if url.startswith(("http://", "//"))
        or (
            url.startswith("https://")
            and "raw.githubusercontent.com" not in url
            and not url.startswith(f"https://{own_site}/")
        )
    ]
    assert not remote, f"the page pulls in remote resources: {remote}"


def test_the_page_has_no_analytics(page):
    for tracker in ("google-analytics", "googletagmanager", "plausible", "umami", "gtag("):
        assert tracker not in page.lower(), f"analytics found on the page: {tracker}"


# --- the drawn month -------------------------------------------------------


def hero_august(page: str) -> tuple[set[int], int]:
    """The August days the hero's entry list shows, and the count it claims.

    The hero draws the sample diary's entry list, so its August rows are
    the page's own statement of which days that diary holds.
    """
    hero = page[: page.index('<section id="features">')]
    block = re.search(
        r'<span class="head">\s*August 2026 · (\d+) entries</span>\n(.*?)\n\s*\n', hero, re.S
    )
    assert block, "the hero should still list an August of entries"
    days = {int(d) for d in re.findall(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\d\d)", block.group(2))}
    return days, int(block.group(1))


def calendar_marks(page: str) -> set[int]:
    """The days the drawn month marks as written.

    A cell is `f"{day:>3}{mark}"`, so a written day is a number with the
    bullet against it. The legend below the grid carries a bullet too, with
    no day in front of it.
    """
    section = re.search(r'<section id="which-day">.*?</section>', page, re.S)
    assert section, "the page should still have a which-day section"
    return {int(d) for d in re.findall(r"(\d{1,2})•", section.group(0))}


def test_the_hero_agrees_with_itself_about_august(page):
    """The month heading counts the rows underneath it."""
    days, claimed = hero_august(page)
    assert len(days) == claimed, f"the heading says {claimed} entries and {len(days)} are drawn"


def test_the_drawn_month_marks_the_days_the_hero_lists(page):
    """The two terminals draw the same diary, so they must agree on it.

    Both are hand-drawn, and this is the half nothing else can see: the key
    bars are checked against the app's bindings, but which days the sample
    was written on lives only in these two pictures. They had drifted apart
    -- the hero listed the 1st, 4th, 9th, 12th and 13th, and the calendar
    put its marks on the 9th through the 13th, inventing two evenings and
    losing two others.
    """
    listed, _ = hero_august(page)
    assert calendar_marks(page) == listed
