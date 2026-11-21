"""The Zecret Textual application: screen routing and session state.

Screen flow:
    UnlockScreen -> EntryListScreen <-> EditorScreen (one day's entry)
                                     <-> CalendarScreen -> EditorScreen
                                     -> DatePromptScreen -> EditorScreen
                                     -> SearchScreen
                                     -> SettingsScreen (theme, password)
                                     -> HelpScreen

The unlocked DiaryFile and the derived key live on the App for the session
and are never persisted. Preferences are the one thing that outlives it;
see config.py.

Three things about the session as a whole are decided here rather than in
a screen: the idle lock (lock_if_idle, on two clocks; see Instant), locking
by hand (action_lock), and the guarded quit (action_quit), which asks
before leaving over unsaved writing and offers to save it.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from pathlib import Path
from typing import Literal, NamedTuple, Self, overload

import rich
from rich.traceback import Traceback
from textual import events
from textual.app import App
from textual.await_complete import AwaitComplete
from textual.screen import Screen, ScreenResultCallbackType, ScreenResultType
from textual.widget import AwaitMount

from zecret.config import DEFAULT_CONFIG_PATH, DEFAULT_THEME, Config
from zecret.screens.base import UNSAVED_CHANGES, ZecretScreen
from zecret.screens.confirm import Choice, ConfirmScreen
from zecret.screens.editor import SAVED_AND_LOCKED
from zecret.screens.entry_list import EntryListScreen
from zecret.screens.help import HelpScreen
from zecret.screens.unlock import UnlockScreen
from zecret.storage import DEFAULT_DIARY_PATH, DiaryFile


class Instant(NamedTuple):
    """A moment, read off both clocks that can measure it.

    Neither clock alone can say how long someone has been away, and they
    fail in opposite directions. `time.monotonic()` does not advance while
    the machine is suspended. The wall clock does, but can be set
    backwards.

    elapsed() takes whichever reports the longer wait, which is fail-closed
    both ways: staying unlocked needs both clocks to agree that little
    time has passed.
    """

    monotonic: float
    wall: float

    @classmethod
    def now(cls) -> Self:
        """Both clocks, read as close together as Python allows."""
        return cls(time.monotonic(), time.time())

    def elapsed(self) -> float:
        """Seconds since this instant, by whichever clock says more."""
        now = Instant.now()
        return max(now.monotonic - self.monotonic, now.wall - self.wall)


#: What counts as someone being at the diary: a key, a click, or the wheel.
#: Mouse movement does not; a mouse nudged on a desk is not a reader.
ACTIVITY = (
    events.Key,
    events.MouseDown,
    events.MouseScrollUp,
    events.MouseScrollDown,
    events.MouseScrollLeft,
    events.MouseScrollRight,
)

LOCKED_BY_TIMEOUT = "Locked after a spell of quiet."
LOCKED_BY_HAND = "Locked."

#: Said when ctrl+l or ctrl+q lands while the password is being changed,
#: which both wait for.
LOCK_WHEN_DONE = "Locking once the new password is saved."
QUIT_WHEN_DONE = "Quitting once the new password is saved."

#: The answer to the unsaved-changes question that quits without losing
#: anything.
SAVE_AND_QUIT = "Save and quit"


class ZecretApp(App[None]):
    """Root Textual application for Zecret."""

    CSS_PATH = "app.tcss"
    TITLE = "Zecret"

    # Off: it searches commands this app does not have. This also removes
    # the ctrl+p binding and the footer's palette entry.
    ENABLE_COMMAND_PALETTE = False

    #: How often the idle check runs. Coarse on purpose: the timeout is in
    #: minutes, and activity is also checked as it arrives (see on_event).
    IDLE_CHECK_SECONDS = 30.0

    def __init__(
        self,
        diary_path: Path = DEFAULT_DIARY_PATH,
        config_path: Path | None = None,
    ) -> None:
        """Store the paths; the diary itself is unlocked via UnlockScreen.

        Args:
            diary_path: Path to the encrypted diary file.
            config_path: Path to the preferences file, or None for
                DEFAULT_CONFIG_PATH. Resolved here rather than as a default
                value so tests can redirect the fallback. Separate from
                diary_path: preferences belong to the person, not the file.
        """
        super().__init__()
        self.diary_path = diary_path
        self.config = Config.load(DEFAULT_CONFIG_PATH if config_path is None else config_path)
        # Both None until UnlockScreen succeeds. Screens reach the diary
        # only through these.
        self.diary: DiaryFile | None = None
        self.key: bytes | None = None
        self.last_activity = Instant.now()
        # Whether the editor covers its text. Session state, deliberately
        # not in config.py: it survives opening another day, and a new
        # session starts uncovered.
        self.masked = False
        # A ctrl+l or ctrl+q that arrived while a screen was working, and
        # is waiting for it to finish.
        self.lock_pending = False
        self.quit_pending = False
        # When a screen was last popped; see pop_screen.
        self.last_pop: float | None = None

    def on_mount(self) -> None:
        """Apply the saved theme and push UnlockScreen, in whichever flow
        fits whether diary_path exists. UnlockScreen reports success by
        dismissing; routing from there is _on_unlocked."""
        self.apply_theme(self.config.theme)
        creating = not self.diary_path.exists()
        self.push_screen(UnlockScreen(creating=creating), self._on_unlocked)
        self.set_interval(self.IDLE_CHECK_SECONDS, self.lock_if_idle)

    async def on_event(self, event: events.Event) -> None:
        """Every event the app sees, which is where activity is noticed.

        Key events reach here even when a widget goes on to consume them,
        so typing in the editor counts.
        """
        if isinstance(event, ACTIVITY):
            # Checked before the stamp, not only on the timer. The timer
            # sleeps on the monotonic clock, which stands still through a
            # suspend, so the first key after a night asleep arrives before
            # the tick. Stamping it would count whoever opened the lid as
            # the writer who never left. The event that finds the diary
            # overdue locks it and is not delivered.
            was_unlocked = self.is_unlocked
            self.lock_if_idle()
            if was_unlocked and not self.is_unlocked:
                return
            self.last_activity = Instant.now()
        await super().on_event(event)

    def apply_theme(self, theme: str) -> None:
        """Switch to `theme`, or to the default if Textual does not know it.

        The name comes from a file anyone can edit, and setting an unknown
        theme raises.
        """
        self.theme = theme if theme in self.available_themes else DEFAULT_THEME

    # Mirrors App's overloads on wait_for_dismiss, so callers keep the
    # return type that goes with the flag.
    @overload
    def push_screen(
        self,
        screen: Screen[ScreenResultType] | str,
        callback: ScreenResultCallbackType[ScreenResultType] | None = None,
        wait_for_dismiss: Literal[False] = False,
        *,
        mode: str | None = None,
    ) -> AwaitMount: ...

    @overload
    def push_screen(
        self,
        screen: Screen[ScreenResultType] | str,
        callback: ScreenResultCallbackType[ScreenResultType] | None = None,
        wait_for_dismiss: Literal[True] = True,
        *,
        mode: str | None = None,
    ) -> asyncio.Future[ScreenResultType]: ...

    def push_screen(
        self,
        screen: Screen[ScreenResultType] | str,
        callback: ScreenResultCallbackType[ScreenResultType] | None = None,
        wait_for_dismiss: bool = False,
        *,
        mode: str | None = None,
    ) -> AwaitMount | asyncio.Future[ScreenResultType]:
        """Push a screen, and drop whatever was still being said.

        Textual keeps a notification for its timeout and redraws it on
        whichever screen is current. Pushing starts something new, so what
        was said about the last thing is finished. Popping does not clear:
        that is how "Saved." reaches the list the editor returns to.
        """
        self.clear_notifications()
        # Split so the flag reaches the base as the literal its overloads
        # are keyed on. Textual raises NoActiveWorker if the True form is
        # awaited outside a worker, and Zecret runs none, so that arm is
        # unreachable here and excluded from coverage.
        if wait_for_dismiss:  # pragma: no cover
            return super().push_screen(screen, callback, True, mode=mode)
        return super().push_screen(screen, callback, False, mode=mode)

    def pop_screen(self) -> AwaitComplete:
        """Pop a screen, carrying what was just said across one pop only.

        Whatever was raised before the previous pop has been carried
        already and is dropped now. Judged by `raised_at`, because notify()
        only posts a message: a toast raised just before dismiss() is not
        stored yet when that pop happens.

        Uses two Textual internals; there is no public way to drop a
        single notification. Guarded, so that if Textual renames them a
        message is carried one pop too far instead of every pop raising.
        """
        if self.last_pop is not None:
            with suppress(AttributeError):
                for notification in list(self._notifications):
                    if notification.raised_at < self.last_pop:
                        self._unnotify(notification, refresh=False)
        self.last_pop = time.time()
        return super().pop_screen()

    def _fatal_error(self) -> None:
        """Print a crash's traceback without the local variables.

        Textual prints an unhandled exception with show_locals=True into
        the terminal's scrollback. Here the locals are the secrets: the
        password, the day's text, the key. The frames and line numbers
        stay, which is what a bug report needs.

        Overrides a private method, since Textual has no public setting
        for this. If it is ever renamed the locals come back, and
        tests/test_crash.py fails.
        """
        self.bell()
        self.panic(Traceback(show_locals=False, width=None, suppress=[rich]))

    def _on_unlocked(self, _result: None) -> None:
        """Called once UnlockScreen dismisses, i.e. the diary is open."""
        self.push_screen(EntryListScreen())

    def action_help(self) -> None:
        """Open the help popup, from whichever main view asked.

        On the app because two screens open it, and neither can import the
        popup, which imports them both to list their keys. Bound on those
        screens only, never app-wide, so '?' stays typeable in text fields.
        """
        self.push_screen(HelpScreen())

    async def action_quit(self) -> None:
        """Quit, but never silently over something half-written.

        Both 'q' on the main views and the app-wide ctrl+q dispatch this
        one action, so the question is asked in one place.
        """
        if self.is_working():
            # The password is being changed. Quitting now would not stop
            # the re-key, only the telling of it. Wait, and leave saying
            # how it ended (PasswordScreen.change_password).
            self.quit_pending = True
            self.notify(QUIT_WHEN_DONE)
            return
        if not self.locking_would_lose_work():
            self.exit()
            return
        # A question is already showing, most likely the editor's own
        # about the same writing. Let that one be answered.
        if isinstance(self.screen, ConfirmScreen):
            return
        self.push_screen(
            ConfirmScreen(UNSAVED_CHANGES, confirm_label="Quit", save_label=SAVE_AND_QUIT),
            self._quit_answered,
        )

    def _quit_answered(self, choice: Choice | None) -> None:
        """Leave on Quit, and on Save and quit once the writing is saved.

        Anything else stays. So does a save that failed: the screen
        holding the text has said why on its own error line.
        """
        if choice not in (Choice.CONFIRM, Choice.SAVE):
            return
        if choice is Choice.SAVE and not self.save_unsaved_work():
            return
        self.exit()

    def save_unsaved_work(self) -> bool:
        """Have every screen holding something unsaved write it out.

        Every one is asked before the answer is worked out; a
        short-circuit would save some of the writing and abandon the rest.
        """
        saved = [
            screen.save_pending()
            for screen in self.screen_stack
            if isinstance(screen, ZecretScreen) and screen.blocks_lock
        ]
        return all(saved)

    def action_lock(self) -> None:
        """ctrl+l from a screen that is not the editor: lock, saving first.

        Bound on every screen the open diary reaches. Saves rather than
        asks, as the editor's own does, because a popup can be sitting
        over an editor with writing in it. A save that fails keeps the
        diary open, with the reason on the editor's error line.

        While the password is being changed it waits, and the dialog
        locks when the change is over.
        """
        if self.is_working():
            self.lock_pending = True
            self.notify(LOCK_WHEN_DONE)
            return
        if not self.locking_would_lose_work():
            self.lock()
        elif self.save_unsaved_work():
            self.lock(SAVED_AND_LOCKED)

    def lock_if_idle(self) -> None:
        """Lock the diary if it has been left alone long enough.

        Called on a timer and before each activity event is stamped.

        Not named check_idle: Textual's MessagePump has a method of that
        name, called from refresh().
        """
        minutes = self.config.lock_after_minutes
        if minutes <= 0 or not self.is_unlocked or self.is_working():
            # Working: the password is being changed. The next check will
            # find it done.
            return
        if self.locking_would_lose_work():
            # A half-written entry holds the lock off, and counts as
            # activity, so the diary does not lock the moment it is saved.
            self.last_activity = Instant.now()
            return
        if self.last_activity.elapsed() >= minutes * 60:
            self.lock(LOCKED_BY_TIMEOUT)

    def is_working(self) -> bool:
        """Whether a screen on the stack must finish before a lock can land."""
        return any(
            isinstance(screen, ZecretScreen) and screen.working for screen in self.screen_stack
        )

    def locking_would_lose_work(self) -> bool:
        """Whether any screen on the stack is holding something unsaved.

        The whole stack: a modal over a half-written entry is still a
        half-written entry.
        """
        return any(
            isinstance(screen, ZecretScreen) and screen.blocks_lock for screen in self.screen_stack
        )

    def lock(self, message: str = LOCKED_BY_HAND) -> None:
        """Forget the diary and the key, and go back to the lock screen.

        The screens are torn down first, while the diary is still open:
        they redraw as they resume.
        """
        if not self.is_unlocked:
            return
        self.lock_pending = False
        while len(self.screen_stack) > 1:
            self.pop_screen()
        self.diary = None
        self.key = None
        # Pushing clears notifications, so the notify comes after it.
        self.push_screen(UnlockScreen(creating=False), self._on_unlocked)
        self.notify(message)

    @property
    def is_unlocked(self) -> bool:
        """Whether there is an open diary to be working in."""
        return self.diary is not None and self.key is not None

    @property
    def unlocked(self) -> tuple[DiaryFile, bytes]:
        """The open diary and the key it was opened with.

        Raises:
            RuntimeError: if the diary is not unlocked, which is a routing
                bug rather than a user error.
        """
        if self.diary is None or self.key is None:
            raise RuntimeError("the diary is not unlocked")
        return self.diary, self.key
