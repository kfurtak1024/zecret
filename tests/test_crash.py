"""What a crash leaves behind in the terminal.

Textual prints an unhandled exception after leaving the alternate screen,
so it stays in the scrollback -- and it printed every frame's local
variables, which in this app are the password, the day's text and the key.

Required coverage:
    - A crash still leaves a traceback: the exception and the frame it was
      raised in, which is what a bug report needs.
    - No local variable's value reaches it -- a password or an entry's text
      held by the frame that raised.
    - A screen change survives a Textual that has renamed the internals
      ZecretApp.pop_screen tidies notifications with.
    - An Entry's repr carries no body, and a DiaryFile's no entries: a repr
      is what anything printing an object by accident shows.
"""

from __future__ import annotations

import datetime as dt

import pytest
from textual.app import App
from textual.screen import Screen

from zecret.app import ZecretApp
from zecret.crypto import KdfParams
from zecret.models import Entry
from zecret.storage import DiaryFile

SECRET_PASSWORD = "hunter2-master-password"
SECRET_BODY = "the thing nobody may read"


async def test_a_crash_leaves_a_traceback_without_the_locals(tmp_path, capfd):
    app = ZecretApp(diary_path=tmp_path / "diary.enc")

    def explode() -> None:
        password = SECRET_PASSWORD
        body = SECRET_BODY
        raise RuntimeError(f"a bug, {len(password) + len(body)} characters in")

    with pytest.raises(RuntimeError):
        async with app.run_test() as pilot:
            app.call_later(explode)
            await pilot.pause()

    # Read from the process's own stderr, which is where Textual prints it
    # once the app has gone -- and empties its list of what to print.
    said = capfd.readouterr().err
    assert "RuntimeError" in said
    assert "explode" in said, "the frame that raised is the part worth having"
    assert SECRET_PASSWORD not in said
    assert SECRET_BODY not in said


def test_an_entry_s_repr_leaves_out_its_body():
    entry = Entry.new(dt.date(2026, 10, 16), SECRET_BODY)
    assert SECRET_BODY not in repr(entry)
    assert "2026, 10, 16" in repr(entry), "the date still says which entry it is"


def test_a_diary_s_repr_leaves_out_its_entries(tmp_path):
    day = dt.date(2026, 10, 16)
    diary = DiaryFile(
        path=tmp_path / "diary.enc",
        kdf_params=KdfParams.generate(),
        entries={day: Entry.new(day, SECRET_BODY)},
    )
    assert SECRET_BODY not in repr(diary)
    assert "2026, 10, 16" not in repr(diary)


async def test_a_screen_change_outlives_a_renamed_textual_internal(tmp_path, monkeypatch):
    monkeypatch.delattr(App, "_unnotify")
    app = ZecretApp(diary_path=tmp_path / "diary.enc")
    async with app.run_test() as pilot:
        app.push_screen(Screen())
        app.push_screen(Screen())
        await pilot.pause()
        # Carried across the first pop, and due to be dropped at the second
        # -- which is the step that reaches for the missing internal.
        app.notify("Said before the pops.")
        await pilot.pause()
        app.pop_screen()
        await pilot.pause()
        app.pop_screen()
        await pilot.pause()
        assert app.is_running
        assert len(app.screen_stack) == 2, "both pops went through"
