# Changelog

Notable changes to Zecret, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Anything that changes the on-disk format gets its own heading here, with
what it means for a diary written by an older version. Nothing else in this
file matters as much as that does.

## [Unreleased]

### Changed — file format

- **The diary format is version 1, and that number is now fixed.** It was
  numbered 2 for historical reasons that never reached anyone, so it has
  been reset while no diary in the world depended on it. The shape of the
  file is unchanged — only the `version` field in the header differs.
  From here the number is a promise: the next format change bumps it and
  ships a migration.
- A diary written by an earlier build carries `"version": 2` and will be
  refused with "incorrect password" (the unlock screen reports an
  unreadable file and a wrong password identically, on purpose). If you
  have one, change that single number to `1` in the file's JSON header —
  nothing else about it needs to move, and the ciphertext is untouched.

### Changed — keys

- **The entry list can be navigated.** <kbd>j</kbd>/<kbd>k</kbd> move a day,
  `g`/`G` and `home`/`end` jump to the newest and oldest entries, and the
  page keys move a screenful. Before this the arrow keys were the only way
  through, so the far end of a year of writing was three hundred presses
  away.
- `g` now means "newest entry", so **writing about another day moved from
  `g` to `a`**, and **locking moved from `l` to `L`** to leave `l` clear of
  the `hjkl` cluster.
- The footer shows seven keys instead of nine; Open, Reload and Lock are
  still there, just found through `?` rather than crowding a bar that only
  holds eighty columns. The help popup now lists *every* binding rather
  than only the ones the footer had room for — which is the only place the
  navigation keys are named.

### Added

- The diary locks itself. After fifteen minutes without a keystroke Zecret
  forgets the diary and the key and asks for the password again; `L` does
  it on demand. A half-written entry holds the lock off rather than being
  discarded by a timer, and the wait is configurable in settings, including
  turning it off.
- `r` on the entry list re-reads the file. A second Zecret writing to the
  same diary used to leave this one refusing every save until it was quit
  and reopened; now there is a way back that does not need the password
  retyped.
- A security policy ([SECURITY.md](SECURITY.md)): how to report a
  vulnerability privately, what counts as one, and the list of properties
  that are known and accepted rather than bugs.

### Fixed

- A long diary is usable again. Both list screens mounted their rows one at
  a time, which re-laid-out every row already placed — quadratic, and paid
  on every return to the screen. Ten years of entries took over a minute to
  draw; it now takes a few seconds.
- Reading no longer costs you your place. Returning from an entry, or
  deleting one, sent the cursor back to the newest day. It now stays on the
  day it was on, or — when that day was the one just deleted — on the next
  older day, which has moved up into its place.
- Creating a diary can no longer overwrite one. The check for an existing
  file and the write were separate steps with a key derivation between
  them, so two Zecrets started with no diary could both pass the check and
  the second would replace the first. Creation now claims the path in the
  same indivisible step that writes it.
- An entry of nothing but spaces and newlines is refused, the same as an
  empty one. It was accepted, and then listed as `(empty)`.

### Changed

- **Zecret runs on Python 3.13.** The floor was 3.14, which is newer than
  the Python most systems ship — so installing with `pip` or `pipx` failed
  outright for anyone who had not gone and fetched one. It needs 3.13 or
  newer now. Nothing about the app or the diary format changed; if you
  install with `uv`, which fetches its own interpreter, you will not notice
  a difference.
- The key bar is compact, so all of it fits an 80-column terminal. Adding
  Reload and Lock had pushed it to 102 columns, where it stopped mid-word
  at "? Hel" and dropped Quit entirely. A test now fails if any advertised
  key stops fitting.
- The screenshots are generated rather than taken by hand:
  `uv run python tools/screenshots.py` rebuilds all ten from the real app.
  They had gone stale, showing a footer two keybindings out of date, and
  nothing could fail to tell anyone.
- The scale tests are excluded from a plain `uv run pytest` and selected
  back by CI, so the edit-run loop stays quick.
- The file format's parsers are covered by property-based tests
  (Hypothesis) as well as by examples, so a diary file this program did not
  write fails as a readable error rather than a traceback.

[Unreleased]: https://github.com/kfurtak1024/zecret/commits/main
