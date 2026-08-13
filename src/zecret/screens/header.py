"""The title bar every screen wears.

Textual's own Header is deliberately not used. It docks an icon that opens
the command palette, and clicking anywhere on it toggles a taller variant --
two behaviours this app does not want and cannot switch off, only style
around. Zecret's chrome does one thing: say what this is and where you are.

So this is a plain Static that renders the same title text (deferring to
App.format_title, so the "Zecret — Search" styling matches what Textual
would produce) and watches the same four reactives Textual's header does:
screen title and sub-title, falling back to the app's.
"""

from __future__ import annotations

from textual.widgets import Static


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
