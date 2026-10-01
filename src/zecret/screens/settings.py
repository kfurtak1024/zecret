"""Settings screen: appearance, locking, and the way to the password dialog.

Appearance is a theme picker over a curated set of Textual's themes. It
applies as the selection moves, so you see the diary in it rather than a
swatch, and saves immediately -- there is no "apply" button to forget. The
list is curated rather than Textual's full set: each name here has been
rendered against this app's own styling and checked that the month
headings, the highlighted row and the footer all stay legible. Saving is
best effort; a preferences file that cannot be written costs you the
setting next launch, never the session you are in.

Changing the master password is a button here and a dialog of its own
(screens/password.py). It is the only thing on this screen that cannot be
undone, and it was three password fields under two dropdowns: something to
scroll past, or to tab into by accident, with its warning read as the
small print at the foot of a form. Moving it out also leaves what remains
short enough to stop scrolling on an ordinary terminal, so the two
settings people come here to change are the whole screen.

Everything else here applies as you choose it and saves immediately --
there is no "apply" button to forget, and the button below is not one: it
opens a question rather than committing an answer.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import Button, Label, Select

from zecret.screens.base import ZecretScreen, card
from zecret.screens.header import DiaryFooter, DiaryHeader
from zecret.screens.password import PasswordScreen

#: How long the diary may sit untouched, as (what the user reads, minutes).
#: Zero never locks, which is offered rather than hidden -- someone writing
#: on a machine only they can reach should be able to say so.
LOCK_TIMEOUTS: list[tuple[str, int]] = [
    ("After 1 minute", 1),
    ("After 5 minutes", 5),
    ("After 15 minutes", 15),
    ("After 30 minutes", 30),
    ("After 1 hour", 60),
    ("Never", 0),
]

THEME_NOT_SAVED = "Theme applied, but could not be saved for next time."
LOCK_NOT_SAVED = "Lock timing applied, but could not be saved for next time."

#: The themes offered, as (what the user reads, what Textual calls it).
#: A shortlist, not all 21 Textual ships: the ansi ones borrow the
#: terminal's own palette and render this app's accents unpredictably, and
#: a dropdown is a worse place to browse than a diary is to read.
THEMES: list[tuple[str, str]] = [
    ("Dark", "textual-dark"),
    ("Light", "textual-light"),
    ("Nord", "nord"),
    ("Gruvbox", "gruvbox"),
    ("Dracula", "dracula"),
    ("Catppuccin Mocha", "catppuccin-mocha"),
    ("Catppuccin Latte", "catppuccin-latte"),
    ("Solarized Light", "solarized-light"),
]


def theme_options(current: str) -> list[tuple[str, str]]:
    """The curated themes, plus the one in use if it is not among them.

    The theme in use can be any Textual ships -- config.json is a file
    anyone can edit, and a later build may curate a shorter list than the
    one that saved it -- and Select raises on a value that is none of its
    options, which took the app down the moment Settings opened. Offering
    it under its own name shows the truth instead: that is the theme you
    are looking at, and choosing another is one move away. It has not
    been checked against this app's styling, which is why it is not simply
    added to THEMES.
    """
    if any(theme == current for _, theme in THEMES):
        return THEMES
    return [*THEMES, (current, current)]


def lock_after_options(current: int) -> list[tuple[str, int]]:
    """The offered waits, plus the saved one if it is not among them.

    For the same reason as theme_options, and with more at stake. This
    used to start the dropdown on the default instead, and Select reports
    its opening value as a change -- so merely opening Settings replaced a
    hand-set wait with fifteen minutes, on disk. A diary set to lock after
    two minutes would quietly start taking fifteen, which is the one
    direction this setting must never drift in unasked.

    Slotted in by length, ahead of "Never", so the list still reads from
    soonest to not at all.
    """
    if any(minutes == current for _, minutes in LOCK_TIMEOUTS):
        return LOCK_TIMEOUTS
    label = "After 1 minute" if current == 1 else f"After {current} minutes"
    timed = [option for option in LOCK_TIMEOUTS if option[1] > 0]
    never = [option for option in LOCK_TIMEOUTS if option[1] == 0]
    return sorted([*timed, (label, current)], key=lambda option: option[1]) + never


class SettingsScreen(ZecretScreen):
    """Pick a theme, choose when the diary locks, and reach the password
    dialog.

    Not a FormScreen any more: nothing here is typed into and nothing here
    can fail in a way that needs a line to explain it. The two dropdowns
    apply as they are chosen, and a preference that cannot be written to
    disk is said in a notification, since it costs the setting next launch
    rather than this screen.
    """

    SUB_TITLE = "Settings"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", priority=True),
    ]

    def compose(self) -> ComposeResult:
        yield DiaryHeader()
        # Scrolls. Moving the password fields into a dialog took this
        # card from wanting thirty-nine rows to twenty-six, which is the
        # difference between needing a tall terminal and needing an
        # ordinary one -- but twenty-four rows leave eighteen inside the
        # frame, so it is still a scroll and not a screenful.
        with card("settings-box"):
            yield Label("Appearance", classes="section-title")
            yield Label(
                "Applied as you choose it, and kept for next time.",
                classes="section-hint",
            )
            yield Select(
                theme_options(self.zecret.theme),
                value=self.zecret.theme,
                allow_blank=False,
                id="theme",
            )

            yield Label("Locking", classes="section-title")
            yield Label(
                "Zecret puts the diary away when you stop typing, and asks "
                "for your password again.",
                classes="section-hint",
            )
            yield Select(
                lock_after_options(self.zecret.config.lock_after_minutes),
                value=self.zecret.config.lock_after_minutes,
                allow_blank=False,
                id="lock-after",
            )

            yield Label("Master password", classes="section-title")
            yield Label(
                "The password that opens this diary. Changing it "
                "re-encrypts every entry under the new one.",
                classes="section-hint",
            )
            # Red, like the answer it leads to. Everything else on this
            # screen is a preference that applies as you choose it and can
            # be chosen again; this is the one control that opens something
            # there is no way back from.
            yield Button("Change master password…", variant="error", id="change-password")
        yield DiaryFooter()

    def on_mount(self) -> None:
        # The top of the form, not the password fields at the bottom of it.
        # This screen scrolls, and focusing the last section would open it
        # already scrolled past the two settings most people came to
        # change. Arrow keys on a closed dropdown open it rather than
        # moving the selection, so landing here changes nothing by itself.
        self.query_one("#theme", Select).focus()

    # --- appearance --------------------------------------------------------

    def on_select_changed(self, event: Select.Changed) -> None:
        """Route a dropdown's new value to whichever setting it belongs to."""
        if event.select.id == "theme":
            self.choose_theme(event.value)
        else:
            self.choose_lock_after(event.value)

    def choose_theme(self, theme: object) -> None:
        """Apply the chosen theme and remember it."""
        # Select is typed as possibly blank; this one is allow_blank=False,
        # so anything else is not a theme name and there is nothing to do.
        if not isinstance(theme, str) or theme == self.zecret.theme:
            return

        self.zecret.apply_theme(theme)
        self.zecret.config.theme = theme
        self.remember(THEME_NOT_SAVED)

    def choose_lock_after(self, minutes: object) -> None:
        """Remember how long the diary may sit idle before locking itself.

        Nothing is restarted: the idle check reads the setting each time it
        runs, so a longer wait takes effect on the next tick and a shorter
        one applies to the quiet that has already passed.
        """
        if not isinstance(minutes, int) or minutes == self.zecret.config.lock_after_minutes:
            return

        self.zecret.config.lock_after_minutes = minutes
        self.remember(LOCK_NOT_SAVED)

    def remember(self, complaint: str) -> None:
        """Persist the preferences, saying so only if it did not work.

        Best effort by design: a preferences file that cannot be written
        costs the setting next launch, never the session you are in.
        """
        try:
            self.zecret.config.save()
        except OSError:
            self.notify(complaint, severity="warning")

    # --- the master password ------------------------------------------------

    def on_button_pressed(self, _event: Button.Pressed) -> None:
        """The one button here opens the dialog that does the work."""
        self.app.push_screen(PasswordScreen())

    def action_back(self) -> None:
        # This screen's escape binding is priority, so it would otherwise
        # win over the dropdown's own -- closing the whole screen when the
        # user meant to close the list they just opened.
        theme = self.query_one("#theme", Select)
        if theme.expanded:
            theme.expanded = False
            return
        self.dismiss()
