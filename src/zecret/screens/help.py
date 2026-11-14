"""One popup of help: what this is, every key, and the rules keys cannot express.

A ModalScreen, so the diary stays visible behind it. Not Textual's
HelpPanel, which documents whichever widget has focus rather than the app.

The key list is generated from the screens' own BINDINGS, never written
out here, so it cannot go stale. Every binding appears, whatever its
`show`: that flag decides only what goes in the footer.
"""

from __future__ import annotations

from typing import ClassVar, NamedTuple

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from zecret import __version__
from zecret.screens.base import plain
from zecret.screens.calendar_view import CalendarScreen
from zecret.screens.date_prompt import DatePromptScreen
from zecret.screens.editor import EditorScreen
from zecret.screens.entry_list import EntryListScreen
from zecret.screens.header import DiaryFooter
from zecret.screens.password import PasswordScreen
from zecret.screens.search import SearchScreen
from zecret.screens.settings import SettingsScreen
from zecret.screens.unlock import UnlockScreen

#: Block-letter ZECRET, rendered without wrapping.
LOGO = r"""
███████╗███████╗ ██████╗██████╗ ███████╗████████╗
╚══███╔╝██╔════╝██╔════╝██╔══██╗██╔════╝╚══██╔══╝
  ███╔╝ █████╗  ██║     ██████╔╝█████╗     ██║
 ███╔╝  ██╔══╝  ██║     ██╔══██╗██╔══╝     ██║
███████╗███████╗╚██████╗██║  ██║███████╗   ██║
╚══════╝╚══════╝ ╚═════╝╚═╝  ╚═╝╚══════╝   ╚═╝
""".strip("\n")

#: Below this many columns the logo would be cut off, so it is hidden.
MIN_LOGO_WIDTH = max(len(line) for line in LOGO.splitlines()) + 6

TAGLINE = f"An encrypted terminal diary · v{__version__}"

CLOSE_HINT = "esc or ? to close"

#: A section with more rows than this is laid out in two columns, trading
#: width the popup has for height it does not.
COLUMN_THRESHOLD = 8

#: Blank columns between two side-by-side columns of keys.
COLUMN_GAP = 4


class Section(NamedTuple):
    """One heading on the page and the keys listed under it."""

    title: str
    #: One binding list per screen the section covers. Rows repeated
    #: between them are listed once.
    groups: list[list[BindingType]]
    #: Whether rows already listed under "The diary" are left out here,
    #: because the shared keys mean the same thing.
    shares_diary_keys: bool = False


#: The list's own section, first on the page.
DIARY = Section("The diary", [EntryListScreen.BINDINGS])

#: The sections after the list's, shown side by side, one column each.
#:
#: The calendar omits what the list has already said (lock, help, quit).
#: The editor does not: its ctrl+l saves before it locks. The last section
#: merges four screens that advertise little beyond "escape goes back";
#: duplicates collapse, so every binding still appears.
SECTIONS: list[Section] = [
    Section("The calendar", [CalendarScreen.BINDINGS], shares_diary_keys=True),
    Section("Writing a day", [EditorScreen.BINDINGS]),
    Section(
        "Anywhere else",
        [
            DatePromptScreen.BINDINGS,
            PasswordScreen.BINDINGS,
            SearchScreen.BINDINGS,
            SettingsScreen.BINDINGS,
            UnlockScreen.BINDINGS,
        ],
    ),
]

#: Between a key and what it does.
KEY_GAP = "   "


def key_width(rows: list[tuple[str, str]]) -> int:
    """How wide the widest key in `rows` is: the column they align to."""
    return max((len(display) for display, _ in rows), default=0)


#: The rules no key can express. Kept short.
NOTES = [
    "One entry per day — reopening a day continues it.",
    "A phrase between *asterisks* is emphasised as you write it.",
    "Days are local, and never later than today.",
    "No password recovery. Lose it and the diary is gone.",
]


def documented_bindings(bindings: list[BindingType]) -> list[Binding]:
    """Every binding a screen declares, in declaration order.

    Not filtered by `show`. Screens declare bindings in reading order.
    """
    return [binding for binding in bindings if isinstance(binding, Binding)]


class HelpScreen(ModalScreen[None]):
    """Every key Zecret answers to, shown over the diary."""

    #: "Close" for both keys. Only escape is on the bar: one key per
    #: action there.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Close", priority=True),
        Binding("question_mark", "back", "Close", key_display="?", show=False),
        Binding("ctrl+l", "app.lock", "Lock", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        # The narrowest terminal the page's columns fit side by side in,
        # measured from the rows while composing them.
        self.min_columns_width = 0

    def compose(self) -> ComposeResult:
        # Not base.card(), and focusable on purpose: this panel has no
        # fields, so focusing it is what the arrow keys scroll with.
        with VerticalScroll(id="help-box"):
            yield Static(LOGO, id="help-logo")
            yield Label(TAGLINE, id="help-tagline")

            yield Label(DIARY.title, classes="section-title")
            yield from self.section_keys(DIARY.groups)
            diary_rows = self.key_rows(DIARY.groups)

            # The short sections sit side by side, and are measured like
            # any other set of columns so a narrow terminal stacks them.
            omits = [diary_rows if section.shares_diary_keys else [] for section in SECTIONS]
            self.note_columns_width(
                [
                    max(
                        len(section.title), self.rows_width(self.section_rows(section.groups, omit))
                    )
                    for section, omit in zip(SECTIONS, omits, strict=True)
                ]
            )
            with Horizontal(classes="help-columns"):
                for section, omit in zip(SECTIONS, omits, strict=True):
                    with Vertical(classes="help-column"):
                        yield Label(section.title, classes="section-title")
                        yield from self.section_keys(section.groups, omit)

            yield Label("Worth knowing", classes="section-title")
            for note in NOTES:
                yield Label(f"• {note}", classes="help-note")

            yield Label(CLOSE_HINT, id="help-close-hint")
        # Its own bar, as every popup has: the box covers the bar beneath
        # only up to its own width.
        yield DiaryFooter()

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

        Stacking keeps reading order: a stacked column follows the one
        that was beside it.
        """
        stacked = self.size.width < self.min_columns_width
        for row in self.query(".help-columns"):
            row.styles.layout = "vertical" if stacked else "horizontal"

    def key_rows(self, groups: list[list[BindingType]]) -> list[tuple[str, str]]:
        """Every (key, description) row across `groups`, repeats dropped.

        Keys are rendered as the footer renders them (ctrl+s as ^s, and
        key_display honoured).
        """
        rows: list[tuple[str, str]] = []
        for bindings in groups:
            for binding in documented_bindings(bindings):
                row = (self.app.get_key_display(binding), binding.description)
                if row not in rows:
                    rows.append(row)
        return rows

    def section_keys(
        self, groups: list[list[BindingType]], omit: list[tuple[str, str]] | None = None
    ) -> ComposeResult:
        """One row per key across `groups`, aligned into a column or two.

        Identical rows repeated across screens are listed once. Two keys
        doing the same thing each get a line. Rows in `omit` are left out.

        A long section is split down the middle into two columns, read
        down then across, both aligned to the same key width.
        """
        rows = self.section_rows(groups, omit)

        width = key_width(rows)
        if len(rows) <= COLUMN_THRESHOLD:
            yield from self.key_labels(rows, width)
            return

        half = (len(rows) + 1) // 2
        self.note_columns_width([self.rows_width(rows)] * 2)
        with Horizontal(classes="help-columns"):
            for chunk in (rows[:half], rows[half:]):
                with Vertical(classes="help-column"):
                    yield from self.key_labels(chunk, width)

    def section_rows(
        self, groups: list[list[BindingType]], omit: list[tuple[str, str]] | None = None
    ) -> list[tuple[str, str]]:
        """The rows a section lists: its keys, less any in `omit`."""
        return [row for row in self.key_rows(groups) if row not in (omit or [])]

    def rows_width(self, rows: list[tuple[str, str]]) -> int:
        """How wide the widest of `rows` is, laid out by key_labels."""
        width = key_width(rows)
        return max((width + len(KEY_GAP) + len(description) for _, description in rows), default=0)

    def key_labels(self, rows: list[tuple[str, str]], width: int) -> ComposeResult:
        """The rows of one column, keys right-aligned to `width`."""
        for display, description in rows:
            yield Label(plain(f"{display:>{width}}{KEY_GAP}{description}"), classes="help-key")

    def note_columns_width(self, widths: list[int]) -> None:
        """Record how wide a terminal these columns need to sit side by side.

        `widths` is each column's widest line. Columns share the row
        equally (`1fr` in app.tcss), so each needs room for the widest,
        plus the gaps and the box's border and padding. Every set of
        columns is measured, and the widest need decides when all stack.
        """
        chrome = 2 + 2 * 2  # border, then padding: 1 2
        needed = len(widths) * max(widths) + (len(widths) - 1) * COLUMN_GAP + chrome
        self.min_columns_width = max(self.min_columns_width, needed)

    def action_back(self) -> None:
        self.dismiss()
