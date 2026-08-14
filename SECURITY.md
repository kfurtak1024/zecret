# Security policy

Zecret's whole purpose is to keep a diary readable only by the person who
wrote it, so a flaw in that is worth hearing about.

## Reporting a vulnerability

Please report privately rather than opening a public issue: use
[**Report a vulnerability**](https://github.com/kfurtak1024/zecret/security/advisories/new)
on the repository's Security tab, which opens a draft advisory only the
maintainer can see.

Zecret is maintained by one person in their own time. Expect an
acknowledgement within a week; a fix takes as long as it takes, and you
will be kept posted. If you want credit in the advisory, say so and you
will get it.

Please include what you need to make the problem reproducible: the version
(`zecret --help` or the version on the help popup), the platform, and the
steps. A proof of concept against a scratch diary — `zecret --path
/tmp/scratch.enc` — is more useful than one against anything you care
about.

## Supported versions

Zecret is an application, not a library, and there is no release branch to
backport to. Fixes land on `main` and go out in the next release; only the
latest release is supported.

## Scope

In scope is anything that breaks one of these:

- **Confidentiality of entry text.** Nothing you write should be readable
  without your password, anywhere on disk.
- **Integrity.** A modified or truncated diary file must fail loudly, never
  decrypt to something plausible and wrong.
- **Authentication.** A wrong password must never open a diary, including
  an empty one.
- **Durability.** No sequence of ordinary use should lose entries that were
  saved, or leave a diary that cannot be opened by the password that made
  it.

The cryptographic requirements those rest on — Argon2id, AES-256-GCM, a
fresh nonce per encryption, per-entry independent encryption, atomic
writes — are written out in [CLAUDE.md](CLAUDE.md) and enforced by the test
suite. A change that quietly weakens one of them is a vulnerability even if
nothing visibly breaks.

## Known and accepted

These are documented design decisions, not oversights, and reports of them
will be closed as such. If you can show that one is worse than described,
that *is* worth reporting.

- **The diary file reveals which days you wrote on.** Entry dates sit
  outside the ciphertext so a record can be named without decrypting it.
  The file leaks the shape of the habit, never a word of the content.
- **There is no password recovery.** Lose the password and the diary is
  gone. This is the point, not a gap.
- **An unlocked Zecret is unlocked.** While the diary is open, entries are
  decrypted in memory and anyone at that terminal can read them. Zecret
  locks itself after a spell with no typing, which shortens that window but
  does not close it — during those minutes, and for as long as an entry is
  half-written, the diary is open.
- **Secrets cannot be wiped from memory.** Python strings and `bytes` are
  immutable, so the password and derived key cannot be overwritten after
  use, and Zecret does not lock pages into RAM. Either may reach swap or a
  core dump. Full-disk encryption is the answer to that, not this program.
- **`~/.zecret/config.json` is plaintext.** It holds the chosen theme and
  nothing else — no entry text, no dates, nothing derived from your key —
  because the lock screen has to be themed before there is a key.
- **Anyone who can already run code as you has won.** A keylogger, a
  debugger attached to the process, or a modified Zecret is outside what a
  local encrypted file can defend against.
