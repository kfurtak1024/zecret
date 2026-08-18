"""One popup of help: what this is, every key, and the rules keys cannot express.

A ModalScreen, which is Textual's pattern for a dialog -- its bindings take
precedence and the screen underneath dims, so the diary stays visible
behind the help rather than being replaced by it. Textual also ships a
HelpPanel, but that is a different thing: context-sensitive keys for the
widget that happens to have focus, docked as a side split. This page is
about the app, not about the focused widget.

The key list is built from the screens' own BINDINGS rather than written
out here. A hand-kept copy would be wrong the first time a binding changed
and nobody would notice -- the whole point of a help page is that it can be
trusted.

Every binding appears, not just the ones marked show=True. That flag decides
what fits in the footer, which is a question about eighty columns rather
than about what is worth knowing: the keys that get around a long diary are
some of the most useful in the app and none of them would survive the
budget. This page is where they are told to you, and it is why leaving a
binding out of the bar costs nothing.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from zecret import __version__
from zecret.screens.date_prompt import DatePromptScreen
from zecret.screens.editor import EditorScreen
from zecret.screens.search import SearchScreen
from zecret.screens.settings import SettingsScreen
from zecret.screens.unlock import UnlockScreen

#: Block-letter ZECRET. Kept as one constant so it can be swapped whole,
#: and rendered without wrapping -- see MIN_LOGO_WIDTH for what happens
#: when the terminal is too narrow to hold it.
LOGO = r"""
███████╗███████╗ ██████╗██████╗ ███████╗████████╗
╚══███╔╝██╔════╝██╔════╝██╔══██╗██╔════╝╚══██╔══╝
  ███╔╝ █████╗  ██║     ██████╔╝█████╗     ██║
 ███╔╝  ██╔══╝  ██║     ██╔══██╗██╔══╝     ██║
███████╗███████╗╚██████╗██║  ██║███████╗   ██║
╚══════╝╚══════╝ ╚═════╝╚═╝  ╚═╝╚══════╝   ╚═╝
""".strip("\n")

#: Below this many columns the logo cannot be drawn without being cut in
#: half, which looks broken rather than decorative -- so it is dropped and
#: the help itself, which is the point, keeps the room.
MIN_LOGO_WIDTH = max(len(line) for line in LOGO.splitlines()) + 6

TAGLINE = f"An encrypted terminal diary · v{__version__}"

CLOSE_HINT = "esc or ? to close"

#: A section longer than this is laid out in two columns rather than one
#: long list. A key row is barely twenty columns wide, so a single column
#: spends height the popup does not have on width it is not using -- and
#: the entry list's eighteen keys are most of the page. Short sections stay
#: in one column: two columns of one row each is a table, not a list.
COLUMN_THRESHOLD = 8

#: Blank columns kept between two side-by-side columns of keys, so the
#: right-aligned keys of the second do not run into the descriptions of the
#: first.
COLUMN_GAP = 4

#: What the page covers, in the order you meet it. EntryListScreen is
#: missing on purpose: importing it here would close a cycle (it imports
#: this screen to open it), and the list's own keys are passed in instead.
#:
#: The last group merges four screens rather than giving each its own
#: heading: they advertise little beyond "escape goes back", and four
#: headings over one line each tells the reader less than one heading over
#: four does. Duplicates collapse, so this stays a merge and not an edit --
#: every binding any of those screens advertises still appears.
SECTIONS: list[tuple[str, list[list[BindingType]]]] = [
    ("Writing a day", [EditorScreen.BINDINGS]),
    (
        "Anywhere else",
        [
            DatePromptScreen.BINDINGS,
            SearchScreen.BINDINGS,
            SettingsScreen.BINDINGS,
            UnlockScreen.BINDINGS,
        ],
    ),
]

#: The rules no key can express. Kept short: this is a popup, and every
#: line here is a line of the diary it is covering.
NOTES = [
    "One entry per day — reopening a day continues it.",
    "Days are local, and never later than today.",
    "No password recovery. Lose it and the diary is gone.",
]


def documented_bindings(bindings: list[BindingType]) -> list[Binding]:
    """Every binding a screen declares, in the order it declares them.

    Not filtered by `show`: that decides what fits in the footer, and a key
    left out of eighty columns is still a key. Screens are expected to
    declare their bindings in the order a reader wants them -- what you do
    first, then what you do rarely, then how you move around.
    """
    return [binding for binding in bindings if isinstance(binding, Binding)]


class HelpScreen(ModalScreen[None]):
    """Every key Zecret answers to, over the diary rather than instead of it."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", priority=True),
        Binding("question_mark", "back", "Close", key_display="?"),
    ]

    def __init__(self, list_bindings: list[BindingType]) -> None:
        """Args:
        list_bindings: The entry list's BINDINGS. Passed in rather than
            imported, since the entry list imports this screen.
        """
        super().__init__()
        self.list_bindings = list_bindings
        # The narrowest terminal two columns of keys can be drawn in, worked
        # out from the rows themselves while composing them. Nothing here
        # knows how wide a description is until the bindings are read, and
        # guessing would either stack columns that fit or squeeze ones that
        # do not.
        self.min_columns_width = 0

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-box"):
            yield Static(LOGO, id="help-logo")
            yield Label(TAGLINE, id="help-tagline")

            yield Label("The diary", classes="section-title")
            yield from self.section_keys([self.list_bindings])

            # The short sections sit side by side rather than stacking:
            # between them they are five rows of content under two headings,
            # and the popup has more width to spend than height.
            with Horizontal(classes="help-columns"):
                for title, groups in SECTIONS:
                    with Vertical(classes="help-column"):
                        yield Label(title, classes="section-title")
                        yield from self.section_keys(groups)

            yield Label("Worth knowing", classes="section-title")
            for note in NOTES:
                yield Label(f"• {note}", classes="help-note")

            yield Label(CLOSE_HINT, id="help-close-hint")

    def on_mount(self) -> None:
        self.fit_width()

    def on_resize(self) -> None:
        self.fit_width()

    def fit_width(self) -> None:
        """Match the layout to the room the terminal is giving it."""
        self.fit_logo()
        self.fit_columns()

    def fit_logo(self) -> None:
        """Show the logo only where there is room to draw all of it."""
        self.query_one("#help-logo", Static).display = self.size.width >= MIN_LOGO_WIDTH

    def fit_columns(self) -> None:
        """Stack the columns where the terminal is too narrow to pair them.

        Same bargain as the logo: two columns squeezed until the
        descriptions truncate tell the reader less than one column they have
        to scroll. Stacking preserves reading order, since a stacked column
        is read after the one that was beside it, not interleaved with it.
        """
        stacked = self.size.width < self.min_columns_width
        for row in self.query(".help-columns"):
            row.styles.layout = "vertical" if stacked else "horizontal"

    def section_keys(self, groups: list[list[BindingType]]) -> ComposeResult:
        """One row per key across `groups`, aligned into a column or two.

        Keys are rendered the way the footer renders them (ctrl+s as ^s,
        and a binding's own key_display honoured), so a key that does reach
        the bar reads the same in both places. Rows repeated across screens
        -- "esc  Back" on every one of them -- are listed once; two keys
        doing the same thing are not, so g and home each get a line, which
        is right, since the reader needs to know both exist.

        A long section is split down the middle into two columns, read down
        and then across. Both halves are aligned to the same key width, so
        the split reads as one section laid out in two columns rather than
        as two sections that happen to be adjacent.
        """
        rows: list[tuple[str, str]] = []
        for bindings in groups:
            for binding in documented_bindings(bindings):
                row = (self.app.get_key_display(binding), binding.description)
                if row not in rows:
                    rows.append(row)

        width = max((len(display) for display, _ in rows), default=0)
        if len(rows) <= COLUMN_THRESHOLD:
            yield from self.key_labels(rows, width)
            return

        self.note_columns_width(rows, width)
        half = (len(rows) + 1) // 2
        with Horizontal(classes="help-columns"):
            for chunk in (rows[:half], rows[half:]):
                with Vertical(classes="help-column"):
                    yield from self.key_labels(chunk, width)

    def key_labels(self, rows: list[tuple[str, str]], width: int) -> ComposeResult:
        """The rows of one column, keys right-aligned to `width`."""
        for display, description in rows:
            yield Label(f"{display:>{width}}   {description}", classes="help-key")

    def note_columns_width(self, rows: list[tuple[str, str]], width: int) -> None:
        """Record how wide a terminal these rows need to sit in two columns.

        Two of the widest row, the gap between them, and the box's own
        border and padding.
        """
        widest = max(width + 3 + len(description) for _display, description in rows)
        chrome = 2 + 2 * 2  # border, then padding: 1 2
        self.min_columns_width = max(self.min_columns_width, 2 * widest + COLUMN_GAP + chrome)

    def action_back(self) -> None:
        self.dismiss()
