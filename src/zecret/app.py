"""The Zecret Textual application: screen management and app-level state.

Screen flow:
    UnlockScreen -> EntryListScreen <-> EditorScreen (one day's entry)
                                     -> DatePromptScreen -> EditorScreen
                                     -> SearchScreen
                                     -> SettingsScreen (theme, password)
                                     -> HelpScreen

The unlocked DiaryFile and derived key live on the App instance for the
duration of the session and are never persisted in plaintext. Preferences
(the theme, and how long the diary may sit idle) are the one thing that
outlives the session, in a separate plaintext file -- see config.py for why
they are not in the diary.

They do not live there indefinitely, though. A diary left open is a diary
anyone at that terminal can read, so this module watches for a spell of
quiet and puts it away again: lock() forgets both, tears the screens down
and goes back to UnlockScreen. Everything to do with that is here rather
than in a screen, for the same reason routing is -- it is about the session
as a whole, not about anything on show.

Quitting is guarded from here for the same reason. It is the other way a
screen full of unsaved writing can vanish, and it arrives by two keys, so
the question about throwing that writing away is asked once in action_quit
rather than once per binding.
"""

from __future__ import annotations

import time
from pathlib import Path

from textual import events
from textual.app import App

from zecret.config import DEFAULT_CONFIG_PATH, DEFAULT_THEME, Config
from zecret.screens.base import ZecretScreen
from zecret.screens.confirm import ConfirmScreen
from zecret.screens.entry_list import EntryListScreen
from zecret.screens.unlock import UnlockScreen
from zecret.storage import DEFAULT_DIARY_PATH, DiaryFile

#: Said when the diary locks itself, so a screen that suddenly wants a
#: password is not a mystery.
LOCKED_BY_TIMEOUT = "Locked after a spell of quiet."
LOCKED_BY_HAND = "Locked."

#: Asked before a quit that would throw away what is on the screen. Worded
#: like the editor's own discard question because it is the same question,
#: reached by a different key.
QUIT_QUESTION = "Discard your unsaved changes and quit?"


class ZecretApp(App[None]):
    """Root Textual application for Zecret."""

    CSS_PATH = "app.tcss"
    TITLE = "Zecret"

    # No command palette. It offers a search over commands this app does
    # not have, and its one useful entry -- the theme picker -- now lives
    # on the settings screen where it can be saved. Switching it off also
    # drops the ctrl+p binding and the footer's "^p palette" entry.
    ENABLE_COMMAND_PALETTE = False

    #: How often to ask whether the diary has been left alone long enough
    #: to lock. Coarse on purpose: the check costs a subtraction, and
    #: locking within half a minute of the deadline is close enough for a
    #: timeout measured in minutes. Tests turn it right down.
    IDLE_CHECK_SECONDS = 30.0

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
        # When something last happened. Monotonic, so the diary does not
        # stay open an hour longer because a clock went backwards.
        self.last_activity = time.monotonic()

    def on_mount(self) -> None:
        """Apply the saved theme, then push UnlockScreen, which prompts to
        unlock or to create a diary depending on whether diary_path exists.

        Routing lives here rather than in the screens: UnlockScreen reports
        success by dismissing, and this decides what comes next.
        """
        self.apply_theme(self.config.theme)
        creating = not self.diary_path.exists()
        self.push_screen(UnlockScreen(creating=creating), self._on_unlocked)
        self.set_interval(self.IDLE_CHECK_SECONDS, self.lock_if_idle)

    async def on_event(self, event: events.Event) -> None:
        """Every event the app sees, which is where activity is noticed.

        Key events reach here even when a widget goes on to consume them --
        typing into the editor's TextArea counts, and has to, or writing a
        long entry would be the one thing that looks like being away.
        """
        if isinstance(event, events.Key | events.MouseDown):
            self.last_activity = time.monotonic()
        await super().on_event(event)

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

    async def action_quit(self) -> None:
        """Quit -- but never silently over something half-written.

        Both spellings dispatch this one action: 'q' on the entry list, and
        ctrl+q, which Textual binds app-wide with priority so that a screen
        made of text fields still has a way out. They are two keys because
        a bare 'q' cannot be bound where there is something to type into,
        not because they are two behaviours, so the question is asked once
        here rather than per binding.

        Textual's own action_quit exits immediately. That is the right
        thing everywhere except over an editor holding unsaved text, which
        would lose it -- without the prompt that backing out of that very
        screen gives, and without even appearing in the key bar to warn
        that it might. The test is the one the idle lock already uses: what
        must not be locked away unasked must not be quit away unasked.
        """
        if not self.locking_would_lose_work():
            self.exit()
            return
        # A question is already on the screen -- the editor's own discard
        # prompt, most likely, since that is what ctrl+q interrupts. Asking
        # the same thing again on top of it buries the first copy under a
        # second, so let the one already showing be answered.
        if isinstance(self.screen, ConfirmScreen):
            return
        self.push_screen(ConfirmScreen(QUIT_QUESTION, confirm_label="Quit"), self._quit_confirmed)

    def _quit_confirmed(self, confirmed: bool | None) -> None:
        """Leave on yes; on no, stay exactly where the question was asked."""
        if confirmed:
            self.exit()

    def lock_if_idle(self) -> None:
        """Lock the diary if it has been left alone long enough.

        Runs on a timer whether or not anything is unlocked, since the
        setting can be changed mid-session and the lock screen itself has
        nothing to lock.

        Not named check_idle: Textual's MessagePump already has one, it
        means "the message queue has drained" rather than "nobody is
        there", and it is called from refresh() -- so taking that name
        replaces a framework method with one that wants attributes the app
        has not set yet, and every test dies in App.__init__.
        """
        minutes = self.config.lock_after_minutes
        if minutes <= 0 or not self.is_unlocked:
            return
        if self.locking_would_lose_work():
            # Half-written entry on the screen. Treat waiting on the writer
            # as activity rather than merely postponing: locking the moment
            # they saved would be the same ambush a beat later.
            self.last_activity = time.monotonic()
            return
        if time.monotonic() - self.last_activity >= minutes * 60:
            self.lock(LOCKED_BY_TIMEOUT)

    def locking_would_lose_work(self) -> bool:
        """Whether any screen on the stack is holding something unsaved.

        The whole stack, not just the top one: a confirmation modal over a
        half-written entry is still a half-written entry.
        """
        return any(
            isinstance(screen, ZecretScreen) and screen.blocks_lock for screen in self.screen_stack
        )

    def lock(self, message: str = LOCKED_BY_HAND) -> None:
        """Forget the diary and the key, and go back to the lock screen.

        Everything above the lock screen is torn down first, while the
        diary is still open: screens rebuild themselves as they resume, and
        one resuming into a locked app has nothing to draw from.
        """
        if not self.is_unlocked:
            return
        while len(self.screen_stack) > 1:
            self.pop_screen()
        self.diary = None
        self.key = None
        self.push_screen(UnlockScreen(creating=False), self._on_unlocked)
        self.notify(message)

    @property
    def is_unlocked(self) -> bool:
        """Whether there is an open diary to be working in."""
        return self.diary is not None and self.key is not None

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
