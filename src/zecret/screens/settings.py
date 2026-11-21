"""Settings screen: appearance, locking, and the way to the password dialog.

The theme and the idle-lock wait apply as they are chosen and save
immediately; there is no "apply" button. Saving is best effort: a
preferences file that cannot be written costs the setting next launch,
never the session.

The themes are a curated subset of Textual's, each checked against this
app's styling.

Changing the master password is a button that opens its own dialog
(screens/password.py), since it is the one thing here that cannot be
undone.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import Button, Label, Select

from zecret.screens.base import ZecretScreen, card
from zecret.screens.header import DiaryFooter, DiaryHeader
from zecret.screens.password import PasswordScreen

#: How long the diary may sit untouched, as (label, minutes). Zero never
#: locks.
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

#: The themes offered, as (label, Textual's name). A shortlist: the ansi
#: themes borrow the terminal's palette and render this app's accents
#: unpredictably.
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

    config.json can name any theme Textual ships, and Select raises on a
    value that is none of its options. An uncurated theme is offered under
    its own name rather than added to THEMES.
    """
    if any(theme == current for _, theme in THEMES):
        return THEMES
    return [*THEMES, (current, current)]


def lock_after_options(current: int) -> list[tuple[str, int]]:
    """The offered waits, plus the saved one if it is not among them.

    Select reports its opening value as a change. Starting on the default
    instead of the saved value would therefore overwrite a hand-set wait
    on disk just by opening Settings.

    The extra option is slotted in by length, ahead of "Never".
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

    Not a FormScreen: nothing here is typed, and a preference that cannot
    be saved is said in a notification.
    """

    SUB_TITLE = "Settings"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", priority=True),
        Binding("ctrl+l", "app.lock", "Lock", priority=True),
    ]

    def compose(self) -> ComposeResult:
        yield DiaryHeader()
        # Scrolls on a 24-row terminal: the card wants more rows than the
        # eighteen that leaves inside the frame.
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
            # The error variant: the one control here that leads to
            # something with no way back.
            yield Button("Change master password…", variant="error", id="change-password")
        yield DiaryFooter()

    def on_mount(self) -> None:
        # The top of the form, so it does not open scrolled. Arrow keys on
        # a closed dropdown open it rather than change it.
        self.query_one("#theme", Select).focus()

    # --- appearance --------------------------------------------------------

    def on_select_changed(self, event: Select.Changed) -> None:
        """Route a dropdown's new value to the setting it belongs to."""
        if event.select.id == "theme":
            self.choose_theme(event.value)
        else:
            self.choose_lock_after(event.value)

    def choose_theme(self, theme: object) -> None:
        """Apply the chosen theme and remember it."""
        # Select is typed as possibly blank, hence the isinstance.
        if not isinstance(theme, str) or theme == self.zecret.theme:
            return

        self.zecret.apply_theme(theme)
        self.zecret.config.theme = theme
        self.remember(THEME_NOT_SAVED)

    def choose_lock_after(self, minutes: object) -> None:
        """Remember how long the diary may sit idle before locking.

        Nothing is restarted: the idle check reads the setting each time
        it runs.
        """
        if not isinstance(minutes, int) or minutes == self.zecret.config.lock_after_minutes:
            return

        self.zecret.config.lock_after_minutes = minutes
        self.remember(LOCK_NOT_SAVED)

    def remember(self, complaint: str) -> None:
        """Persist the preferences, saying so only if it did not work."""
        try:
            self.zecret.config.save()
        except OSError:
            self.notify(complaint, severity="warning")

    # --- the master password ------------------------------------------------

    def on_button_pressed(self, _event: Button.Pressed) -> None:
        """The one button here opens the password dialog."""
        self.app.push_screen(PasswordScreen())

    def action_back(self) -> None:
        # This screen's escape is priority and would win over a dropdown's
        # own, so an open dropdown is closed first.
        for select in self.query(Select):
            if select.expanded:
                select.expanded = False
                return
        self.dismiss()
