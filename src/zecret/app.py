"""The Zecret Textual application: screen management and app-level state.

Screen flow:
    UnlockScreen -> EntryListScreen <-> EditorScreen (one day's entry)
                                     -> DatePromptScreen -> EditorScreen
                                     -> SearchScreen
                                     -> SettingsScreen (theme, password)
                                     -> HelpScreen

The unlocked DiaryFile and derived key live on the App instance for the
duration of the session and are never persisted in plaintext. Preferences
(the theme) are the one thing that outlives the session, in a separate
plaintext file -- see config.py for why they are not in the diary.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import App

from zecret.config import DEFAULT_CONFIG_PATH, DEFAULT_THEME, Config
from zecret.screens.entry_list import EntryListScreen
from zecret.screens.unlock import UnlockScreen
from zecret.storage import DEFAULT_DIARY_PATH, DiaryFile


class ZecretApp(App[None]):
    """Root Textual application for Zecret."""

    CSS_PATH = "app.tcss"
    TITLE = "Zecret"

    # No command palette. It offers a search over commands this app does
    # not have, and its one useful entry -- the theme picker -- now lives
    # on the settings screen where it can be saved. Switching it off also
    # drops the ctrl+p binding and the footer's "^p palette" entry.
    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        diary_path: Path = DEFAULT_DIARY_PATH,
        config_path: Path | None = None,
    ) -> None:
        """Store the paths; the diary itself is unlocked via UnlockScreen.

        Args:
            diary_path: Path to the encrypted diary file. Defaults to
                ~/.zecret/diary.enc, overridable via --path / ZECRET_DIARY_PATH.
            config_path: Path to the preferences file, defaulting to
                DEFAULT_CONFIG_PATH. Deliberately a separate argument
                rather than derived from diary_path: preferences belong to
                the person, not the file, so pointing --path at a scratch
                diary must not give it a theme of its own. Resolved here
                rather than as a default value so the fallback can be
                redirected in tests, which must never read or write the
                real one.
        """
        super().__init__()
        self.diary_path = diary_path
        self.config = Config.load(DEFAULT_CONFIG_PATH if config_path is None else config_path)
        # Both are None until UnlockScreen succeeds, and live only in memory
        # for the session. Screens reach the diary exclusively through these.
        self.diary: DiaryFile | None = None
        self.key: bytes | None = None

    def on_mount(self) -> None:
        """Apply the saved theme, then push UnlockScreen, which prompts to
        unlock or to create a diary depending on whether diary_path exists.

        Routing lives here rather than in the screens: UnlockScreen reports
        success by dismissing, and this decides what comes next.
        """
        self.apply_theme(self.config.theme)
        creating = not self.diary_path.exists()
        self.push_screen(UnlockScreen(creating=creating), self._on_unlocked)

    def apply_theme(self, theme: str) -> None:
        """Switch to `theme`, or to the default if it is not a real theme.

        Config holds whatever string was in the file, which may name a
        theme this Textual no longer ships; setting it directly would raise
        and take the app down over a preference.
        """
        self.theme = theme if theme in self.available_themes else DEFAULT_THEME

    def _on_unlocked(self, _result: None) -> None:
        """Called once UnlockScreen dismisses, i.e. the diary is open."""
        self.push_screen(EntryListScreen())

    @property
    def unlocked(self) -> tuple[DiaryFile, bytes]:
        """The open diary and the key it was opened with.

        Every screen after UnlockScreen needs both, and needs them non-None.
        Reaching here before unlocking is a routing bug, not a user error,
        so it raises rather than returning a half-open state.

        Raises:
            RuntimeError: if the diary has not been unlocked yet.
        """
        if self.diary is None or self.key is None:
            raise RuntimeError("the diary is not unlocked")
        return self.diary, self.key
