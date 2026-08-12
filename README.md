# Zecret

A modern, encrypted terminal diary.

Zecret keeps your diary in a single encrypted file on disk. Every entry is
encrypted independently under a key derived from your master password
(Argon2id), and the app itself is a fast, keyboard-driven Textual TUI.

## Status

Complete. Creating and unlocking a diary, listing, writing, editing,
deleting, searching, and changing your master password all work, and the
interface follows your terminal's light or dark theme.

## Quick start

```bash
uv sync
uv run zecret
```

By default your diary lives at `~/.zecret/diary.enc`. Override with
`--path` or the `ZECRET_DIARY_PATH` environment variable.

### Keys

| Key       | Where       | Does                                  |
| --------- | ----------- | ------------------------------------- |
| `n`       | entry list  | Write a new entry                     |
| `enter`   | entry list  | Open the selected entry               |
| `d`       | entry list  | Delete the selected entry (asks first)|
| `/`       | entry list  | Search                                |
| `s`       | entry list  | Change your master password           |
| `q`       | entry list  | Quit                                  |
| `ctrl+s`  | editor      | Save and return                       |
| `esc`     | anywhere    | Back (asks first if you have edits)   |

## Development

```bash
uv sync          # installs the dev tools too (PEP 735 dependency group)
uv run pytest
uv run ruff check . && uv run ruff format .
uv run mypy
```

CI runs the same three checks on every push and pull request, and the test
suite on Python 3.11 through 3.14. Because CI installs with
`uv sync --locked`, `uv.lock` is committed — regenerate and commit it
whenever you change `pyproject.toml`.

## Security notes

- Your master password is never stored — only an Argon2id-derived key,
  which itself never touches disk.
- Losing your password means losing access to your diary. There is no
  recovery mechanism by design.
- Plaintext entries are never written to disk; only ciphertext.

### How it works

- **Key derivation:** Argon2id (`time_cost=3`, `memory_cost=64 MiB`,
  `parallelism=4`), with a random 16-byte salt generated per diary and
  stored in the file header.
- **Encryption:** AES-256-GCM, with a fresh random nonce for every
  encryption. Each entry is encrypted independently, so editing one entry
  never re-encrypts the others.
- **Integrity:** any tampering with a stored entry — or a wrong password —
  fails the AEAD authentication check and is reported as an error, never
  as an empty or partial diary. The header carries an encrypted verifier so
  this holds even for a diary with no entries yet.
- **Durability:** saves are atomic (temp file → `fsync` → `os.replace`), so
  an interrupted write can never leave a half-written diary. The file is
  created `0600`.
