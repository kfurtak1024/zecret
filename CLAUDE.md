# CLAUDE.md — Zecret

This file guides Claude Code when working in this repository. Read it in
full before implementing anything.

## What this project is

Zecret is an encrypted terminal diary. A single user, locally, protects
their diary entries with a master password. The app is a Textual-based TUI
— no web server, no sync, no multi-user concerns.

**One entry per calendar day.** The date is the entry's identity: there is
no id and no title, a day holds at most one entry, and opening a day means
writing it or continuing what is already there. The date is the *local*
day, so an entry written at 23:50 belongs to the day the writer would name.
Screens ask for a date and hand it to the editor, which looks up whether
that day has been written — nothing in the UI decides between "new" and
"edit" for itself.

The repository is **implemented and tested**. Keep the public interfaces
as they are unless you find a concrete reason to change one; if you do,
update this file to match.

## Tech stack (fixed — do not substitute)

- Python 3.13, managed with `uv` (`uv sync`, `uv run`, `uv add <pkg>`) and
  pinned in `.python-version`. `requires-python` is `>=3.13` — a floor, not
  a pin, so newer interpreters are permitted — but 3.13 is the only one
  developed and tested on, and a mistake that only a later version forgives
  is meant to fail here rather than on a user's machine. The floor is not
  higher because Zecret is published to PyPI: a `pip`/`pipx` user gets
  whatever interpreter their system ships, and a floor above that is a
  resolver error rather than an install. `requires-python`, mypy's
  `python_version`, ruff's `target-version` and the CI job all name 3.13,
  and move together if it ever rises.
- **Textual** for the TUI — use widgets/screens/CSS idiomatically; don't
  hand-roll ANSI escape codes or use `curses` directly
- **argon2-cffi** for key derivation (Argon2id specifically, not Argon2i/d)
- **cryptography** for AEAD encryption
- **pytest** (+ `pytest-asyncio` for Textual screen tests) for testing
- **ruff** for linting and formatting (`uv run ruff check .`,
  `uv run ruff format .`) — config lives in `pyproject.toml`
- **mypy** in strict mode over `src/` (`uv run mypy`)

Dependency floors track current releases rather than the oldest version
that happens to work; `cryptography` in particular should not be allowed to
drift onto an unpatched release. Dev-only tools live in the PEP 735
`[dependency-groups]` table, which `uv sync` installs by default — so a
bare checkout can run `uv run pytest` with no extra flags.

## Architecture

```
src/zecret/
├── crypto.py     # KDF (Argon2id) + AEAD encrypt/decrypt. No file I/O, no entry semantics.
├── models.py     # Entry dataclass (date + body) + JSON (de)serialization. No crypto, no file I/O.
├── storage.py    # DiaryFile: owns the on-disk format, atomic writes, ties crypto+models together.
├── config.py     # Preferences (the theme) in a plaintext file. Never diary content — see below.
├── app.py        # ZecretApp (Textual App subclass): screen routing, session state, idle lock, guarded quit.
├── screens/      # One file per screen: unlock, entry_list, editor, search, settings, help.
│                 # Plus shared pieces: base.py (ZecretScreen for typed
│                 # access to the app, FormScreen for the screens with
│                 # fields and an error line, the date/snippet formatting
│                 # every screen shares, and the wording for a refused
│                 # save), header.py (both bars -- the title above and the
│                 # keys below, which every screen wears including the
│                 # modals), confirm.py (yes/no modal) and date_prompt.py
│                 # (which-day modal).
└── __main__.py   # CLI entry point (`zecret` command): arg parsing, launches ZecretApp.
```

Keep this layering strict:
- `crypto.py` knows nothing about entries or files — just bytes in, bytes out.
- `models.py` knows nothing about encryption or file paths.
- `storage.py` is the only place that touches the filesystem or combines
  crypto + models — with one bounded exception, `config.py`.
- `config.py` owns `~/.zecret/config.json`, the only file Zecret writes in
  the clear. It exists because the theme has to be known before the diary
  is unlocked -- as does how long the diary may sit idle, since that timer
  runs from launch -- and a preference is neither secret nor writing. **It may
  hold preferences and nothing else** — no entry text, no dates, no
  password, nothing derived from the key. Anything that would tell a reader
  of that file something about the diary's contents belongs in the diary,
  behind the password. Security requirement 4 below is about entry content
  and passwords; a theme name is neither, which is why this is an exception
  and not a violation. It is also forgiving where `storage.py` is strict: a
  missing or corrupt config falls back to defaults, because a mangled
  preference must never be why someone cannot reach their diary. The path
  is the default rather than a constant: `--config` / `ZECRET_CONFIG_PATH`
  redirects it, which is what lets a development build run without writing
  the preferences someone actually uses. `ZecretApp` resolves the fallback
  when it is constructed, not at import time, so tests can redirect it —
  `__main__.py` passes `None` for "you decide" rather than naming the
  default itself, and `conftest.py`'s autouse `isolated_config` fixture
  depends on that.
- `screens/*.py` never call `crypto.py` or the filesystem directly — they
  only go through `app.diary` (a `DiaryFile`) and `app.key`. Where a screen
  needs something crypto-shaped, storage grows the method: this is why
  `DiaryFile.verify_password()` exists, for the settings screen's re-check
  of the current password.
- Presentation belongs to the screens, and stays there. The entry list
  groups days under a month heading; `DiaryFile.entries` is an unordered
  mapping and knows nothing about it. Sorting, grouping and wording are the
  screen's business — don't push them down into storage to save the screen
  a `sorted()`.
- **How wide a row is belongs to the terminal, not to Python.** A list row
  carries the entry's whole first line and `app.tcss` trims it at render
  time (`text-wrap: nowrap` + `text-overflow: ellipsis`), so a wide window
  shows more of a day for free. Never compute the trim from a measured
  width: that makes the row text depend on the size, which means rebuilding
  on resize, and `refresh_entries()` is a full clear-and-remount that takes
  over a second at 1500 entries — on every event of a window drag.
  `SNIPPET_CAP` in `screens/base.py` is a guard against one pasted
  paragraph with no newline in it, not a display width; it is far past any
  terminal, and shortening it back into a width would undo this.

Interface note: `DiaryFile.create_new()` and `DiaryFile.unlock()` return
`(DiaryFile, key)`, not just the `DiaryFile`. The derived key has to reach
`app.key`, and screens may not call `derive_key()` themselves under the
layering rule above — so storage hands it back, the same way
`change_password()` already returns the new key.

## Security requirements (non-negotiable)

These are the properties the test suite and any code review should verify.
Do not weaken any of these for convenience:

1. **Argon2id only**, with the parameters already stubbed in
   `KdfParams` (`time_cost=3, memory_cost=65536, parallelism=4` — roughly
   OWASP-recommended interactive settings). Do not drop to PBKDF2 or
   lower these defaults.
2. **Unique nonce per encryption call, always.** Never let a nonce be
   reused with the same key. Generate it fresh inside `encrypt()` — never
   pass one in from outside.
3. **AEAD only** (authenticated encryption) — never plain CBC or CTR mode
   without a MAC. Wrong-password / tampered-data detection depends on this:
   decryption must fail loudly (`ZecretDecryptError`) rather than silently
   returning garbage. The cipher is **AES-256-GCM**: `cryptography` still
   does not expose XChaCha20-Poly1305 (checked against 50.0.0), so the
   documented fallback is what ships. It is fixed rather than negotiated —
   the file format records no cipher id, so changing it needs a format
   version bump and a migration.
4. **No plaintext ever touches disk.** No temp files containing decrypted
   entry content, no debug logging of entry text or password, no writing
   plaintext for "crash recovery" purposes.
5. **Atomic writes only.** `DiaryFile.save()` must write to a temp file in
   the same directory, `fsync()`, then `os.replace()` over the real path.
   Never write directly to the live diary file in place. Creating a diary
   is the one exception, and guards a different failure: it writes to the
   target directly under `O_CREAT|O_EXCL` (`_create_exclusively()`), because
   the temp-and-rename dance protects a diary that is already there, and
   the rename is itself the step that would flatten one another process had
   just created. There is no live file to damage at that point, and a
   failed creation unlinks what it started.
6. **Per-entry independent encryption.** Editing or deleting one day's
   entry must never require decrypting or re-encrypting any other entry's
   ciphertext. This is what the storage tests check for explicitly.
7. **Fail closed.** Any decryption failure surfaces as
   `ZecretDecryptError` and is caught at the UI layer to show "incorrect
   password" — never swallowed, never defaults to an empty diary.
8. **Never overwrite a diary this session did not last write.** A
   `DiaryFile` holds the whole diary in memory, so a second Zecret open on
   the same file would otherwise write its copy over the first's entries
   with no error at all. `save()` compares the file's mtime and size
   against what they were when it last read or wrote it, and raises
   `ZecretConflictError` instead. Every screen that saves rolls its
   in-memory change back and says so. The same failure reaches creating a
   diary by a different road — two Zecrets started with no diary, both
   passing the "is one there?" check, both going on to write — and the
   mtime check cannot see it, since neither has a stamp to compare
   against. That case is closed by the exclusive create in requirement 5,
   not here.

## File format

See the module docstring in `storage.py` for the authoritative JSON shape.

**The format is version 1 and that number is now frozen.** It was reset to
1 while no diary anywhere depended on it — the last moment that was free to
do. From here the header field is a promise, not a draft: if you change the
format, bump the version and **write a migration** keyed off it. Renumbering
again, or quietly widening what version 1 means, is not an option, and
"nobody is using it yet" is no longer true. `_load_document()` matches the
version exactly (`type is int`, not `==`, because `True == 1` and
`1.0 == 1` in Python and neither is a format version) and refuses anything
else rather than half-reading it.

Entries carry `created_at` and `updated_at`, and no screen shows either.
That is deliberate and settled: the date names the entry, and a diary does
not need to tell you when you typed it. They stay in the format because
taking them out would be a format change for no gain — but don't add UI for
them, and don't take them as licence to add more fields "since they're
free".

Known and accepted: the record dates are outside the ciphertext, so the
file reveals *which days* have entries, though not a word of what they say.
That is what lets a record be named without decrypting it, which in turn is
what the outer-vs-authenticated date check depends on. Don't "fix" it by
moving the date inside without replacing that check with something equally
strong.

## Working on it

The build order the project was first written in — `crypto.py`, then
`models.py`, `storage.py`, `app.py` + `unlock.py`, `entry_list.py`,
`editor.py`, `search.py`, `settings.py`, and `app.tcss` last — is still the
right order of priorities for a change that spans layers: get storage right
and tested before touching the UI, and leave visual polish until the
behavior is settled. Bugs in `crypto.py` and `storage.py` are the ones that
actually matter.

**Never develop against a real diary, and never run `uv run zecret` bare.**
The working tree is the program: an unfinished `storage.py` opening
someone's own diary is how entries get lost. Use the script instead —

```
./zecret-dev.sh
```

— which seeds a throwaway diary if there is not one yet and opens it with
**both** overrides, `--path` and `--config`. Both are required and only one
of them fails loudly: forgetting `--path` shows you your own diary, which
you notice, while forgetting `--config` silently writes the preferences you
actually use. That is the whole reason the pair is in a script rather than
in a shell alias someone retypes.

Everything lives in `.zecret-dev/` inside the checkout — gitignored, and
absent from the sdist allowlist in `pyproject.toml`, which is what keeps it
out of a release. Delete it whenever; the next run rebuilds it.

`tools/seed_dev_diary.py` is what does the seeding, and is worth running
directly when you want different data: a few hundred generated days,
deterministic per `--seed`, behind the password `dev`. It **refuses to
write anywhere inside `~/.zecret`**, which is the guard that makes it safe
to point `--path` somewhere by hand. A few of the seeded days are awkward
on purpose (very long, one word, emoji, an unbroken line with nothing to
wrap on) and it prints which dates they landed on. Add to `EDGE_CASES` when
a new shape breaks something, so the next regeneration still has it.

## Testing

- Every test file lists its required coverage in its docstring — treat
  those lists as a checklist, not a suggestion, and extend the list when
  you add behavior worth guarding.
- Run `uv run pytest` before considering any module done, and
  `uv run ruff check . && uv run ruff format . && uv run mypy` before
  calling it clean. CI (`.github/workflows/ci.yml`) runs exactly those
  three, on the single interpreter named in `.python-version`. There is no
  version matrix: `requires-python` permits newer interpreters, but 3.13 is
  the one the project stands behind on every push.
- CI runs the suite as `pytest --cov`, with the threshold in
  `[tool.coverage.report]`. It is set to where the suite stands, so it only
  ever ratchets up. Coverage is deliberately not in `addopts`: a local
  `uv run pytest` should stay fast enough to run constantly.
- Any test that opens a diary must request the `cheap_kdf` fixture
  (`pytestmark = pytest.mark.usefixtures("cheap_kdf")` at the top of the
  module). It keeps real Argon2id at test cost factors. It is not autouse
  on purpose: `tests/test_crypto.py` asserts the real OWASP parameters,
  and a blanket patch would leave that assertion passing against nothing.
- `filterwarnings = ["error"]` is set: a deprecation warning fails the
  suite rather than accumulating silently.
- CI sets `UV_LOCKED=1`, so `uv.lock` is committed and must be regenerated
  (and committed) whenever `pyproject.toml` changes. Otherwise every job
  fails on a stale lockfile.
- For `storage.py`, use `tmp_path` (pytest fixture) for all file I/O in
  tests — never touch a real `~/.zecret/` during tests.
- Textual screens can be tested with Textual's `App.run_test()` /
  `Pilot` API for basic interaction smoke tests; full UI test coverage
  is lower priority than crypto/storage correctness.

## Releasing

Zecret is on PyPI as [`zecret`](https://pypi.org/project/zecret/). A release
is a tag and nothing else: pushing `vX.Y.Z` runs
`.github/workflows/release.yml`, which publishes to PyPI and opens the
GitHub release. There is no manual upload step and no `workflow_dispatch` —
a release should be a tag in the history, not a button someone pressed.

The workflow is four jobs in sequence, each gating the next:

1. **check** — the tag must equal `pyproject.toml`'s `version`. They are
   written by different hands and nothing else compares them; PyPI would
   accept a `v0.2.0` tag carrying `0.1.0` without complaint, and the wrong
   number would be public and unrepublishable.
2. **verify** — ruff, mypy and `pytest --cov -m ""` against the *tagged*
   commit. CI covers pushes to main, but a tag can point anywhere.
3. **pypi** — `uv build`, then Trusted Publishing (OIDC). **There is no API
   token anywhere in this repo or its secrets, and there must not be.**
   `id-token: write` is granted to this job alone.
4. **github-release** — `gh release create`, with notes lifted out of
   `CHANGELOG.md`. It runs after PyPI on purpose: a release pointing at a
   version that failed to publish is worse than no release yet.

### Before tagging

- **`CHANGELOG.md` needs a section for the version.** Rename
  `[Unreleased]` to `[X.Y.Z] - YYYY-MM-DD`, leave a fresh empty
  `[Unreleased]` above it, and update the link definitions at the foot of
  the file. The `github-release` job extracts the section by heading and
  **fails the release if it finds nothing** rather than publishing empty
  notes.
- **Regenerate the screenshots.** The help popup renders
  `zecret.__version__` in its tagline, so *every version bump makes
  `assets/help-*.png` stale* — the one documentation item nothing can fail
  on. `uv run python tools/screenshots.py`; the generator is deterministic,
  so only genuinely-changed shots show up in `git status`.
- Bump `version` in `pyproject.toml` — the only place it is written — and
  re-lock, since `uv.lock` records it too.
- Let CI go green on main first.

### The parts that live outside the repo

Configured once, on PyPI and in the repository settings, and easy to
misdiagnose from the workflow logs because neither is visible here:

- **PyPI trusted publisher**: project `zecret`, owner `kfurtak1024`, repo
  `zecret`, workflow `release.yml`, environment `pypi`. Renaming the
  workflow file or the environment breaks publishing until PyPI is updated
  to match.
- **The `pypi` environment's deployment rule** must be **ref type `Tag`**,
  pattern `v*`. A *branch* rule of the same name silently permits nothing,
  and the failure lands late — after `check` and `verify` have passed — as
  a rejected deployment rather than a test failure. Do not add `main`
  here: the workflow only triggers on tags, so a branch rule would only
  ever pre-authorise a mistake.

### Irreversible

A published version number is consumed permanently. Yanking or deleting a
PyPI release does not free it for re-upload, so a bad release costs the next
patch number, not a retry. This is why `check` and `verify` run first.

## Conventions

- Type hints everywhere. `uv run mypy` enforces this; keep it green.
  Textual's `App`/`Screen` are generic, so subclasses need a parameter —
  `Screen[None]` unless the screen returns a value via `dismiss()`.
- **Locking by hand saves; the idle timer refuses.** `ctrl+l` in the
  editor calls `EditorScreen._save()` and locks only if it returned True.
  The timer does the opposite — `blocks_lock` holds it off entirely — and
  the two are not inconsistent: a keypress means someone is leaving the
  room now, so the diary must actually close, and a question left on the
  screen would keep it open behind that question. A timer has nobody to
  ask and nothing to promise, so it waits instead. Quitting takes the
  third road, `ZecretApp.action_quit`, which asks: quitting is not a claim
  about who can read this.
- **The question about unsaved writing has three answers.** `ConfirmScreen`
  dismisses a `Choice` — `CONFIRM`, `SAVE` or `CANCEL` — and grows a third
  button whenever it is given a `save_label`. Both ways of leaving a
  half-written day offer it (escape, and `ctrl+q` through the app), and
  deleting an entry does not: there is no road between going through with
  a deletion and leaving the day alone, so that question stays two-answer
  and keeps its focus on Cancel. Where saving is on offer the focus starts
  there instead — it is the answer that throws nothing away, which is the
  same rule as before and not an exception to it. `SAVE` reaches the
  editor through `ZecretScreen.save_pending()`, the counterpart of
  `blocks_lock`: a screen that says it is holding something unsaved must
  be able to write it on request. A refused save never leaves — the error
  is already on that screen's own line, and leaving would lose exactly
  what the answer was keeping.
- **Saving is not leaving.** `ctrl+s` writes the day and stays in it —
  an entry is written over an evening, and being returned to the list on
  every save meant pressing `n` and finding your place again to add the
  next line. `escape` is the only key that leaves the editor, and after a
  save it has nothing to ask about. `_save()` returns True without writing
  when nothing has changed since the last one: the key is a reflex, and a
  write per press would restamp `updated_at` on a day nobody edited and
  turn another Zecret's saving into a `ZecretConflictError` over an entry
  this session was not changing.
- **The mask is drawn, never written.** `ctrl+r` covers every word in the
  editor but the one the cursor touches. It happens in
  `DiaryTextArea.get_line`, the hook Textual's own docstring offers for
  exactly this, on the way to the screen and never in the document.
  Masking by rewriting the text would file an entry full of blocks, and it
  is the one mistake here that cannot be taken back.
  Each covered character is swapped for `BAR`, a three-quarter block: the
  same number of characters and the same number of cells, so the cursor,
  the wrapping and the selection all still land where they should, and the
  quarter-cell it leaves empty is what separates one line of redaction
  from the next. **Only single-cell characters are swapped.** A bar is one
  cell, so a two-cell character replaced by one would shorten the line and
  lose the widget's place in it; those keep their own glyph and are
  painted in ink the colour of their own background instead — which is
  why the mask's colour must still be opaque and identical for text and
  background.
  Three things paint after `get_line`: TextArea caches rendered lines
  (cleared in `watch_masked`), the cursor line's highlight (switched off
  while masked) and the selection (given a bar of its own in `app.tcss`,
  keyed on the `-masked` class). Each of them used to hand back what the
  mask had covered, back when every character was hidden by colour alone
  — `ctrl+a` laid the whole entry bare. Swapping the glyphs closed that
  for ordinary text, and the mitigations stay because the wide-character
  path still depends on colour. Anything else that draws over the editor
  has to be checked against the same three.
  The state lives on `ZecretApp.masked` so it survives opening another
  day, and is deliberately **not** in `config.py`: a diary that opened
  unreadable would be a puzzle before it was a protection. It is a screen
  someone can read over your shoulder, not a cipher -- it hides what you
  wrote earlier, since the word being typed is revealed as it is typed.
- **The editor wraps before it paints.** Textual wraps a `TextArea` when
  it handles the `Resize` message, which is queued — so the compositor has
  already drawn the widget at the new size by the time it arrives, and
  opening a long day showed one frame of unwrapped text before the wrapped
  one. `DiaryTextArea.render_lines` wraps first if the width has changed
  since it last did, which is inside the paint rather than after it. It
  tracks the width alone; everything else that changes the wrapping goes
  through TextArea's own rewrap at that same width.
- **Text-editing keys belong to the widget, not to the screen.**
  `EditorScreen.BINDINGS` holds four keys and they are all about the
  *diary* — save it, lock it, cover it, go back. Everything about the
  writing itself lives
  on `DiaryTextArea`, which is Textual's `TextArea` plus the keys it is
  missing: `ctrl+home` / `ctrl+end` for the two ends of the entry, and
  `ctrl+a` rebound from readline's "start of line" (which `home` still
  does) to select-all, where every other editor puts it. That split is
  what keeps them off the help popup and the key bar, both of which are
  generated from screen `BINDINGS` — and it is the right answer rather
  than a trick, since the popup does not list `ctrl+z`, `ctrl+k` or the
  arrow keys either, and a reader who has used an editor knows them.
  `tests/test_help_screen.py` fails if one of these keys reaches the page.
  Add the next such key to `DiaryTextArea`; add it to the screen only if
  it does something to the diary.
- `Entry` is a frozen dataclass. Edits go through `entry.edited(body)`,
  which returns a new instance; `storage.py` detects changes by comparing
  entry references across a save, so in-place mutation would break it.
  There is deliberately no way to change an entry's date: that would be a
  move, not an edit, and could collide with the day it lands on.
- `import datetime as dt` rather than `from datetime import date` —
  `Entry.date` would otherwise shadow the type it is annotated with.
- `from __future__ import annotations` at the top of every module.
- Docstrings are load-bearing documentation, not filler — update them if
  behavior diverges from what's currently written.
- Prefer raising specific exceptions (`ZecretDecryptError`, etc.) over
  generic `Exception` or silent failure.
- No print-based debugging left in committed code; Textual apps can't
  usefully print to stdout anyway while running.
- Styling lives entirely in `app.tcss`, which documents its own
  conventions at the top: theme variables only (never hard-coded colors,
  so every theme in the picker works), rules grouped by the role a widget
  plays rather than by screen, and 1 cell of vertical to 2 of horizontal
  spacing. `$error` is reserved for errors and destructive actions, and
  `.caution` — the warning shown wherever a master password is chosen — is
  the second of those rather than an exception to the first: choosing a
  password is the step that makes losing the diary possible. Do not spend
  that red on anything less final. (It is `.caution` and not `.warning`
  because Textual's own `Label` reserves that class for a variant of its
  own and paints `$warning-muted` behind it.) Text starts at the same column on every full-width screen — the
  gutter lines the *borders* up, and `Input` and `TextArea` pad their
  insides by different amounts, so lining up what is read takes a rule of
  its own; `tests/test_chrome.py` fails if the two drift apart again. The
  one break from that grouping is the `:light` section at the
  foot of the file, which exists because light and dark stack depth in
  opposite directions and no theme variable can say so — the reasoning is
  written there. Adding a card means adding it to that selector list too,
  or it will look right in dark and vanish in light. The mask's `:light`
  rule is the exception to *that*, and stays beside the rule it overrides:
  the two are a matched pair whose colours must be identical for a word to
  stay covered, so parting them by two hundred lines invites exactly the
  edit that half-lifts the bars. A `:light` override belongs at the foot
  unless it is one of a pair like that. Note also that the pseudo-class
  has to sit on the widget — a component class does not answer to
  `:light` itself, which is what makes the mask need a widget selector. Screens carry a `SUB_TITLE` so the header says where you are.
- **Notifications belong to the app, not to the screen that raised one.**
  Textual holds them for their timeout and redraws the live ones onto
  whichever screen is current, so in an app that changes screens as often
  as this one every toast flickered: it vanished with the screen it was
  raised over and reappeared on the next, out of context — "Saved." over
  the empty editor you had just opened, "Locked." over the entries you had
  just unlocked. `ZecretApp.push_screen` calls `clear_notifications()`,
  and that asymmetry is the rule: **pushing** is starting something new,
  so what was said about the last thing is finished; **popping** is the
  end of the thing being spoken about, which is how "Saved." reaches the
  list the editor returns to. Anything that pushes a screen and then
  notifies must do it in that order — see `lock()`.
- **Every screen carries a `DiaryFooter`, modals included.** A
  `ModalScreen` renders over the screen it was opened from rather than
  replacing it, so one without a footer does not show *no* bar -- it shows
  the bar underneath, whose keys are all dead while the modal has focus.
  `tests/test_chrome.py` checks that a modal advertises its own key and
  not the list's. `HelpScreen` is the exception and stays one: its box
  fills the terminal and says "esc or ? to close" in its own corner.
- **`show` is a layout decision, not a documentation one.** A binding's
  `show=True` puts it in the footer and nothing more; the help popup lists
  every binding either way (`documented_bindings()` in `screens/help.py`).
  Keeping a key out of the bar therefore costs nothing, which is what lets
  the entry list carry eight navigation bindings without a fight over
  width. Do not couple the two back together — that coupling is what made
  navigation unaddable and left `enter` documented but invisible.
- **The key bar fits 80 columns.** `DiaryFooter` (`screens/header.py`) is
  Textual's `Footer` in its compact spelling. The entry list's eight
  advertised keys take 72 of the 80 a terminal defaults to, which spends
  the room that used to be spare: the next key means either shortening a
  description ("Another day" is the long one) or dropping one to
  `show=False`, which costs only its place in the bar.
  `tests/test_chrome.py` fails when anything advertised stops fitting.
  `ctrl+l` is in the bar rather than hidden because being able to find it
  is a security property — someone stepping away who cannot see it quits,
  or leaves the diary open — which is the bar earning its width rather
  than a key winning a popularity contest.
- **Bindings are declared in reading order**, because the help popup lists
  them in that order: what you do often, then what you do rarely, then how
  you move around.
- The chrome is deliberately minimal. Textual's `Header` is not used —
  `screens/header.py` replaces it, because Textual's docks an icon that
  opens the command palette and expands when clicked. The command palette
  is off (`ENABLE_COMMAND_PALETTE = False`), which also removes `ctrl+p`
  and the footer's palette entry. Don't reintroduce either; a setting that
  belongs to the user goes on the settings screen, where it can be saved.
- **A user-facing change is not done until the documentation matches it.**
  This is a checklist, not a sentiment. Every change that alters what
  someone sees or presses goes through it *in the same commit*:
  - `README.md` — the key table, the feature list, the prose.
  - `docs/index.html` — the key table, the feature cards, "How it works".
  - `CHANGELOG.md` — under `Unreleased`, in the voice of what changed for
    the writer, not what changed in the code.
  - `assets/*.png` — **the screenshots**, if the change touches anything
    visible. Adding a keybinding changes the footer in five of them. This
    is the one that gets forgotten, because nothing fails when it is: no
    test can see that a picture is out of date. Regenerate with
    `tools/screenshots.py` (`uv run python tools/screenshots.py`).
  - `CLAUDE.md` — this file, if an interface, layer or rule moved.
  - The in-app help needs nothing: it builds itself from `BINDINGS`.
- **The product page is part of the app's surface.** `docs/index.html`
  describes the keys, the theme count, the Argon2 parameters, the default
  diary path and the Python version. Change any of those in the code and
  the page changes in the same commit — it is user-facing documentation
  that happens to live in HTML, not decoration. `tests/test_docs_page.py`
  fails if the keys, counts or parameters drift, so this is enforced
  rather than remembered; the prose around them is on you. The page also
  promises no third-party requests and no analytics, and that is tested
  too — keep it a single self-contained file.
- The help popup (`screens/help.py`) is a `ModalScreen` — Textual's
  pattern for a dialog, and what the app's other popups already are. It is
  not Textual's `HelpPanel`, which documents whichever widget has focus
  rather than the app. Its key list is generated from the screens'
  `BINDINGS`, so a new binding appears there automatically and a test
  fails if it does not. Never hand-write a key into it. It is bound to `?`
  on the entry list only, so `?` stays typeable in every text field.
- **The help popup spends width to buy height.** A section longer than
  `COLUMN_THRESHOLD` is split down the middle into two columns, read down
  and then across, and `fit_columns()` stacks them again where the terminal
  is too narrow to pair them — the same bargain `fit_logo()` already makes.
  This is what keeps the page to 30 rows rather than 47. Its full height is
  coupled to two constants that must move together: `ROWS["help"]` in
  `tools/screenshots.py` (what the picture is shot at) and `SHOT_ROWS` in
  `tests/test_help_screen.py` (which fails if the page outgrows it).
  Nothing else can see a cropped screenshot, so that test is the guard.
- The version shown in the help popup comes from `zecret.__version__`,
  which reads the installed distribution metadata. `pyproject.toml` is the
  only place the version is written; don't add a second copy.

## Explicit non-goals (do not implement unless asked)

- No cloud sync, no networking of any kind.
- No tags, mood ratings, or attachments on entries.
- No titles: the date names the entry. Adding one back would put two
  identities on a thing that only needs one.
- No more than one entry per day, and no future-dated entries.
- No multi-user support.
- No password recovery mechanism.
- No plugin system.

If a task seems to require one of these, stop and ask rather than
expanding scope.
