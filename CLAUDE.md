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

- Python 3.14, managed with `uv` (`uv sync`, `uv run`, `uv add <pkg>`) and
  pinned in `.python-version`. Zecret is an application, not a library, so
  it targets exactly one interpreter rather than a support range: uv
  provisions it, so nothing depends on what a user's system ships.
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
├── app.py        # ZecretApp (Textual App subclass): screen routing, holds session state.
├── screens/      # One file per screen: unlock, entry_list, editor, search, settings.
│                 # Plus three shared helpers: base.py (ZecretScreen, typed
│                 # access to the app, and the date/snippet formatting every
│                 # screen shares), confirm.py (yes/no modal) and
│                 # date_prompt.py (which-day modal).
└── __main__.py   # CLI entry point (`zecret` command): arg parsing, launches ZecretApp.
```

Keep this layering strict:
- `crypto.py` knows nothing about entries or files — just bytes in, bytes out.
- `models.py` knows nothing about encryption or file paths.
- `storage.py` is the only place that touches the filesystem or combines
  crypto + models.
- `screens/*.py` never call `crypto.py` or the filesystem directly — they
  only go through `app.diary` (a `DiaryFile`) and `app.key`. Where a screen
  needs something crypto-shaped, storage grows the method: this is why
  `DiaryFile.verify_password()` exists, for the settings screen's re-check
  of the current password.

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
   Never write directly to the live diary file in place.
6. **Per-entry independent encryption.** Editing or deleting one day's
   entry must never require decrypting or re-encrypting any other entry's
   ciphertext. This is what the storage tests check for explicitly.
7. **Fail closed.** Any decryption failure surfaces as
   `ZecretDecryptError` and is caught at the UI layer to show "incorrect
   password" — never swallowed, never defaults to an empty diary.

## File format

See the module docstring in `storage.py` for the authoritative JSON shape.
Treat `version: 2` in the header as load-bearing — if you ever need to
change the format, add a migration path keyed off that field rather than
breaking old files. Version 1 (UUID-keyed entries with titles) predates
the one-entry-per-day model and is refused outright rather than migrated;
that was a deliberate call taken while no real diary used it, and it is not
a precedent for the next change.

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

## Testing

- Every test file lists its required coverage in its docstring — treat
  those lists as a checklist, not a suggestion, and extend the list when
  you add behavior worth guarding.
- Run `uv run pytest` before considering any module done, and
  `uv run ruff check . && uv run ruff format . && uv run mypy` before
  calling it clean. CI (`.github/workflows/ci.yml`) runs exactly those
  three, on the single interpreter named in `.python-version`.
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

## Conventions

- Type hints everywhere. `uv run mypy` enforces this; keep it green.
  Textual's `App`/`Screen` are generic, so subclasses need a parameter —
  `Screen[None]` unless the screen returns a value via `dismiss()`.
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
  so light and dark both work), rules grouped by the role a widget plays
  rather than by screen, and 1 cell of vertical to 2 of horizontal
  spacing. Screens carry a `SUB_TITLE` so the header says where you are.

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
