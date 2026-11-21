"""The bars every screen wears: the title above, the keys below.

Textual's Header is not used: it docks an icon that opens the command
palette and expands when clicked, and neither can be switched off.
DiaryHeader is a plain Static showing the same title text, through
App.format_title, and watching the same four reactives.

DiaryFooter is Textual's Footer in its compact form, defined once so every
screen's bar agrees. Every screen composes one, modals included: a
ModalScreen renders over the screen beneath, so one without a footer shows
that screen's bar, with every key on it dead.

Compact because the entry list's eight advertised keys must fit 80 columns.
"""

from __future__ import annotations

from typing import Any

from textual.widgets import Footer, Static


class DiaryHeader(Static):
    """One line: the app name, then the screen's sub-title. Not clickable."""

    def on_mount(self) -> None:
        self.show_title()
        # A screen sets its sub_title in its own on_mount, which may run
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
    """The key bar, compact so the entry list's keys fit 80 columns."""

    def __init__(self, **kwargs: Any) -> None:
        # Passed to __init__, not set as a class attribute: `compact` is a
        # reactive, and assigning over it in a subclass replaces the
        # descriptor rather than its default.
        kwargs.setdefault("compact", True)
        super().__init__(**kwargs)
