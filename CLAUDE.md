# CLAUDE.md — Zecret

This file guides Claude Code when working in this repository. Read it in
full before implementing anything.

## What this project is

Zecret is an encrypted terminal diary. A single user, locally, protects
their diary entries with a master password. The app is a Textual-based TUI
— no web server, no sync, no multi-user concerns.

The repository is currently **scaffolded but not implemented**: module
files exist with docstrings, type signatures, and `raise
NotImplementedError` bodies. Your job is to fill them in, in the order
described below, without changing the public interfaces unless you find a
concrete reason to (if you do, update this file to match).

## Tech stack (fixed — do not substitute)

- Python 3.11+, managed with `uv` (`uv sync`, `uv run`, `uv add <pkg>`).
  Development targets the latest CPython, pinned in `.python-version`.
- **Textual** for the TUI — use widgets/screens/CSS idiomatically; don't
  hand-roll ANSI escape codes or use `curses` directly
- **argon2-cffi** for key derivation (Argon2id specifically, not Argon2i/d)
- **cryptography** for AEAD encryption
- **pytest** (+ `pytest-asyncio` for Textual screen tests) for testing
- **ruff** for linting and formatting (`uv run ruff check .`,
  `uv run ruff format .`) — config lives in `pyproject.toml`
- **mypy** in strict mode over `src/` (`uv run mypy`), checked against the
  3.11 floor rather than the newest interpreter

Dependency floors track current releases rather than the oldest version
that happens to work; `cryptography` in particular should not be allowed to
drift onto an unpatched release. Dev-only tools live in the PEP 735
`[dependency-groups]` table, which `uv sync` installs by default — so a
bare checkout can run `uv run pytest` with no extra flags.

## Architecture

```
src/zecret/
├── crypto.py     # KDF (Argon2id) + AEAD encrypt/decrypt. No file I/O, no entry semantics.
├── models.py     # Entry dataclass + JSON (de)serialization. No crypto, no file I/O.
├── storage.py    # DiaryFile: owns the on-disk format, atomic writes, ties crypto+models together.
├── app.py        # ZecretApp (Textual App subclass): screen routing, holds session state.
├── screens/      # One file per screen: unlock, entry_list, editor, search, settings.
│                 # Plus two shared helpers: base.py (ZecretScreen, typed
│                 # access to the app) and confirm.py (yes/no modal).
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
6. **Per-entry independent encryption.** Editing or deleting one entry
   must never require decrypting or re-encrypting any other entry's
   ciphertext. This is what the storage tests check for explicitly.
7. **Fail closed.** Any decryption failure surfaces as
   `ZecretDecryptError` and is caught at the UI layer to show "incorrect
   password" — never swallowed, never defaults to an empty diary.

## File format

See the module docstring in `storage.py` for the authoritative JSON shape.
Treat `version: 1` in the header as load-bearing — if you ever need to
change the format, add a migration path keyed off that field rather than
breaking old files.

## Build order

Implement in this order; each step should be fully tested before moving on.

1. **`crypto.py`** — KDF + AEAD. This is the foundation; get it right and
   well-tested first. Run `uv add cryptography argon2-cffi` if not already
   present.
2. **`models.py`** — `Entry` dataclass, JSON (de)serialization.
3. **`storage.py`** — `DiaryFile`: create/unlock/save/add/update/delete/
   change_password, atomic writes. This is the module most worth
   over-testing (see `tests/test_storage.py` for required coverage).
4. **`app.py` + `screens/unlock.py`** — get a working unlock/create-diary
   flow end to end before building out the rest of the UI.
5. **`screens/entry_list.py`** — list + navigation.
6. **`screens/editor.py`** — create/edit flow, wired to the list.
7. **`screens/search.py`** — live in-memory filter.
8. **`screens/settings.py`** — password change flow.
9. **`app.tcss`** — polish the visual design once functionality is complete.

Don't jump ahead to UI polish before `crypto.py` and `storage.py` are
solid and tested — bugs there are the ones that actually matter.

## Testing

- Every module's test file already lists required coverage in its
  docstring (`tests/test_crypto.py`, `tests/test_storage.py`,
  `tests/test_models.py`) — treat those lists as a checklist, not a
  suggestion.
- Run `uv run pytest` before considering any module done, and
  `uv run ruff check . && uv run ruff format . && uv run mypy` before
  calling it clean. CI (`.github/workflows/ci.yml`) runs exactly those
  three, plus the test suite on every Python from 3.11 to 3.14 — so a
  change that only works on the newest interpreter fails there, not here.
- CI installs with `uv sync --locked`, so `uv.lock` is committed and must
  be regenerated (and committed) whenever `pyproject.toml` changes.
  Otherwise every job fails on a stale lockfile.
  `filterwarnings = ["error"]` is set: a deprecation warning fails the
  suite rather than accumulating silently.
- For `storage.py`, use `tmp_path` (pytest fixture) for all file I/O in
  tests — never touch a real `~/.zecret/` during tests.
- Textual screens can be tested with Textual's `App.run_test()` /
  `Pilot` API for basic interaction smoke tests; full UI test coverage
  is lower priority than crypto/storage correctness.

## Conventions

- Type hints everywhere (already present in stubs — keep them accurate
  as you implement). `uv run mypy` enforces this; keep it green. Textual's
  `App`/`Screen` are generic, so subclasses need a parameter —
  `Screen[None]` unless the screen returns a value via `dismiss()`.
- `Entry` is a frozen dataclass. Edits go through `entry.edited(...)`,
  which returns a new instance; `storage.py` detects changes by comparing
  entry references across a save, so in-place mutation would break it.
- `from __future__ import annotations` at the top of every module
  (already present).
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
- No multi-user support.
- No password recovery mechanism.
- No plugin system.

If a task seems to require one of these, stop and ask rather than
expanding scope.
