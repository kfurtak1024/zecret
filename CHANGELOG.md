# Changelog

Notable changes to Zecret, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Anything that changes the on-disk format gets its own heading here, with
what it means for a diary written by an older version. Nothing else in this
file matters as much as that does.

## [Unreleased]

### Added

- The diary locks itself. After fifteen minutes without a keystroke Zecret
  forgets the diary and the key and asks for the password again; `l` does
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

- The scale tests are excluded from a plain `uv run pytest` and selected
  back by CI, so the edit-run loop stays quick.
- The file format's parsers are covered by property-based tests
  (Hypothesis) as well as by examples, so a diary file this program did not
  write fails as a readable error rather than a traceback.

[Unreleased]: https://github.com/kfurtak1024/zecret/commits/main
