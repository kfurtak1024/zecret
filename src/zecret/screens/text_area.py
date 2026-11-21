"""DiaryTextArea: the widget a day is written in.

Textual's TextArea with the editing keys it lacks, the mask, and the
colour on an *emphasised phrase*. The rules for where words and phrases
are live in prose.py; the screen around this widget is editor.py.
"""

from __future__ import annotations

from typing import ClassVar

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual.binding import Binding, BindingType
from textual.geometry import Region
from textual.reactive import reactive
from textual.strip import Strip
from textual.widgets import TextArea
from textual.widgets.text_area import Edit, EditResult, Location

from zecret.screens.prose import BAR, is_word, run_at, strong_spans, word_runs


class DiaryTextArea(TextArea):
    """Textual's text area with the editing keys it is missing, a mask,
    and emphasis.

    **Keys** are bound here rather than on the screen, which keeps them
    out of the help popup and the key bar: those document what Zecret does
    with a diary, and these are what any editor does with text.

    **The mask is drawn, never written.** It is laid over the text in
    get_line on its way to the screen; the document is untouched. Masking
    by rewriting the text would file an entry full of blocks.

    **Emphasis is drawn, never written**, and only ever colours. The
    asterisks stay on screen: hiding them would draw one character fewer
    than the document holds and put the cursor out of place.
    """

    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "diary-text-area--mask",
        "diary-text-area--strong",
        "diary-text-area--strong-marker",
    }

    #: Whether the writing is covered. The session's value lives on
    #: ZecretApp.masked.
    masked: reactive[bool] = reactive(False)

    BINDINGS: ClassVar[list[BindingType]] = [
        # TextArea has keys for the ends of a line but not of the text.
        Binding("ctrl+home", "document_start", "Start of the entry", show=False),
        Binding("ctrl+end", "document_end", "End of the entry", show=False),
        Binding("ctrl+shift+home", "document_start(True)", "Select to the start", show=False),
        Binding("ctrl+shift+end", "document_end(True)", "Select to the end", show=False),
        # A paragraph at a time. With soft wrap on, `down` moves by wrapped
        # row and a paragraph is one long document line.
        Binding("ctrl+up", "cursor_paragraph_up", "Previous paragraph", show=False),
        Binding("ctrl+down", "cursor_paragraph_down", "Next paragraph", show=False),
        Binding("ctrl+shift+up", "cursor_paragraph_up(True)", "Select a paragraph up", show=False),
        Binding(
            "ctrl+shift+down", "cursor_paragraph_down(True)", "Select a paragraph down", show=False
        ),
        # Overrides TextArea's ctrl+a, which is readline's "start of line".
        # `home` still does that.
        Binding("ctrl+a", "select_all", "Select all", show=False),
    ]

    #: The width the text was last wrapped at; see render_lines.
    _wrapped_at: int | None = None

    def __init__(self, text: str = "", *, soft_wrap: bool = True, id: str | None = None) -> None:
        """A text area that never highlights the cursor's line.

        TextArea paints that band after get_line, over the whole line and
        with a foreground colour, so it would wipe both the emphasis and
        the mask's ink on the line being typed.

        The signature names only what Zecret passes, so a misspelled
        keyword is a type error rather than swallowed by `**kwargs`.
        """
        super().__init__(text, soft_wrap=soft_wrap, highlight_cursor_line=False, id=id)

    # --- wrapping ----------------------------------------------------------

    def render_lines(self, crop: Region) -> list[Strip]:
        """Wrap to the width about to be drawn, if it changed.

        TextArea rewraps on the Resize message, which is queued and so
        arrives after the first paint at the new size: a long day drew one
        frame unwrapped. Wrapping here is inside the paint.

        Only the width is tracked. Everything else that changes the
        wrapping goes through TextArea's own rewrap at this same width.
        """
        width = self.wrap_width
        if width != self._wrapped_at:
            self._wrapped_at = width
            self.wrapped_document.wrap(width, tab_width=self.indent_width)
        return super().render_lines(crop)

    def edit(self, edit: Edit) -> EditResult:
        """Make an edit, then bring the cursor into view once more.

        TextArea.edit scrolls to the cursor before it grows the scrollable
        height to fit the edit, so a scroll to a row the edit just added
        falls one row short: Enter on the bottom line put the cursor out
        of sight. Scrolling again, once the height is right, reaches it.
        Only done when the edit changed the height.

        If Textual reorders the two itself, this second scroll finds
        nothing to do and can go.
        """
        height = self.virtual_size.height
        result = super().edit(edit)
        if self.virtual_size.height != height:
            self.scroll_cursor_visible()
        return result

    # --- emphasis ----------------------------------------------------------

    def _emphasise(self, line: Text) -> Text:
        """Colour every *emphasised phrase* in `line`, asterisks included.

        The phrase takes the emphasis colour and bold; the marks take the
        colour alone. Both attributes because each covers where the other
        gives out: bold is unreliable across terminals and fonts, colour
        is absent at sixteen colours or under NO_COLOR. Which colour is
        app.tcss's business.

        `line` is stylized in place; TextArea builds a fresh Text per call.
        """
        spans = strong_spans(line.plain)
        if not spans:
            return line

        ink = self.get_component_rich_style("diary-text-area--strong")
        marks = self.get_component_rich_style("diary-text-area--strong-marker")
        for span in spans:
            line.stylize(marks, span.start, span.text_start)
            line.stylize(ink, span.text_start, span.text_end)
            line.stylize(marks, span.text_end, span.end)
        return line

    # --- the mask ----------------------------------------------------------

    def get_line(self, line_index: int) -> Text:
        """The line as it should be drawn: emphasised, or covered.

        The mask wins: a masked line is never emphasised, since colour
        over a row of bars would show where the emphasis in a covered day
        is.

        Masked, every word but the one the cursor touches has each
        character swapped for BAR. Same number of characters and cells,
        so the cursor, wrapping and selection all land where they should.

        Only characters one cell wide are swapped. A two-cell character
        replaced by a one-cell bar would shorten the line, so those keep
        their glyph and are painted in ink the colour of their own
        background.
        """
        line = super().get_line(line_index)
        if not self.masked:
            return self._emphasise(line)

        cursor_row, cursor_column = self.cursor_location
        runs = word_runs(line.plain)
        revealed = run_at(runs, cursor_column) if line_index == cursor_row else None
        covered = [run for run in runs if run != revealed]
        if not covered:
            return line

        characters = list(line.plain)
        wide: list[int] = []
        for start, end in covered:
            for index in range(start, end):
                if cell_len(characters[index]) == 1:
                    characters[index] = BAR
                else:
                    wide.append(index)

        masked = Text("".join(characters), end=line.end, no_wrap=True)
        ink = self.get_component_rich_style("diary-text-area--mask")
        for start, end in covered:
            masked.stylize(ink, start, end)
        solid = Style(color=ink.color, bgcolor=ink.color)
        for index in wide:
            masked.stylize(solid, index, index + 1)
        return masked

    def watch_masked(self, masked: bool) -> None:
        """Cover or uncover the writing, and redraw.

        TextArea caches rendered lines and cannot know the mask changed.
        notify_style_update() is the public hook that clears that cache.

        The selection is painted after get_line and sets both colours, so
        it would read through the wide-character path of the mask. The
        `-masked` class lets app.tcss give the selection a bar of its own.
        """
        self.notify_style_update()
        self.set_class(masked, "-masked")
        self.refresh()

    # --- getting around ----------------------------------------------------

    def action_document_start(self, select: bool = False) -> None:
        """ctrl+home: to the first character of the day's text."""
        self.move_cursor((0, 0), select=select)

    def action_document_end(self, select: bool = False) -> None:
        """ctrl+end: to the last character of the day's text."""
        self.move_cursor(self.document.end, select=select)

    def _written(self, row: int) -> bool:
        """Whether `row` has anything on it but whitespace."""
        return bool(self.document[row].strip())

    def action_cursor_paragraph_up(self, select: bool = False) -> None:
        """ctrl+up: to the top of this paragraph, or of the one above it.

        A paragraph is a line of the document, not of the screen. Blank
        lines are stepped over. From mid-paragraph the first press goes to
        its start, as ctrl+left does with a word.
        """
        row, column = self.cursor_location
        if column > 0:
            self.move_cursor((row, 0), select=select)
            return
        previous = row - 1
        while previous >= 0 and not self._written(previous):
            previous -= 1
        self.move_cursor((max(previous, 0), 0), select=select)

    def action_cursor_paragraph_down(self, select: bool = False) -> None:
        """ctrl+down: to the start of the next paragraph, or to the end of
        the text after the last one."""
        row, _ = self.cursor_location
        following = row + 1
        while following < self.document.line_count and not self._written(following):
            following += 1
        if following >= self.document.line_count:
            self.move_cursor(self.document.end, select=select)
            return
        self.move_cursor((following, 0), select=select)

    def get_cursor_word_right_location(self) -> Location:
        """Where ctrl+right goes: the end of the next word.

        End-of-word going right and start-of-word going left is the
        platform convention (VS Code, GTK, readline's alt+f), not a bug.

        TextArea's own rule takes the next change of character class,
        which after punctuation lands at the start of the following word:
        `It rained. |Then` rather than `It rained.|`. Taking a run of
        same-class characters whole, with whitespace as a class of its
        own, fixes that.
        """
        row, column = self.cursor_location
        line = self.document[row]
        if row < self.document.line_count - 1 and column == len(line):
            return row + 1, 0
        index = column
        while index < len(line) and line[index].isspace():
            index += 1
        if index == len(line):
            return row, len(line)
        word = is_word(line[index])
        while index < len(line) and not line[index].isspace() and is_word(line[index]) == word:
            index += 1
        return row, index

    def get_cursor_word_left_location(self) -> Location:
        """Where ctrl+left goes: the start of the word before the cursor.

        The mirror of get_cursor_word_right_location, fixing the mirrored
        fault: TextArea stopped at `a| *strong*` rather than `a |*strong*`.

        Walked by hand rather than with a regex anchored at the end of the
        line. `search` tries every start position, which is quadratic
        inside one long run: an unbroken 40,000-character line took
        seconds per keypress.
        """
        row, column = self.cursor_location
        if row > 0 and column == 0:
            return row - 1, len(self.document[row - 1])
        line = self.document[row]
        index = column
        while index > 0 and line[index - 1].isspace():
            index -= 1
        if index == 0:
            return row, 0
        word = is_word(line[index - 1])
        while index > 0 and not line[index - 1].isspace() and is_word(line[index - 1]) == word:
            index -= 1
        return row, index
