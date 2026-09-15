"""Screen for writing one day's entry.

Opened on a date, never on an entry: a day holds at most one entry, so the
date is the whole question and the screen looks up whether that day has
been written yet.
    - Unwritten day: on save, build Entry.new(date, body), call
      app.diary.add_entry(...), then app.diary.save(app.key).
    - Written day: on save, build entry.edited(body), call
      app.diary.update_entry(...), then app.diary.save(app.key).

Every save persists immediately (writes the full diary file atomically) —
there is no separate "unsaved draft" state to manage across screens.

Saving does not leave, though. ctrl+s writes the day and hands the cursor
straight back, because an entry is written over an evening rather than in
one keystroke; escape is what leaves.

Because there is no draft state, leaving with unsaved changes would lose
them outright, so backing out of a modified entry asks first — which a
saved day no longer is, so escape after ctrl+s just goes. The question has
three answers, not two: save and go back, discard, or stay. Escape is
pressed to reach the list, and offering only to throw the last paragraph
away or to stay put made an ordinary key into a small trap. A save that
fails keeps you on the screen with your text intact, whichever key asked
for it.

Locking is the exception to that asking. ctrl+l saves the day and then
locks, rather than putting a question on the screen and leaving the diary
open behind it while it waits for an answer -- see action_save_and_lock.

Those four keys are the screen's whole keymap, and they are about the
diary rather than about the text: save it, lock it, cover it, go back.
Everything to do with the writing itself belongs to DiaryTextArea below --
including the two things drawn over the text on its way to the screen, the
mask and the colour on an *emphasised phrase*.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import ClassVar, NamedTuple

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.geometry import Region
from textual.reactive import reactive
from textual.strip import Strip
from textual.widgets import Label, TextArea
from textual.widgets.text_area import Location

from zecret.models import Entry
from zecret.screens.base import UNSAVED_CHANGES, FormScreen, format_day_long, save_error
from zecret.screens.confirm import Choice, ConfirmScreen
from zecret.screens.header import DiaryFooter, DiaryHeader
from zecret.storage import ZecretConflictError

#: The way out of the unsaved-changes question that keeps the writing.
#: Names where it puts you, because the other two answers go to the same
#: place and only this one takes the day with it.
SAVE_AND_GO_BACK = "Save and go back"
#: Shown for an empty body and for one that is only whitespace, which
#: amounts to the same thing and reads the same way in the list.
EMPTY_ENTRY = "Nothing to save — write something first."
#: Said over the day you are still writing. ctrl+s leaves the text exactly
#: where it was, so nothing on the screen changes to mark the save -- and
#: without a word for it the keypress would be indistinguishable from one
#: the app never received.
SAVED = "Saved."
#: Said after ctrl+l, because the saving is the part you would not
#: otherwise know happened -- the lock screen speaks for itself.
SAVED_AND_LOCKED = "Saved, and locked."

#: What a covered character is drawn as: three-quarters of a cell, so a
#: paragraph of them reads as separate lines of redaction rather than one
#: slab. One cell wide, which is the whole reason a glyph can be swapped
#: in at all -- see DiaryTextArea.get_line for what happens to the
#: characters that are wider than that.
BAR = "▆"

#: What a phrase is wrapped in to emphasise it: *like this*. One character
#: rather than a pair of them, because a diary is typed quickly and the
#: mark has to be cheap to reach for -- and because it is the one people
#: already make by hand in a notebook.
STRONG = "*"

#: How far ctrl+right goes: over any leading whitespace, then over one
#: whole run of same-class characters -- letters and digits, or
#: punctuation. Three classes rather than two, with whitespace its own, is
#: the point of it: it is what stops a run of punctuation from swallowing
#: the space after it and carrying the cursor into the following word.
#: See DiaryTextArea.get_cursor_word_right_location.
_WORD_RIGHT = re.compile(r"\s*(\w+|[^\w\s]+)")

#: How far ctrl+left goes, read backwards from the cursor: the last whole
#: run of same-class characters, with any whitespace after it skipped.
#: The mirror of _WORD_RIGHT and wrong in the mirrored way without the
#: third class -- see DiaryTextArea.get_cursor_word_left_location.
_WORD_LEFT = re.compile(r"(\w+|[^\w\s]+)\s*\Z")


def word_runs(line: str) -> list[tuple[int, int]]:
    """Every maximal run of non-blank characters in `line`, as [start, end).

    A "word" here is only "something with no space in it" -- no attempt is
    made to split "don't" or "well-worn", because the runs are what gets
    covered by a bar and a bar that stopped at an apostrophe would tell a
    reader where the apostrophes are. Punctuation riding on the end of a
    word is likewise left inside the bar rather than sticking out of it.

    The gaps between runs are what make masked text look like a redacted
    page rather than one long stripe: the spaces stay the colour of the
    page, so the shape of the writing survives while the words do not.
    That shape does leak the length of every word, which is the bargain
    censors have always made and is why this is a screen someone can read
    over your shoulder, not a cipher.
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
    """The run the cursor is touching, if it is touching one.

    Touching includes both ends, which is what makes this useful while
    typing: the cursor sits just past the last letter of the word being
    written, so `end` has to count as part of it. A cursor in the space
    between two words touches exactly one of them -- the one it has just
    left -- because runs are separated by at least one blank, so no two
    of them can claim the same column.
    """
    for start, end in runs:
        if start <= column <= end:
            return (start, end)
    return None


class StrongSpan(NamedTuple):
    """Where one *emphasised phrase* sits in a line, in character offsets.

    Four offsets rather than two because the marks are drawn differently
    from what they mark: `start`..`text_start` is the opening run of
    asterisks, `text_start`..`text_end` the phrase itself, and
    `text_end`..`end` the closing run.
    """

    start: int
    text_start: int
    text_end: int
    end: int


def strong_spans(line: str) -> list[StrongSpan]:
    """Every *emphasised phrase* in `line`, left to right and never nested.

    The rule is Markdown's, cut down to the part that matters here: a run
    of asterisks opens a phrase if a non-space follows it, and closes one
    if a non-space precedes it. That is what keeps a sentence trailing off
    in an asterisk out of it, while still catching the "**bold**" people
    type from habit -- a run is taken whole, so two asterisks mark a
    phrase exactly as one does.

    One thing Markdown's rule gets wrong for a diary, and this does not:
    **a phrase may not open straight after a digit.** "2 * 3" is safe
    under the flanking rule alone, but "3*4 packs and 2*6 bottles" is not
    -- there the first asterisk opens and the second closes, and a line of
    arithmetic comes out with "4 packs and 2" emphasised in the middle of
    it. CommonMark does exactly this and is right to, because it is
    marking up documents; a diary is likelier to hold multiplication than
    emphasis that begins inside a number. Only digits are excluded, not
    letters, so a script written without spaces between its words can
    still emphasise a phrase in the middle of a line.

    A run that can only open while a phrase is already open is passed
    over, and an unclosed phrase is not a phrase: the marks have to come
    in pairs or nothing is emphasised. The phrase itself is never empty,
    because runs are maximal and so two of them always have at least one
    other character between them.

    Spans never cross a line, since this is handed one line at a time --
    which is a decision as much as a consequence. A soft wrap does not
    break a phrase (the widget wraps what this has already marked up), but
    a paragraph break does, and an asterisk left open at the end of a
    paragraph would otherwise colour the rest of the day.

    Nothing here touches the document. A mispaired asterisk costs a
    phrase its colour and nothing else -- the text is filed exactly as it
    was typed, which is why the rule can afford to be this simple and why
    there is no way to escape a literal asterisk.
    """
    spans: list[StrongSpan] = []
    opened: tuple[int, int] | None = None
    length = len(line)
    index = 0
    while (start := line.find(STRONG, index)) != -1:
        # find() rather than a character at a time, because this runs on
        # every line on its way to the screen and almost every line of a
        # diary holds no asterisk at all. Skipping to the next one is a
        # C-level scan; walking there in Python costs about forty times as
        # much on a long paragraph, for the same answer.
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


class DiaryTextArea(TextArea):
    """Textual's text area with the editing keys it is missing, and a mask.

    The keys are bound on the widget rather than on the screen, which is
    what keeps them out of the help popup and the key bar: those two
    document what Zecret does with a *diary* -- save it, lock it, go back
    -- and a reader who has used any other editor already knows what
    ctrl+home does. It is the same reason the popup does not list ctrl+z,
    ctrl+k or the arrow keys, which are Textual's and equally real. The
    keys themselves are ordinary; what is not ordinary is that Textual
    leaves them out, so they are put back rather than invented.

    Three gaps get filled that way -- the two ends of the entry, the
    selecting twins of the movement keys that had none, and a paragraph at
    a time -- and one key gets corrected rather than added: ctrl+right
    stopped in a different place after punctuation than it did after a
    word. See get_cursor_word_right_location.

    Masking is the other thing here, and it is the screen's to switch on
    (ctrl+r) because it is Zecret's own idea rather than an editor's.
    Emphasis is the third, and needs no key at all: a phrase between
    asterisks is picked out in a colour of its own, and in bold, as it is
    typed.

    **The mask is drawn, never written.** It is a style laid over the text
    on its way to the screen and nothing else: the document is untouched,
    which is what keeps `body_text` honest, `modified` correct, and the
    bars out of the diary file. Masking by rewriting the text would file
    an entry full of blocks, and it is the one mistake here that cannot be
    taken back.

    It is styling rather than substitution for a second reason too. Swapping
    each character for a block would work only until someone wrote in a
    script that is two cells wide -- a block is one cell, so the line's
    width would stop matching what the widget wrapped and where it thinks
    the cursor is. Colouring the characters that are already there leaves
    every measurement alone.

    **Emphasis is drawn, never written**, for the first of those reasons
    and not the second: it only ever colours, so it is a style laid on the
    line and cannot change a measurement even in principle. The asterisks
    stay on the screen where they were typed. Hiding them would be the
    substitution the mask cannot do -- one character fewer on the line
    than in the document, and the cursor a cell out for the rest of the
    paragraph -- and it would also be a lie about what is in the file.
    """

    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "diary-text-area--mask",
        "diary-text-area--strong",
        "diary-text-area--strong-marker",
    }

    #: Whether the writing is covered. Off at the start of every session
    #: and never written down -- see ZecretApp.masked, which is where it
    #: lives between one day and the next.
    masked: reactive[bool] = reactive(False)

    BINDINGS: ClassVar[list[BindingType]] = [
        # TextArea has home and end for the line, and the page keys for a
        # screenful, but nothing for the two ends of the text itself --
        # so a day written at length had its top hundreds of presses from
        # its bottom.
        Binding("ctrl+home", "document_start", "Start of the entry", show=False),
        Binding("ctrl+end", "document_end", "End of the entry", show=False),
        # Every other way of moving in the editor has a shift twin that
        # selects on the way -- home/shift+home, ctrl+left/ctrl+shift+left
        # -- and the two keys above were the only pair without one, being
        # the only pair this widget added. Selecting to the top of a long
        # day was therefore the one selection that had to be made with the
        # mouse.
        Binding("ctrl+shift+home", "document_start(True)", "Select to the start", show=False),
        Binding("ctrl+shift+end", "document_end(True)", "Select to the end", show=False),
        # Paragraph movement. `down` moves by *wrapped* row here, because
        # soft wrap is on and a paragraph of prose is one long line in the
        # document -- so there was no key that moved a paragraph at a
        # time, which in a diary is the unit anyone actually navigates by.
        # ctrl+up/ctrl+down is where GTK and Word both put it.
        Binding("ctrl+up", "cursor_paragraph_up", "Previous paragraph", show=False),
        Binding("ctrl+down", "cursor_paragraph_down", "Next paragraph", show=False),
        Binding("ctrl+shift+up", "cursor_paragraph_up(True)", "Select a paragraph up", show=False),
        Binding(
            "ctrl+shift+down", "cursor_paragraph_down(True)", "Select a paragraph down", show=False
        ),
        # Overrides TextArea's own ctrl+a, which is readline's "start of
        # line" -- a pairing with ctrl+e that made sense when a text field
        # was one line long. Selecting the whole entry is what the chord
        # means everywhere else, and it was reachable only on f7, which
        # nobody finds. Nothing is lost: home still goes to the start of
        # the line, and is the key most people reach for anyway.
        Binding("ctrl+a", "select_all", "Select all", show=False),
    ]

    #: The width the text was last wrapped at, so a paint can tell whether
    #: what it is about to draw was wrapped for the width it is drawing
    #: into. None until the first one -- see render_lines.
    _wrapped_at: int | None = None

    def __init__(self, text: str = "", *, soft_wrap: bool = True, id: str | None = None) -> None:
        """A text area that never highlights the line the cursor is on.

        TextArea paints that band *after* get_line, over the whole line,
        and it carries a foreground as well as a background -- the same
        foreground the page already uses, so it changes nothing to look at
        and yet wipes every colour get_line laid down. Emphasis on the
        line being typed is exactly the emphasis someone is looking at, so
        the two cannot both be had. The mask already switched the band off
        for its own duration and for the same reason; this switches it off
        before there is anything to switch.

        Little is lost with it. Soft wrap makes it a band over the whole
        paragraph rather than the row the cursor is in, which says much
        less in prose than it does in code, and the cursor itself has
        never stopped saying where you are.

        Set here rather than as a reactive default because TextArea takes
        it as a constructor argument and writes it over one.

        The signature is narrowed to what Zecret actually passes rather
        than forwarded as `**kwargs`, which would have swallowed a
        misspelled `soft_warp=True` that mypy is run in strict mode to
        catch. TextArea takes a dozen more arguments and this widget has
        one construction site; a keyword it does not name is a mistake
        worth hearing about.
        """
        super().__init__(text, soft_wrap=soft_wrap, highlight_cursor_line=False, id=id)

    # --- wrapping ----------------------------------------------------------

    def render_lines(self, crop: Region) -> list[Strip]:
        """Wrap the day to the width it is about to be drawn at, if needed.

        TextArea wraps its text when it is told its size has changed, and
        it is told that by a Resize message -- which is queued, and so
        arrives after the compositor has already painted the widget at the
        new size. A day opened from the list therefore drew one frame of
        unwrapped text, each paragraph running off the right-hand edge as
        a single line, and rewrapped a frame later: a visible flinch on
        opening every long entry, which read as the text being replaced by
        different text.

        Wrapping here instead closes the gap, because this runs inside the
        paint rather than in a message after it. The Resize still arrives
        and still rewraps; this costs one extra pass over the day's lines
        when the width changes, which is work the resize was going to do
        anyway, and buys a first frame that is never wrong.

        Only the width is tracked. Everything else that changes the
        wrapping -- the indent width, the line numbers, a document swapped
        in under the widget -- goes through TextArea's own rewrap at the
        same width this recorded, so it stays true without being told.
        """
        width = self.wrap_width
        if width != self._wrapped_at:
            self._wrapped_at = width
            self.wrapped_document.wrap(width, tab_width=self.indent_width)
            self._line_cache.clear()
        return super().render_lines(crop)

    # --- emphasis ----------------------------------------------------------

    def _emphasise(self, line: Text) -> Text:
        """Colour every *emphasised phrase* in `line`, asterisks and all.

        The phrase takes the emphasis colour and the bold; the marks
        around it take the colour alone. Sharing the colour is what makes
        `*phrase*` read as one thing rather than as a word with
        punctuation stuck to it, and withholding the weight is what still
        lets the writing outrank the marks holding it up. They cannot be
        hidden altogether -- see the note on this class about what a
        character fewer would cost.

        Both attributes, never one. Bold alone is the least dependable
        thing a terminal offers: some render it as a brighter shade of the
        same ink, and some fonts have no bold face to switch to. Colour
        alone thins out at the other end -- sixteen colours, or NO_COLOR,
        where there is nothing for it to arrive as. They are independent
        parameters of one escape sequence, so neither can undo the other
        and each covers where the other gives out. *Which* colour is
        app.tcss's business and is argued out there -- it was measured
        against the prose on either side of a phrase rather than against
        the page, which is the test the obvious candidates fail.

        `line` is stylized in place: TextArea builds a fresh Text for each
        line every time it is asked, so there is nothing shared to spoil.
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
        """The line as it should be drawn -- emphasised, or covered.

        Two things are laid on the text on its way to the screen, and they
        never share a line: **the mask wins.** A phrase drawn in the
        emphasis colour over a row of bars would say where the emphasis in
        a covered day is, which is more than nothing about what it says -- and the
        mask's whole promise is that nothing reads through it. So a masked
        line is only ever masked, and the colour comes back with the words
        when it is uncovered.

        Textual's own docstring for this method offers it as the place to
        style what a TextArea renders. What comes back is a line of the
        same length, in which every covered character has been swapped for
        a bar: same number of characters, same number of cells, different
        thing to look at. Everything downstream measures the line rather
        than reading it, so the cursor lands where it should, the wrapping
        breaks where it did, and a selection covers what it says it does.

        Only characters one cell wide are swapped. A bar is one cell, and
        a two-cell character replaced by one would shorten the line, so
        the widths would stop matching what the widget wrapped and where
        it thinks the cursor is. Those keep their own character and are
        painted in ink the colour of their own background instead, which
        covers them just as well at whatever width they happen to be --
        the trick this whole method used to use, now down to the handful
        of characters that need it.

        Swapping the glyph rather than hiding it is also what makes the
        mask hold: a colour can be painted over by whatever draws next,
        and twice it was -- see watch_masked. A character that is not
        there cannot be brought back by a later coat of paint.
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
        """Cover or uncover the writing, and make the widget draw it again.

        TextArea keeps rendered lines in a cache keyed on the things it
        knows can change how a line looks -- the scroll, the selection,
        the theme. It cannot know about this one, so switching the mask
        alone would leave every line on screen exactly as it was drawn a
        moment ago. Clearing the cache is what TextArea itself does when
        the theme or the document changes underneath it.

        Two of TextArea's own styles are painted *after* get_line has had
        its say, and each would hand back what the mask had just covered:

        - The cursor line's highlight, which would put the mask's ink on a
          readable background and give away the whole line the cursor is
          on. That one is no longer switched off here because it is no
          longer switched on at all -- see highlight_cursor_line above,
          which emphasis took off permanently for the same reason the mask
          took it off for the duration.
        - The selection, which sets both colours over everything it covers
          and so read straight through the mask. ctrl+a is select-all, so
          one keystroke laid the entire entry bare while the screen was
          supposed to be covered. The `-masked` class is what lets
          app.tcss give the selection a bar of its own instead.
        """
        self._line_cache.clear()
        self.set_class(masked, "-masked")
        self.refresh()

    # --- getting around ----------------------------------------------------

    def action_document_start(self, select: bool = False) -> None:
        """ctrl+home: to the first character of the day's text.

        With `select`, on ctrl+shift+home, taking the writing in between
        with it.
        """
        self.move_cursor((0, 0), select=select)

    def action_document_end(self, select: bool = False) -> None:
        """ctrl+end: to the last character of the day's text."""
        self.move_cursor(self.document.end, select=select)

    def _written(self, row: int) -> bool:
        """Whether `row` has anything on it but whitespace."""
        return bool(self.document[row].strip())

    def action_cursor_paragraph_up(self, select: bool = False) -> None:
        """ctrl+up: to the top of this paragraph, or of the one above it.

        A paragraph is a line of the document, not a line of the screen.
        Soft wrap is on, so someone writing prose presses enter between
        paragraphs and nowhere else, and the row the cursor is drawn on is
        a fragment of a sentence rather than a unit of anything. Blank
        lines are stepped over rather than stopped on, so the key behaves
        the same for a diary written with a blank line between paragraphs
        and one written without.

        Landing at the start of the current paragraph before leaving it is
        what ctrl+left already does with a word, and is what makes the key
        useful from the middle of a long one.
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
        """ctrl+down: to the start of the next paragraph.

        Past the end of the last one it goes to the end of the day rather
        than refusing to move, so the key is never dead -- the same
        bargain MonthCalendar's cursor makes when it clamps to today.
        """
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

        End-of-word rather than start-of-next-word is deliberate and is
        the convention this widget is surrounded by -- VS Code binds the
        pair as `cursorWordEndRight` and `cursorWordStartLeft`, and GTK,
        readline's `alt+f` and Firefox on Linux all stop at the end too.
        The asymmetry with ctrl+left reads as a bug and is not one.

        What *was* a bug is what TextArea does instead of it. Its rule is
        "the next change of character class, having skipped leading
        whitespace", which lands on a word's end only because a word is
        usually followed by a space. After punctuation the first change of
        class is the space-to-letter one at the *start* of the next word,
        so the cursor overshot past the space:

            It rained. Then  ->  `It rained. |Then`, not `It rained.|`

        -- which put the landing point somewhere different after every
        full stop, and charged two presses to leave a word that ended a
        sentence. Taking the run of same-class characters whole fixes it,
        with whitespace as a class of its own so that it can end a run of
        punctuation as well as begin one.
        """
        row, column = self.cursor_location
        line = self.document[row]
        if row < self.document.line_count - 1 and column == len(line):
            return row + 1, 0
        run = _WORD_RIGHT.match(line, column)
        return row, run.end() if run else len(line)

    def get_cursor_word_left_location(self) -> Location:
        """Where ctrl+left goes: the start of the word before the cursor.

        Start-of-word is the right half of the pair -- see
        get_cursor_word_right_location for why the two are allowed to
        disagree about which end of a word they stop at, and why that is
        not the asymmetry worth fixing.

        The one that was worth fixing is here too, mirrored. TextArea
        strips *trailing* whitespace and then takes the last change of
        character class, which for a run of punctuation with a space in
        front of it falls at the start of the space rather than at the
        start of the punctuation:

            a *strong*  ->  `a| *strong*`, not `a |*strong*`

        So going left over an emphasis mark stopped a cell short of it,
        while going left over the same mark with no space in front landed
        on it -- the same key, two different places, for a difference
        nobody typing can see. Reading the run backwards with whitespace
        as a class of its own gives the mark's own start both times.
        """
        row, column = self.cursor_location
        if row > 0 and column == 0:
            return row - 1, len(self.document[row - 1])
        run = _WORD_LEFT.search(self.document[row], 0, column)
        return row, run.start(1) if run else 0


class EditorScreen(FormScreen):
    """Write or revise the entry for a single day."""

    ERROR_ID = "editor-error"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("escape", "back", "Back", priority=True),
        # Reachable here, unlike the old shift-L on the entry list, because
        # a chord means something of its own inside a text field. What it
        # does with half-written text is the question that kept locking off
        # this screen; action_save_and_lock answers it.
        Binding("ctrl+l", "save_and_lock", "Lock", priority=True),
        # Zecret's own idea rather than an editor's, so unlike ctrl+home
        # and ctrl+a it is declared here: the key bar and the help popup
        # are built from a screen's bindings, and this is a key nobody
        # arrives already knowing. The editor advertises three other keys
        # in a bar with room for eight, so it costs nothing to show.
        #
        # ctrl+r for redact. Free in every direction that matters: no
        # TextArea binding, no screen binding, and the entry list's own
        # 'r' is a bare letter, which cannot be pressed in here anyway.
        Binding("ctrl+r", "toggle_mask", "Mask", priority=True),
    ]

    def __init__(self, date: dt.date) -> None:
        """Args:
        date: The day to write about. Whether it already has an entry is
            looked up from the diary, so callers never have to decide
            between "new" and "edit".
        """
        super().__init__()
        self.date = date
        self.entry: Entry | None = None

    @property
    def creating(self) -> bool:
        return self.entry is None

    def compose(self) -> ComposeResult:
        # Resolved here rather than in __init__ because the diary is
        # reached through the running app, which a screen only has once it
        # is mounted.
        diary, _ = self.zecret.unlocked
        self.entry = diary.entry_for(self.date)

        yield DiaryHeader()
        with Vertical(id="editor-box"):
            yield DiaryTextArea(
                "" if self.entry is None else self.entry.body,
                soft_wrap=True,
                id="body",
            )
            yield Label("", id="editor-error")
        yield DiaryFooter()

    def on_mount(self) -> None:
        day = format_day_long(self.date)
        self.sub_title = f"{day} — new" if self.creating else day
        # The mask belongs to the session, not to the day: someone writing
        # in a carriage covers the screen once, not once per entry.
        self.body.masked = self.zecret.masked
        self.body.focus()

    # --- current state -----------------------------------------------------

    @property
    def body(self) -> DiaryTextArea:
        """The widget the day is written in."""
        return self.query_one("#body", DiaryTextArea)

    @property
    def body_text(self) -> str:
        return self.body.text

    @property
    def original_body(self) -> str:
        """What the day held when the screen opened -- nothing, if unwritten."""
        return "" if self.entry is None else self.entry.body

    @property
    def modified(self) -> bool:
        """Whether the text differs from what was opened."""
        return self.body_text != self.original_body

    @property
    def blocks_lock(self) -> bool:
        """Unsaved text is exactly what the idle lock must not discard.

        Backing out asks before throwing this away; a timer must not do
        silently what a keypress is made to confirm.
        """
        return self.modified

    # --- actions -----------------------------------------------------------

    def action_save(self) -> None:
        """ctrl+s: file the day and carry on writing it.

        Saving does not leave. Every editor spells "write what I have so
        far" this way, and a diary entry is written over an evening rather
        than in one keystroke -- being returned to the list for it meant
        pressing 'n' and finding your place again to add the next line, so
        the safe habit cost more than not having it.

        Leaving is escape's job, and it no longer asks anything once this
        has run: there is nothing unsaved left to discard.
        """
        if self._save():
            self.set_error("")
            self.notify(SAVED)

    def _save(self) -> bool:
        """Persist the day's text, and say whether it reached disk.

        Split out of action_save because locking needs the same work
        without the leaving: a caller that gets False back should stay
        where it is, since the error is already on the screen and the text
        is still only in the widget.
        """
        # Nothing typed since the last save, so there is nothing to write.
        # Worth the check now that ctrl+s stays here: the reflex is to
        # press it every few sentences, and each press would otherwise
        # rewrite the whole file, restamp a day nobody edited, and turn
        # another Zecret's saving into a conflict over an entry this one
        # was not changing. A day that has never been written is not
        # unmodified in this sense -- it is empty, and refused below.
        if not self.modified and self.entry is not None:
            return True

        body = self.body_text
        # Blank means blank, not just zero-length: a body of spaces and
        # newlines is what the list already renders as "(empty)", so
        # accepting it here would file a day under text nobody wrote. The
        # text is stored as typed -- only the question of whether there is
        # any is asked with the whitespace taken off.
        if not body.strip():
            self.set_error(EMPTY_ENTRY)
            return False

        diary, key = self.zecret.unlocked
        existing = self.entry
        if existing is None:
            entry = Entry.new(self.date, body)
            diary.add_entry(entry)
        else:
            entry = existing.edited(body)
            diary.update_entry(entry)

        try:
            diary.save(key)
        except (OSError, ZecretConflictError) as error:
            # Put the in-memory diary back as it was, so it still matches
            # the file and pressing save again is a clean second attempt --
            # otherwise the retry would hit "an entry already exists".
            if existing is None:
                diary.delete_entry(self.date)
            else:
                diary.update_entry(existing)
            # Stay put: popping now would throw away text that never
            # reached disk.
            self.set_error(save_error(error))
            self.notify("The entry was not saved.", severity="error")
            return False

        # Now the edit is the day's entry, so leaving is no longer "unsaved".
        self.entry = entry
        return True

    def action_toggle_mask(self) -> None:
        """ctrl+r: cover the writing, or uncover it.

        Kept on the app rather than on this screen so that going back to
        the list and opening another day does not quietly undo it. It is
        never written down: a new session starts uncovered, because a
        diary that opened unreadable would be a puzzle before it was a
        protection.
        """
        self.zecret.masked = not self.zecret.masked
        self.body.masked = self.zecret.masked

    def action_save_and_lock(self) -> None:
        """Put the day away, and the diary with it.

        Saves rather than asking. Lock is what you press on the way out of
        the room, so it must not stop to put a question on the screen and
        then leave the diary open behind it while it waits to be answered
        -- which is what backing out does, correctly, since backing out is
        not a promise about who can read this.

        Nothing typed yet means nothing to save: an untouched editor locks
        straight away rather than refusing over an empty day. A day that
        will not save -- blank, or a diary that changed underneath this one
        -- keeps you here with the reason, because a lock that quietly threw
        the text away would be the very thing this avoids.
        """
        if not self.modified:
            self.zecret.lock()
            return
        if self._save():
            self.zecret.lock(SAVED_AND_LOCKED)

    def action_back(self) -> None:
        """Leave the day -- asking first if that would throw writing away.

        The question offers to save rather than only to discard: escape is
        pressed to get back to the list, and being told the only ways to do
        that were to lose the last paragraph or to stay put made a routine
        key into a small trap.
        """
        if not self.modified:
            self.dismiss()
            return
        self.app.push_screen(
            ConfirmScreen(
                UNSAVED_CHANGES,
                confirm_label="Discard",
                save_label=SAVE_AND_GO_BACK,
            ),
            self.leave,
        )

    def leave(self, choice: Choice | None) -> None:
        """Act on the answer to the unsaved-changes question.

        Anything other than the two answers that leave -- Cancel, escape,
        a modal torn down from under it -- stays here with the text
        untouched, which is what makes the question safe to raise on a key
        as ordinary as escape.
        """
        if choice is Choice.CONFIRM:
            self.dismiss()
        elif choice is Choice.SAVE and self._save():
            # Before the dismiss and outliving it: a notification belongs
            # to the app, so this one is still there to be read over the
            # list. A save that refuses keeps you here instead, with its
            # reason already on the error line.
            self.notify(SAVED)
            self.dismiss()

    def save_pending(self) -> bool:
        """Write the day out for someone who is quitting over it.

        The editor is the one screen that ever holds something unsaved --
        see blocks_lock, which is what puts this question on the screen in
        the first place.
        """
        return self._save()
