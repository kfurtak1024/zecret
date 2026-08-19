<div align="center">

# Zecret

**A modern, encrypted terminal diary.**

One entry a day, in your terminal, kept in a single encrypted file that only
you can open.

[**zecret.krfu.dev**](https://zecret.krfu.dev) · [Install](#install) · [How it works](#how-it-works)

[![CI](https://github.com/kfurtak1024/zecret/actions/workflows/ci.yml/badge.svg)](https://github.com/kfurtak1024/zecret/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/zecret?logo=pypi&logoColor=white)](https://pypi.org/project/zecret/)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue?logo=python&logoColor=white)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Built with Textual](https://img.shields.io/badge/built%20with-Textual-5a4fcf)](https://textual.textualize.io)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://img.shields.io/badge/mypy-checked-2a6db2)](https://mypy-lang.org)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/kfurtak1024/zecret/main/assets/entries-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/kfurtak1024/zecret/main/assets/entries-light.png">
  <img alt="The Zecret entry list, showing days of diary entries grouped under month headings, most recent first" src="https://raw.githubusercontent.com/kfurtak1024/zecret/main/assets/entries-dark.png" width="820">
</picture>

</div>

---

## Why

A diary should be private by construction, not by promise. Zecret has no
server, no account, no sync and no telemetry — there is nowhere for your
writing to go. It is one encrypted file on your own disk, opened by a
password only you know, in a terminal you already have open.

- 📅 **One entry a day** — each day is a page, named by its date; come back and it is the same page
- 🗓️ **Grouped by month** — the diary reads as months, each headed with how much of it you wrote
- 🔐 **Encrypted at rest** — Argon2id key derivation, AES-256-GCM per entry
- ✍️ **Keyboard-driven** — a fast Textual TUI, no mouse required
- 🔎 **Instant search** — live filtering across everything you have written
- 📄 **One portable file** — back it up by copying it; it is useless without your password
- 🌗 **Light and dark** — eight themes, picked in settings and remembered
- 🔒 **Locks itself** — walks away when you do, and asks for your password again
- 🚫 **Offline by design** — no networking of any kind

## Install

```bash
uv tool install zecret
zecret
```

That is the whole of it: [uv](https://github.com/astral-sh/uv) fetches a
suitable Python along with the program, so nothing depends on what your
system happens to ship. If you would rather use what you already have,
`pipx install zecret` and `pip install zecret` both work on Python 3.13 or
newer.

Your diary lives at `~/.zecret/diary.enc` by default. Point somewhere else
with `--path /some/where.enc` or the `ZECRET_DIARY_PATH` environment
variable — handy for keeping separate diaries, or trying it out without
touching your real one.

Your settings follow you rather than the file, so a diary opened with
`--path` still uses your theme. If you would rather it did not — running a
build you are working on, say — `--config /some/where.json` or
`ZECRET_CONFIG_PATH` gives that run preferences of its own.

`zecret --help` lists both flags and both environment variables, and
`zecret --version` says which Zecret you have without opening the diary.

On first launch there is no diary yet, so Zecret asks you to choose a
master password and creates one. Every launch after that asks for that
password to unlock it.

> [!WARNING]
> There is no password recovery, by design. Nobody — including you — can
> open the file without the password. Choose something you will not lose.

## Using it

<div align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/kfurtak1024/zecret/main/assets/editor-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/kfurtak1024/zecret/main/assets/editor-light.png">
  <img alt="Writing a day's entry: the date in the header above a full-height text area" src="https://raw.githubusercontent.com/kfurtak1024/zecret/main/assets/editor-dark.png" width="760">
</picture>
</div>

Press <kbd>n</kbd> to write about today, <kbd>ctrl</kbd>+<kbd>s</kbd> to
save. A day holds one entry, so pressing <kbd>n</kbd> again later opens what
you already wrote rather than starting a second page — the evening simply
continues the morning. Every save re-writes the diary file atomically, so
there is no draft state to lose track of.

<div align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/kfurtak1024/zecret/main/assets/date-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/kfurtak1024/zecret/main/assets/date-light.png">
  <img alt="A modal asking which day to write about, prefilled with a date" src="https://raw.githubusercontent.com/kfurtak1024/zecret/main/assets/date-dark.png" width="760">
</picture>
</div>

Missed a day? Press <kbd>a</kbd> and type the date. Anything up to today is
fair game; days that have not happened yet are refused.

<div align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/kfurtak1024/zecret/main/assets/search-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/kfurtak1024/zecret/main/assets/search-light.png">
  <img alt="Search filtering entries live as you type" src="https://raw.githubusercontent.com/kfurtak1024/zecret/main/assets/search-dark.png" width="760">
</picture>
</div>

Press <kbd>/</kbd> to search. Your entries are already decrypted in memory
for the session, so filtering is instant and nothing touches the disk.

<div align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/kfurtak1024/zecret/main/assets/help-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/kfurtak1024/zecret/main/assets/help-light.png">
  <img alt="The help popup over the diary, listing every key by section" src="https://raw.githubusercontent.com/kfurtak1024/zecret/main/assets/help-dark.png" width="760">
</picture>
</div>

Press <kbd>?</kbd> for every key in one popup, and <kbd>s</kbd> for settings
— where you pick a theme, choose how long the diary waits before locking
itself, and change your master password. Those preferences are kept in
`~/.zecret/config.json`, the one file Zecret writes unencrypted; it holds
your settings and nothing about what you wrote.

Zecret locks itself after fifteen minutes without a keystroke, and asks for
your password again — press <kbd>L</kbd> to do it yourself on the way out
of the room. A half-written entry holds the lock off rather than being
thrown away by a timer. Change the wait, or turn it off, in settings.

### Keys

| Key | Where | Does |
| --- | --- | --- |
| <kbd>n</kbd> | entry list | Write about today |
| <kbd>a</kbd> | entry list | Write about another day (asks which) |
| <kbd>enter</kbd> | entry list | Open the selected day |
| <kbd>d</kbd> | entry list | Delete the selected day's entry (asks first) |
| <kbd>r</kbd> | entry list | Re-read the file, picking up another Zecret's writing |
| <kbd>/</kbd> | entry list | Search |
| <kbd>s</kbd> | entry list | Settings: theme, locking, master password |
| <kbd>L</kbd> | entry list | Lock the diary without quitting |
| <kbd>?</kbd> | entry list | Help — every key, on one page |
| <kbd>q</kbd> | entry list | Quit |
| <kbd>ctrl</kbd>+<kbd>s</kbd> | editor | Save and return |
| <kbd>esc</kbd> | anywhere | Back (asks first if you have unsaved edits) |

Getting around a long diary: <kbd>j</kbd>/<kbd>k</kbd> or the arrow keys move
a day at a time, <kbd>g</kbd>/<kbd>G</kbd> (or <kbd>home</kbd>/<kbd>end</kbd>)
jump to the newest and oldest entries, and <kbd>PgUp</kbd>/<kbd>PgDn</kbd>
move a screenful. These stay out of the bar at the bottom, which only has
room for so much — <kbd>?</kbd> lists everything.

## How it works

- **Key derivation** — Argon2id (`time_cost=3`, `memory_cost=64 MiB`,
  `parallelism=4`, roughly OWASP interactive settings), with a random
  16-byte salt generated per diary and stored in the file header. Your
  password is never stored; the derived key never touches disk.
- **Encryption** — AES-256-GCM with a fresh random nonce for every
  encryption. Each day's entry is encrypted independently, so editing one
  day never re-encrypts the others. Only the dates are visible in the file;
  every word you write is inside the ciphertext.
- **Integrity** — tampering with a stored entry, or a wrong password, fails
  the AEAD authentication check and is reported as an error, never as an
  empty or partial diary. The header carries an encrypted verifier, so this
  holds even for a diary with no entries yet.
- **Durability** — saves are atomic (temp file → `fsync` → `os.replace`),
  so an interrupted save can never leave a half-written diary. Creating a
  diary instead claims the path with `O_EXCL`, so two first runs racing each
  other cannot end with one written over the other; a creation that fails
  removes what it started. The file is created `0600`.

Plaintext is never written to disk — not as temp files, not as logs, not
for crash recovery.

## Development

```bash
git clone https://github.com/kfurtak1024/zecret.git
cd zecret
uv sync            # dev tools included (PEP 735 dependency group)
./zecret-dev.sh    # run it against a throwaway diary
uv run pytest
uv run ruff check . && uv run ruff format .
uv run mypy
```

Note `./zecret-dev.sh` rather than `uv run zecret`. Running the app from a
checkout opens **your own diary** with whatever code is currently checked
out, which is not what you want a half-finished change doing. The script
points the app at `.zecret-dev/` instead — gitignored, throwaway, and
seeded on first run with a few hundred generated days so there is enough in
it to see a layout problem. The password is `dev`. Delete the directory
whenever you like; the next run rebuilds it.

It overrides the preferences file as well as the diary, which matters more
than it sounds: without that, trying themes out in a development build
changes the theme in the one you write in.

```bash
uv run python tools/seed_dev_diary.py --help    # different data, same guardrails
```

The screenshots above are generated, not taken by hand — regenerate them
after any change that alters what a screen looks like:

```bash
uv run python tools/screenshots.py    # needs librsvg or inkscape
```

CI runs those same checks on every push and pull request. `uv.lock` is
committed and CI installs from it, so regenerate and commit it whenever
`pyproject.toml` changes.

## License

MIT © Krzysztof Furtak — see [LICENSE](LICENSE).
