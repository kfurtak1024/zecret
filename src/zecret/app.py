"""The Zecret Textual application: screen management and app-level state.

Screen flow:
    UnlockScreen -> EntryListScreen <-> EditorScreen
                                     -> SearchScreen
                                     -> SettingsScreen (change password)

The unlocked DiaryFile and derived key live on the App instance for the
duration of the session and are never persisted in plaintext.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import App

from zecret.screens.entry_list import EntryListScreen
from zecret.screens.unlock import UnlockScreen
from zecret.storage import DEFAULT_DIARY_PATH, DiaryFile


class ZecretApp(App[None]):
    """Root Textual application for Zecret."""

    CSS_PATH = "app.tcss"
    TITLE = "Zecret"

    def __init__(self, diary_path: Path = DEFAULT_DIARY_PATH) -> None:
        """Store the diary path; the diary itself is unlocked via UnlockScreen.

        Args:
            diary_path: Path to the encrypted diary file. Defaults to
                ~/.zecret/diary.enc, overridable via --path / ZECRET_DIARY_PATH.
        """
        super().__init__()
        self.diary_path = diary_path
        # Both are None until UnlockScreen succeeds, and live only in memory
        # for the session. Screens reach the diary exclusively through these.
        self.diary: DiaryFile | None = None
        self.key: bytes | None = None

    def on_mount(self) -> None:
        """Push UnlockScreen, which prompts to unlock or to create a diary
        depending on whether diary_path exists.

        Routing lives here rather than in the screens: UnlockScreen reports
        success by dismissing, and this decides what comes next.
        """
        creating = not self.diary_path.exists()
        self.push_screen(UnlockScreen(creating=creating), self._on_unlocked)

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
