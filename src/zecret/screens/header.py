"""The bars every screen wears: the title above, the keys below.

Textual's own Header is deliberately not used. It docks an icon that opens
the command palette, and clicking anywhere on it toggles a taller variant --
two behaviours this app does not want and cannot switch off, only style
around. Zecret's chrome does one thing: say what this is and where you are.

So DiaryHeader is a plain Static that renders the same title text (deferring
to App.format_title, so the "Zecret — Search" styling matches what Textual
would produce) and watches the same four reactives Textual's header does:
screen title and sub-title, falling back to the app's.

DiaryFooter is Textual's Footer in its compact spelling, which is one place
rather than seven so the bar cannot end up looking different depending on
which screen you are on. Every screen composes one, the two modals
included: a ModalScreen renders over the screen it was opened from rather
than replacing it, so one without a footer shows the bar underneath -- whose
keys are all dead while the modal has focus.

Compact because the entry list advertises eight keys and the roomy spelling
needs far more than a terminal's eighty columns to lay them out; at eighty
it stopped mid-word at "? Hel". Compact, those eight come to seventy-two,
so this is the setting that gives way if the app ever grows another key --
see the note in CLAUDE.md.
"""

from __future__ import annotations

from typing import Any

from textual.widgets import Footer, Static


class DiaryHeader(Static):
    """One line: the app name, then the screen's sub-title. Not clickable."""

    def on_mount(self) -> None:
        self.show_title()
        # A screen sets its sub_title in its own on_mount, which may land
        # after this one, so watch rather than render once.
        for node, attribute in (
            (self.app, "title"),
            (self.app, "sub_title"),
            (self.screen, "title"),
            (self.screen, "sub_title"),
        ):
            self.watch(node, attribute, self.show_title)

    def show_title(self) -> None:
        """Render "<title> — <sub-title>", the screen's if it set one."""
        screen_title = self.screen.title
        screen_sub_title = self.screen.sub_title
        self.update(
            self.app.format_title(
                self.app.title if screen_title is None else screen_title,
                self.app.sub_title if screen_sub_title is None else screen_sub_title,
            )
        )


class DiaryFooter(Footer):
    """The key bar, compact so the entry list's keys fit an 80-column terminal.

    A subclass rather than `Footer(compact=True)` written out on every
    screen: the five of them must agree, and one of them quietly not
    agreeing is exactly the kind of thing nobody notices.
    """

    def __init__(self, **kwargs: Any) -> None:
        # Passed to __init__ rather than set as a class attribute, since
        # `compact` is a Textual reactive and assigning a plain value over
        # it in a subclass replaces the descriptor instead of the default.
        kwargs.setdefault("compact", True)
        super().__init__(**kwargs)
