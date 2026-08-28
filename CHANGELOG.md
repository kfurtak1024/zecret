# Changelog

Notable changes to Zecret, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions
follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Anything that changes the on-disk format gets its own heading here, with
what it means for a diary written by an older version. Nothing else in this
file matters as much as that does.

## [Unreleased]

### Added

- **The month you are choosing from.** Pressing <kbd>a</kbd> to write about
  another day now shows that day's month under the date field, with every
  day you have already written marked — so the evenings you missed are the
  ones without a mark, which is a question no date field could answer. The
  field still has the cursor and still takes a typed date, so knowing the
  date is no slower than it was; <kbd>tab</kbd> or <kbd>&darr;</kbd> steps
  into the month, where the arrow keys walk a day at a time, the page keys
  move a month, <kbd>home</kbd> and <kbd>end</kbd> reach its ends, and
  <kbd>enter</kbd> takes the day the cursor is on. The calendar follows
  the typing as it happens — the month appears at the keystroke that names
  it, and the day as the day goes in — and moving the calendar writes the
  date back into the field. Days that have not happened are
  greyed and the cursor will not go there, which is the same rule the
  screen already applied to a typed date.

### Changed

- **Choosing a master password says what it costs to forget it.** The
  screen that creates a diary now carries the warning in red rather than in
  the grey the rest of the hints are written in: forget it and the diary is
  gone, with no recovery and no back door. It was already said there, and
  read like small print.

- **Changing the master password is its own dialog.** Settings now offers a
  button, and the three password fields have moved behind it, where the
  same warning is the first thing on the screen rather than the last line
  of a form you had scrolled to the bottom of. It is the only thing in
  Zecret that cannot be undone, and it was previously something you could
  tab into by accident on the way past two dropdowns. Nothing about the
  change itself is different: your current password is still checked before
  anything happens, and a change that fails to save still leaves the diary
  openable by the password you already had. Settings is a shorter screen
  for it, too.

### Fixed

- **A long day no longer flinches when you open it.** An entry appeared for
  a moment with its paragraphs running off the right-hand edge and then
  redrew itself wrapped, which read as the text being replaced by different
  text. The wrapping now happens before the first frame is drawn rather
  than a frame after it.

## [0.4.0] - 2026-08-27

### Added

- **Cover the page while you write.** <kbd>ctrl</kbd>+<kbd>r</kbd> puts
  every word in the entry behind a bar except the one your cursor is
  touching, the way a declassified document arrives. It is for writing
  somewhere with a seat behind you: the bars stay until you press it
  again, and they follow you from one day to the next rather than lifting
  every time you open an entry. What it hides is what you have already
  written — the word you are typing is revealed as you type it — and it is
  not a substitute for locking, since the bars are on the screen rather
  than on the diary. The writing underneath is untouched, so what you save
  is what you wrote.

- **The editor's missing text keys.** <kbd>ctrl</kbd>+<kbd>home</kbd> goes
  to the start of the entry you are writing and
  <kbd>ctrl</kbd>+<kbd>end</kbd> to the end of it; the editor had
  <kbd>home</kbd> and <kbd>end</kbd> for the line you were on and the page
  keys for a screenful, but nothing for the text itself, so the top of a
  day written at length was a long way from its bottom.
  <kbd>ctrl</kbd>+<kbd>a</kbd> now selects the whole entry rather than
  jumping to the start of the line, which is what <kbd>home</kbd> is for.
  None of the three appear under <kbd>?</kbd>: that page is about the
  diary, and these do here what they do in every other editor.

- **Leaving a half-written day offers to save it.** Both
  <kbd>esc</kbd> and <kbd>ctrl</kbd>+<kbd>q</kbd> stopped to ask before
  throwing unsaved writing away, but the only answers were to lose it or
  to stay where you were — so the safe reply to a question about your own
  writing was "no". Each now has a third: **Save and go back**, or **Save
  and quit**, and that is the button a stray <kbd>enter</kbd> lands on. A
  save that cannot happen keeps you in the day with the reason rather than
  leaving on the strength of it. Deleting an entry still asks the plain
  two-answer question — there is nothing to save there.

### Changed

- **<kbd>ctrl</kbd>+<kbd>s</kbd> no longer closes the day.** It writes what
  you have and hands the cursor straight back, where before it filed the
  entry and returned you to the list — so saving part-way through an
  evening meant pressing <kbd>n</kbd> and finding your place again to add
  the next line, and the safe habit cost more than not having it.
  <kbd>esc</kbd> is what goes back, and it no longer asks anything once you
  have saved. Pressing <kbd>ctrl</kbd>+<kbd>s</kbd> on a day you have not
  touched since the last save does nothing at all rather than rewriting it.

## [0.3.0] - 2026-08-20

### Added

- **Lock is <kbd>ctrl</kbd>+<kbd>l</kbd> now, and it is in the key bar.**
  Locking used to be <kbd>L</kbd>, listed only under <kbd>?</kbd> and
  working only on the entry list — but someone getting up from the desk is
  not the person who stops to read the help page first, and a bare letter
  cannot be pressed while there is text to type into. The chord is what a
  password manager locks with, it sits between Settings and Help at the
  bottom of the list, and it works while you are writing.
- **Saving says so.** <kbd>ctrl</kbd>+<kbd>s</kbd> returns you to the
  list, where a day you have just revised looks exactly as it did before —
  so nothing on the screen told you the save had happened rather than, say,
  a stray <kbd>esc</kbd> having thrown it away. It now says "Saved." on the
  way back, the way locking already said "Locked."
- **Locking while writing saves the day first.** Press it mid-entry and
  Zecret files what you have written, then asks for your password again.
  The alternative was a question left on the screen with the diary open
  behind it, which is the opposite of what the key is for. An untouched
  day just locks; one that cannot be saved keeps you where you are with
  the reason.

### Fixed

- **Messages no longer flash back up on the next screen.** "Saved." and
  "Locked." outlived the screens they were said on: each went away as that
  screen was left, then reappeared seconds later somewhere it made no
  sense — "Locked." over the entries you had just unlocked, "Saved." over
  the empty day you had just opened to write something else. A message now
  ends when you start the next thing, and only follows you back to where
  you came from.
- **The search box lines up with its results.** It sat one cell to the
  right of the days listed underneath it, and of the editor on the next
  screen over — a text field pads its inside by more than a text area
  does, so bordering them at the same place was not enough to line up what
  you read.
- **The key bar tells the truth while a question is on screen.** Asking
  which day to write about, or whether to delete an entry, left the entry
  list's bar showing underneath — eight keys, none of which did anything
  until the question was answered, and no sign of the <kbd>esc</kbd> that
  did. Both now carry their own bar saying so.
- **The light themes no longer read as one flat sheet of grey.** Zecret
  drew every card as a lift off the page behind it, which is how depth
  works on a dark background and not at all how it works on a pale one —
  so on Light, Solarized Light and Catppuccin Latte the cards dissolved
  into the page, the title bar stopped looking like a bar, and the editor
  came out as a wash of grey with a floating orange rectangle in it. Light
  themes now put paper on a desk: the page you write on is lighter than
  what surrounds it, the bars are darker, and the selected day is the calm
  blue the rest of the app already selects things with instead of a
  fluorescent orange stripe. Each theme keeps its own colour — Solarized
  is still cream, Latte is still cool. The dark themes are untouched.
- **Quitting no longer throws away a half-written entry.** Backing out of
  the editor has always asked before discarding unsaved text, and the idle
  timer has always refused to lock over it — but <kbd>ctrl</kbd>+<kbd>q</kbd>
  went straight out, taking the entry with it. It now asks the same
  question, and cancelling leaves you where you were with your text intact.
  Nothing changes when there is nothing unsaved: <kbd>q</kbd> from the
  entry list still just quits.

## [0.2.0] - 2026-08-19

### Added

- **`zecret --version`**, which answers what you are running without asking
  for your password. The version was already in the help popup, but that is
  on the other side of the unlock screen — an odd place to keep the one
  fact a bug report needs.
- **`zecret --help` now names `ZECRET_DIARY_PATH` and
  `ZECRET_CONFIG_PATH`.** Both have existed for a while and neither
  appeared anywhere the command itself would tell you about, which made
  them documentation you had to already know to look for.
- **Preferences can live somewhere else too.** `--config /some/where.json`,
  or `ZECRET_CONFIG_PATH`, points one run at a different settings file. The
  default has not moved and neither has the rule behind it: your settings
  belong to you rather than to a file, so a diary opened with `--path`
  still uses your theme. This is for when that is the wrong answer —
  running a build of Zecret you are working on, where changing the theme to
  see what it looks like should not change the one you write in.

### Changed

- **A wide window now shows more of each day.** Rows in the diary list and
  in search used to stop after sixty characters however much room there
  was, leaving most of a wide terminal empty beside a cut-off sentence.
  They now carry the whole of the entry's first line and show as much of it
  as fits, trimming with an ellipsis only where the window really runs out.
  Resizing costs nothing: the trimming happens as the row is drawn.
- **The help popup is wider, and most of it now fits on screen at once.**
  The keys sit in two columns instead of one long list, which takes the
  page from 47 rows to 30 — on an 80×25 terminal every key of the diary is
  visible without scrolling, where before you scrolled to reach half of
  them. A terminal too narrow to hold two columns stacks them back into
  one rather than squeezing the descriptions.
- The source distribution no longer ships `tools/`. Nothing installs or
  runs differently — the wheel never contained it, and the test suite the
  sdist carries does not depend on it. What an sdist is for is rebuilding
  and verifying the package; the screenshot and dev-diary generators are
  for working on it from a git checkout, which is where they now stay.

### Fixed

- `ZECRET_DIARY_PATH` set to an empty string is now treated as unset rather
  than as the current directory.

## [0.1.0] - 2026-08-17

The first release. What follows is what Zecret does on its first day rather
than a list of changes from something earlier: the entries that tracked its
development described a program nobody outside had run, so they have been
folded into this one and left in the git history, where they belong.

A `0.x` version on purpose. The program is finished and tested, but no one
has yet kept a diary in it for a year, and the keys and the command line
should stay free to move until someone has. The **file format is a
different promise, and it is already made**: it is version 1, and a diary
written today will be readable by every later Zecret or migrated by one.

### Added

- **A diary of days.** One entry per calendar day, and the date is the
  entry's whole identity — no titles, no ids, nothing to name or file.
  Opening a day means writing it or continuing what is already there. The
  day is the local one, so something written at 23:50 belongs to the day
  you would call it.
- **A master password and nothing else.** Argon2id derives the key
  (time_cost 3, 64 MiB, 4 lanes) and every entry is sealed on its own with
  AES-256-GCM. Editing one day never re-encrypts another. A wrong password
  or an altered file fails loudly rather than returning nonsense — and
  there is no recovery, by design. Nobody, including you, opens the file
  without the password.
- **The diary locks itself.** After fifteen minutes without a keystroke
  Zecret forgets the diary and the key and asks for the password again;
  `L` does it on demand. A half-written entry holds the lock off rather
  than being discarded by a timer, and the wait is configurable, including
  turning it off.
- **Search across every entry**, filtering as you type, with no separate
  step to submit.
- **An entry list that stays usable at years of writing.** Days are grouped
  under month headings, newest first; `j`/`k` move a day, `g`/`G` and
  `home`/`end` jump to the newest and oldest, and the page keys move a
  screenful.
- **Every key documented in the app.** `?` lists all of them, generated
  from the bindings themselves, so the popup cannot fall out of step with
  what the program actually does. The footer shows the seven that fit an
  80-column terminal; the rest are a keypress away.
- **Themes**, chosen in settings and remembered between runs in
  `~/.zecret/config.json` — the one file Zecret writes in the clear, and it
  holds preferences and nothing else. No entry text, no dates, nothing
  derived from your key.
- **Writes that do not lose a diary.** Saves go to a temporary file in the
  same directory, are fsynced, and replace the real one in a single
  indivisible step. A second Zecret writing the same file is detected and
  refused rather than silently overwritten, and `r` re-reads without asking
  for the password again. Creating a diary claims the path in the same step
  that writes it, so two first runs cannot race.
- **A diary anywhere you like.** `~/.zecret/diary.enc` by default,
  `--path` or `ZECRET_DIARY_PATH` for somewhere else — separate diaries, or
  a throwaway one to try it with.

### Security

- The threat model, what counts as a vulnerability, and how to report one
  privately are written down in [SECURITY.md](SECURITY.md), along with the
  properties that are known and accepted rather than bugs. Chief among
  them: the file reveals *which days* have entries, though not a word of
  what they say.

[Unreleased]: https://github.com/kfurtak1024/zecret/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/kfurtak1024/zecret/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/kfurtak1024/zecret/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/kfurtak1024/zecret/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/kfurtak1024/zecret/releases/tag/v0.1.0
