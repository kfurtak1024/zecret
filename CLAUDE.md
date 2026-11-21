# CLAUDE.md — Zecret

Guidance for Claude Code in this repository. Read it in full before
implementing anything.

This file states the rules as they are. Why a rule exists is given in one
line where it constrains future changes; the story of how it was found
belongs in the commit history.

## What this project is

Zecret is an encrypted terminal diary: one user, local, protected by a
master password. A Textual TUI. No server, no sync, no multi-user.

**One entry per calendar day.** The date is the entry's identity: no id,
no title, at most one entry per day. The date is the *local* day. Screens
ask for a date and hand it to the editor, which looks up whether that day
is written. Nothing in the UI decides between "new" and "edit".

The repository is **implemented and tested**. Keep public interfaces as
they are unless there is a concrete reason to change one; if you do,
update this file.

## Tech stack (fixed — do not substitute)

- **Python 3.13**, managed with `uv`, pinned in `.python-version`.
  `requires-python` is `>=3.13`: a floor, because Zecret is on PyPI and a
  `pip` user gets whatever interpreter their system ships. 3.13 is the
  only version developed and tested on. `requires-python`, mypy's
  `python_version`, ruff's `target-version` and CI all name 3.13 and move
  together.
- **Textual** for the TUI. Use widgets, screens and CSS idiomatically; no
  hand-rolled ANSI, no `curses`.
- **argon2-cffi** for key derivation (Argon2id only).
- **cryptography** for AEAD encryption.
- **zxcvbn** for rating a password being chosen. Advisory only; nothing in
  the crypto or storage path depends on it.
- **pytest** (+ `pytest-asyncio`, `pytest-xdist`, `hypothesis`).
- **ruff** for lint and format; **mypy** strict over `src/` and `tools/`.

Dependency floors track current releases; `cryptography` in particular
must not drift onto an unpatched release. **Textual has a ceiling below
its next major**, because Zecret relies on a few internals with no public
equivalent: `ZecretApp` overrides `_fatal_error` and uses `_notifications`
/ `_unnotify` in `pop_screen`, and the editor depends on the order
TextArea paints in. Do not add another internal where a public hook
exists (`notify_style_update()` is how the mask clears TextArea's line
cache). Dev tools live in the PEP 735 `[dependency-groups]` table, which
`uv sync` installs by default.

## Architecture

```
src/zecret/
├── crypto.py     # KDF (Argon2id) + AEAD. Bytes in, bytes out.
├── models.py     # Entry dataclass + JSON (de)serialization.
├── storage.py    # DiaryFile: on-disk format, atomic writes, crypto + models.
├── config.py     # Preferences in a plaintext file. Never diary content.
├── strength.py   # Password rating (zxcvbn). The only place the password
│                 # reaches third-party code.
├── app.py        # ZecretApp: routing, session state, idle lock, guarded quit.
├── screens/
│   ├── base.py           # ZecretScreen, FormScreen, DayList, card(), plain(),
│   │                     # shared formatting and wording, delete_day().
│   ├── header.py         # DiaryHeader and DiaryFooter (every screen, modals too).
│   ├── unlock.py, entry_list.py, calendar_view.py, editor.py, search.py,
│   │   settings.py, help.py          # one screen each
│   ├── confirm.py, date_prompt.py, password.py   # modals
│   ├── calendar.py       # MonthCalendar / YearCalendar widgets
│   ├── text_area.py      # DiaryTextArea: editing keys, mask, emphasis
│   └── prose.py          # pure text rules: word runs, emphasis spans
└── __main__.py   # CLI entry point.
```

Layering, kept strict:

- `crypto.py` knows nothing about entries or files.
- `models.py` knows nothing about encryption or paths.
- `storage.py` is the only place that touches the filesystem or combines
  crypto and models, with one bounded exception: `config.py`.
- `config.py` owns `~/.zecret/config.json`, the only file written in the
  clear. **Preferences and nothing else**: no entry text, no dates, no
  password, nothing derived from the key. It is forgiving where storage is
  strict: a missing or corrupt config means defaults. The path is
  redirectable (`--config` / `ZECRET_CONFIG_PATH`). `ZecretApp` resolves
  the default when constructed, not at import, so tests can redirect it:
  `__main__.py` passes `None`, and `conftest.py`'s autouse
  `isolated_config` depends on that.
- `screens/*.py` never call `crypto.py` or the filesystem. They go through
  `app.diary` and `app.key`. Where a screen needs something crypto-shaped,
  storage grows the method (`verify_password()`, `change_password()`).
- `DiaryFile.create_new()` and `unlock()` return `(DiaryFile, key)`,
  because screens may not call `derive_key()`.
- **Presentation belongs to the screens.** `DiaryFile.entries` is an
  unordered mapping. Sorting, grouping and wording stay in the screen.
- `screens/prose.py` is pure functions on strings, with no Textual. Rules
  about where words and phrases are go there; drawing goes in
  `text_area.py`; anything about the diary goes in `editor.py`.

### Rules the screens follow

- **Row width belongs to the terminal.** A list row carries the entry's
  whole first line and `app.tcss` trims it at render time. Never compute
  the trim from a measured width: that means rebuilding every row on
  resize. `SNIPPET_CAP` is a guard against one huge pasted line, not a
  display width.
- **Text Zecret did not write never reaches Textual as markup.** A string
  handed to a `Label`, an `Option` or `notify()` is parsed as markup and a
  stray closing tag raises `MarkupError`. Entry text, error lines, paths,
  OS errors and anything quoting the diary file go through `plain()`, and
  a notification carrying anything but a constant passes `markup=False`.
  Headless tests mount no toasts, so a notification is tested by rendering
  a `Toast` from it.
- **A list of days is a `DayList` (an `OptionList`), never a `ListView`.**
  A ListView mounts a widget per row. Rows are built with `day_row()`. A
  rebuild is synchronous and happens on resume only when the diary changed
  (`unchanged()`, by identity). The page keys stay with the screen
  (`priority=True`) and count screen lines, not rows (`HEADING_LINES`).
  `tests/test_scale.py` holds the rebuild to a ceiling at ten years.
- **A card is built with `card()`**, a `VerticalScroll` with
  `can_focus=False`, so the panel is not an empty stop on the tab ring.
  `HelpScreen` builds its own and stays focusable. `ZecretScreen.AUTO_FOCUS`
  is `""` (not `None`): every screen says what it opens focused on in
  `on_mount`. `tests/test_chrome.py` checks both.
- **Every screen carries a `DiaryFooter`, modals included.** A modal
  without one shows the bar of the screen beneath, with every key dead.
- **Notifications belong to the app.** `ZecretApp.push_screen` clears them
  (pushing starts something new). `pop_screen` carries a message across
  one pop only, judged by `raised_at`. Anything that pushes a screen and
  then notifies must do it in that order; see `lock()`.

## Security requirements (non-negotiable)

Do not weaken any of these for convenience.

1. **Argon2id only**, with the `KdfParams` defaults (`time_cost=3,
   memory_cost=65536, parallelism=4`). No PBKDF2, no lower defaults.
2. **Unique nonce per encryption call.** Generated inside `encrypt()`,
   never passed in.
3. **AEAD only.** The cipher is **AES-256-GCM** (`cryptography` does not
   expose XChaCha20-Poly1305). It is fixed, not negotiated: the format
   records no cipher id, so changing it needs a version bump and a
   migration. Decryption fails loudly (`ZecretDecryptError`).
4. **No plaintext ever touches disk.** No temp files of decrypted content,
   no logging of entry text or password. A crash counts:
   `ZecretApp._fatal_error` prints the traceback without locals, and
   `Entry.body` and `DiaryFile.entries` are out of their reprs.
   `tests/test_crash.py` guards this.
5. **Atomic writes only.** `save()` writes a temp file in the same
   directory, fsyncs, then `os.replace()`s. Creating a diary is the one
   exception: it writes directly under `O_CREAT|O_EXCL`
   (`_create_exclusively()`), because the rename is the step that would
   flatten a diary another process had just created. Stale temp files from
   a killed save are swept by the next save, only when older than
   `STALE_TEMP_SECONDS`.
6. **Per-entry independent encryption.** Editing or deleting one entry
   never decrypts or re-encrypts another entry's ciphertext.
7. **Fail closed.** Every failure to read the diary is a refusal: never
   swallowed, never a diary with days left out, never an empty one. The
   key verifier is checked first, and its failure is the only one that
   means a wrong password (`ZecretDecryptError`). A record that fails
   after it is `ZecretDamagedError`; a newer format is
   `ZecretVersionError` (both `ValueError`s). Argon2 failing to allocate
   is `MemoryError`. The unlock screen names each one. The KDF header is
   parsed strictly: whole numbers and a named algorithm, nothing coerced.
8. **Never overwrite a diary this session did not last write.** `save()`
   compares the file's mtime and size with what they were at the last
   read or write and raises `ZecretConflictError`. Every screen that saves
   does so inside `DiaryFile.saving(key)`, which restores memory if the
   save fails. Do not hand-write that undo in a screen.
   The editor does not stop at a refusal. It re-reads the file
   (`DiaryFile.reopen`) and, if this day there is still what it opened,
   files the day into the re-read diary and adopts it. If the other
   session changed the same day, nothing is written until ctrl+s has asked
   whose version to keep (`EditorScreen._save_onto_reread`), and nothing
   is adopted while that question is open.

**The idle lock is checked on the event path as well as on a timer.**
`ZecretApp.on_event` calls `lock_if_idle()` *before* stamping an activity
event. The timer sleeps on the monotonic clock, which stops during
suspend, so the first key after resume arrives before the tick; stamping
it first would keep the diary open. The event that finds the diary overdue
locks it and is not delivered.

Known limits are listed in `SECURITY.md` under *Known and accepted*,
including that integrity is per record, not per file.

## File format

The module docstring in `storage.py` is the authoritative shape.

**The format is version 1 and that number is frozen.** A change bumps the
version and adds a migration keyed off it. `_load_document()` matches the
version exactly (`type is int`) and refuses anything else.

Entries carry `created_at` and `updated_at`, and no screen shows either.
That is settled: do not add UI for them, and do not add more fields.

Known and accepted: record dates are outside the ciphertext, so the file
reveals which days have entries. The outer-vs-authenticated date check
depends on that. Do not move the date inside without replacing that check
with something equally strong.

## Working on it

For a change that spans layers, the order of priorities is `crypto.py`,
`models.py`, `storage.py`, then `app.py` and the screens, and `app.tcss`
last. Get storage right and tested before touching the UI. Bugs in
`crypto.py` and `storage.py` are the ones that matter most.

**Never develop against a real diary, and never run `uv run zecret`
bare.** Use:

```
./zecret-dev.sh
```

It seeds a throwaway diary and opens it with **both** `--path` and
`--config`. Forgetting `--config` silently writes the preferences you
actually use, which is why the pair is a script. Everything lives in
`.zecret-dev/`, gitignored and absent from the sdist allowlist.

`tools/seed_dev_diary.py` does the seeding (password `dev`, deterministic
per `--seed`). It refuses to write inside `~/.zecret`. Add to `EDGE_CASES`
when a new shape of entry breaks something.

## Testing

- Every test file lists its required coverage in its docstring. Treat the
  list as a checklist and extend it when adding behaviour.
- **Test the path the user takes, not only the function behind it.** A
  test that sets state and calls the check directly can pass while the
  event path is wrong, which is how the idle lock's suspend hole went
  unnoticed. Where a behaviour is reached by a key or an event, at least
  one test drives it that way.
- Run `uv run pytest` before considering a module done, and
  `uv run ruff check . && uv run ruff format . && uv run mypy` before
  calling it clean. CI runs those on the one interpreter in
  `.python-version`.
- The suite runs in parallel (`-n auto`). Every test stands alone: its own
  `tmp_path`, no shared state. Use `-n0` to debug.
- CI runs `pytest --cov -m ""`; the threshold in `[tool.coverage.report]`
  only ratchets up. Coverage and the `slow` tests are not in the default
  local run.
- Any test that opens a diary requests the `cheap_kdf` fixture
  (`pytestmark`). It is not autouse, because `tests/test_crypto.py`
  asserts the real parameters.
- `filterwarnings = ["error"]`: a deprecation warning fails the suite.
- CI sets `UV_LOCKED=1`, so `uv.lock` is regenerated and committed
  whenever `pyproject.toml` changes.
- Storage tests use `tmp_path` for all file I/O.

## Releasing

Zecret is on PyPI as [`zecret`](https://pypi.org/project/zecret/). A
release is a tag: pushing `vX.Y.Z` runs `.github/workflows/release.yml`.
No manual upload, no `workflow_dispatch`.

Four jobs, each gating the next:

1. **check** — the tag must equal `pyproject.toml`'s `version`.
2. **verify** — ruff, mypy and `pytest --cov -m ""` on the tagged commit.
3. **pypi** — `uv build`, then Trusted Publishing (OIDC). **There is no
   API token in this repo or its secrets, and there must not be.**
4. **github-release** — `gh release create` with notes from
   `CHANGELOG.md`. It fails if it finds no section for the version.

Before tagging:

- Rename `[Unreleased]` in `CHANGELOG.md` to `[X.Y.Z] - YYYY-MM-DD`, add a
  fresh `[Unreleased]`, update the link definitions.
- Regenerate the screenshots (`uv run python tools/screenshots.py`). The
  help popup shows the version, so every bump makes `assets/help-*.png`
  stale.
- Bump `version` in `pyproject.toml` (the only place it is written) and
  re-lock.
- Let CI go green on main.

Outside the repo, configured once:

- **PyPI trusted publisher**: project `zecret`, owner `kfurtak1024`, repo
  `zecret`, workflow `release.yml`, environment `pypi`. Renaming the
  workflow or environment breaks publishing.
- **The `pypi` environment's deployment rule** must be ref type **Tag**,
  pattern `v*`. A branch rule permits nothing and fails late. Do not add
  `main`.

A published version number is consumed permanently.

## Conventions

### Code

- Type hints everywhere; `uv run mypy` stays green. Screens are
  `Screen[None]` unless they return a value via `dismiss()`.
- `Entry` is a frozen dataclass. Edits go through `entry.edited(body)`.
  There is deliberately no way to change an entry's date.
- `import datetime as dt`; `from __future__ import annotations` in every
  module.
- Raise specific exceptions, never a bare `Exception` or silent failure.
- No print debugging in committed code.
- **Comments and docstrings say what the code does and the constraint a
  reader must not break. They do not narrate history.** "X used to do Y
  and was reported as Z" goes in the commit message. Keep a reason when
  removing it would invite someone to undo the fix; state it in a
  sentence. Update a docstring when behaviour changes.

### Locking, quitting and saving

- **Locking by hand saves; the idle timer refuses.** `ctrl+l` in the
  editor saves and locks only if the save succeeded. The idle lock holds
  off while `blocks_lock` is true. Quitting (`ZecretApp.action_quit`)
  asks.
- `ctrl+l` is bound on every screen once the diary is open (`app.lock`),
  and saves whatever an editor underneath holds first.
- A screen that is `working` (the password dialog while it re-encrypts)
  makes a lock or quit wait: `lock_pending` / `quit_pending`. The dialog
  acts on them when it ends, and a quit leaves the outcome in the
  terminal through `App.exit(message=...)`.
- **Idleness is measured on two clocks and the longer wait wins**
  (`Instant` in `app.py`). `time.monotonic()` stops during suspend; the
  wall clock can be set backwards. Do not swap this for `CLOCK_BOOTTIME`.
- **The unsaved-changes question has three answers.** `ConfirmScreen`
  dismisses a `Choice` (`CONFIRM`, `SAVE`, `CANCEL`) and shows a third
  button when given a `save_label`. Deleting stays two-answer with focus
  on Cancel. Where saving is offered, focus starts there. `SAVE` reaches
  the editor through `ZecretScreen.save_pending()`. A refused save never
  leaves the screen.
- **Saving is not leaving.** `ctrl+s` writes and stays; `escape` leaves.
  `_save()` returns True without writing when nothing changed, so a reflex
  save does not restamp `updated_at` or cause a conflict.

### Passwords

- **A password being chosen is rated, never refused.** `UnlockScreen`
  (creating) and `PasswordScreen` call `FormScreen.advise_on_password()`.
- **Rating needs a dictionary, hence `zxcvbn`.** Do not replace it with a
  length-and-classes heuristic. `strength.py` is the single call site.
  zxcvbn raises past `MAX_SCORED` characters, so a longer password is
  rated on its first `MAX_SCORED`.
- The reading goes on the **error row**, which is fixed at `height: 1`.
  `rate()` is given the row's measured width and shortens advice rather
  than let it be cut off. The `-advice` class marks the line as
  withdrawable, so clearing a reading cannot clear an error. Amber then
  green, never `$error`.
- The same row carries a `-status` line while Argon2id runs
  (`FormScreen.set_status`), with the fields disabled.
- **Changing the master password is a dialog, not a form field.** The
  warning is first on the screen. Title, warning and three fields come to
  exactly the eighteen rows a 24-row terminal leaves, which is why the
  card is 70 columns wide. `PasswordScreen` inherits `ModalScreen[None]`
  **and** `FormScreen`, in that order; both matter (see its docstring).

### The editor

- **The mask is drawn, never written.** `ctrl+r` covers every word but the
  one the cursor touches, in `DiaryTextArea.get_line`. Each covered
  one-cell character is swapped for `BAR`. **Only single-cell characters
  are swapped**; wider ones are painted in ink the colour of their own
  background, so the mask's colour must be opaque and identical for text
  and background. The line cache is cleared in `watch_masked`, the
  cursor-line highlight is off, and the selection has its own bar in
  `app.tcss`. Anything else that draws over the editor must be checked
  against those. The state lives on `ZecretApp.masked` and is deliberately
  not in `config.py`.
- **Emphasis is drawn, never written, and is the only markup.** A phrase
  between asterisks takes `$text-success` **and** bold; the marks take the
  colour alone. The asterisks stay on screen. `strong_spans()` in
  `prose.py` is the whole rule, including the one departure from
  Markdown: **a phrase may not open straight after a digit**. A span
  never crosses a line. **The mask wins**: a masked line is never
  emphasised. Always on, no setting. Do not grow this into Markdown.
- `DiaryTextArea` passes `highlight_cursor_line=False`, because TextArea
  paints that band after `get_line` and would wipe both.
- **The editor wraps before it paints** (`DiaryTextArea.render_lines`),
  since TextArea rewraps on a queued `Resize`.
- **Text-editing keys belong to the widget, not the screen.**
  `EditorScreen.BINDINGS` holds four keys, all about the diary. Keys about
  the text go on `DiaryTextArea`, which keeps them out of the help popup
  and key bar. The same split puts arrows on the calendars and `[` `]` on
  `CalendarScreen`, and `down` on `DateInput`.
- **Moving by a word stops at word ends going right and word starts going
  left.** That is the platform convention; do not make them symmetric.
  `DiaryTextArea` overrides both word-location methods to take a run of
  same-class characters whole, with whitespace as its own class.

### The calendars (`screens/calendar.py`)

- `MonthCalendar` is one month (the date prompt). `YearCalendar` is twelve
  `MonthGrid`s that draw and own nothing, so one cursor walks the year.
  They share keys through `WalkableCalendar`, drawing through
  `draw_month` / `day_role`, and the `month-calendar--*` component
  classes. `CalendarLegend` uses the today class too.
- How many months sit across is the stylesheet's call, from the
  `-months-N` class `CalendarScreen.fit_months` sets by hand in `on_mount`
  and on resize (Textual's breakpoints apply after the first paint). The
  screen holds repaints (`App.batch_update`) until it has scrolled to the
  cursor's month, released in a `finally` and on unmount.
- In the year the arrows are spatial (`spatial_step`): they stop at the
  edge of the year and refuse a future day. `MonthCalendar` keeps
  day-and-week arrows.
- A calendar owns no date. The grid **announces** its moves
  (`DateChanged`, `DatePicked`); the field moves the grid **quietly**
  (`MonthCalendar.show`). That asymmetry keeps a half-typed date from
  being completed under the writer's cursor.
- Which days are written is handed in (`frozenset(diary.entries)`), never
  looked up by a widget.
- The calendar view is a screen pushed over the list. The list reads
  `CalendarScreen.date` (a plain copy, never the widget) and
  `EntryListScreen.editing` in its own `on_screen_resume`, never in a
  dismiss callback. A resume that arrives while another screen is in
  front decides nothing.

### Chrome, keys and help

- **Every bar reads the same way**: this screen's actions, the way out,
  then `^l Lock`, and `? Help` and `q Quit` on the two main views. A full
  screen's way out is **Back**, a popup's is **Cancel** or **Close**, and
  the main views name where `c` goes. One action has one name everywhere
  (**Edit**). Words are the writer's (`^r` is **Cover**).
- **`show` is a layout decision.** It puts a binding in the footer and
  nothing more; the help popup lists every binding
  (`documented_bindings()`).
- **The key bar fits 80 columns.** The entry list's eight keys take 69.
  The next key means shortening a description or `show=False`.
  `tests/test_chrome.py` fails when it stops fitting. `ctrl+l` is shown
  because finding it is a security property.
- **Bindings are declared in reading order**: frequent, rare, movement.
- Textual's `Header` is not used and the command palette is off. Do not
  reintroduce either.
- The help popup is a `ModalScreen`, generated from the screens'
  `BINDINGS`. Never hand-write a key into it. It is bound to `?` on the
  two main views only, via `app.help`. A section longer than
  `COLUMN_THRESHOLD` splits into two columns, and `fit_columns()` stacks
  them on a narrow terminal. Its full height is coupled to `ROWS["help"]`
  in `tools/screenshots.py` and `SHOT_ROWS` in
  `tests/test_help_screen.py`.
- The version shown comes from `zecret.__version__`; `pyproject.toml` is
  the only place it is written.

### Styling

Styling lives in `app.tcss`, which states its conventions at the top:
theme variables only, rules grouped by role, 1 cell vertical to 2
horizontal. `$error` is for errors, destructive actions, `.caution` and
the change-password button; do not spend it on anything less final. Text
starts at the same column on every full-width screen
(`tests/test_chrome.py`). Light themes are handled in the `:light` section
at the foot of the file; adding a card means adding it to those selector
lists. The mask's `:light` rule is the exception and stays beside the rule
it overrides. `:light` must sit on the widget, not on a component class.
Screens carry a `SUB_TITLE`.

### Documentation

**A user-facing change is not done until the documentation matches**, in
the same commit:

- `README.md`: the key table, the feature list, the prose.
- `docs/index.html`: the key table, feature cards, "How it works", and the
  drawn terminals. `tests/test_docs_page.py` checks keys, counts and
  parameters; the prose is on you. The page is a single self-contained
  file with no third-party requests.
- `CHANGELOG.md`: under `Unreleased`, in terms of what changed for the
  writer.
- `assets/*.png`: regenerate with `tools/screenshots.py` if anything
  visible changed. Nothing fails when this is forgotten.
- `SECURITY.md`: if a security property or a known limit moved.
- `CLAUDE.md`: if an interface, layer or rule moved.
- The in-app help builds itself from `BINDINGS`.

## Explicit non-goals (do not implement unless asked)

- No cloud sync, no networking.
- No tags, mood ratings or attachments.
- No Markdown and no rich text beyond the one emphasis mark.
- No rendering of an entry anywhere but the editor.
- No titles.
- No more than one entry per day, and no future-dated entries.
- No multi-user support.
- No password recovery.
- No plugin system.

If a task seems to require one of these, stop and ask.
