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
Everything to do with the writing itself belongs to DiaryTextArea below.
"""

from __future__ import annotations

import datetime as dt
from typing import ClassVar

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

    Masking is the other thing here, and it is the screen's to switch on
    (ctrl+r) because it is Zecret's own idea rather than an editor's.

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
    """

    COMPONENT_CLASSES: ClassVar[set[str]] = {"diary-text-area--mask"}

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

    # --- the mask ----------------------------------------------------------

    def get_line(self, line_index: int) -> Text:
        """The line as it should be drawn -- covered, where it is masked.

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
            return line

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
          on. Masking turns it off, which is also how it should look -- a
          row of bars needs no band behind it to say where the cursor is.
        - The selection, which sets both colours over everything it covers
          and so read straight through the mask. ctrl+a is select-all, so
          one keystroke laid the entire entry bare while the screen was
          supposed to be covered. The `-masked` class is what lets
          app.tcss give the selection a bar of its own instead.
        """
        self._line_cache.clear()
        self.highlight_cursor_line = not masked
        self.set_class(masked, "-masked")
        self.refresh()

    # --- getting around ----------------------------------------------------

    def action_document_start(self) -> None:
        """ctrl+home: to the first character of the day's text."""
        self.move_cursor((0, 0))

    def action_document_end(self) -> None:
        """ctrl+end: to the last character of the day's text."""
        self.move_cursor(self.document.end)


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
