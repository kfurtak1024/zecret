#!/usr/bin/env bash
#
# Run Zecret from this checkout against a throwaway diary.
#
#     ./zecret-dev.sh              # seed if needed, then open the dev diary
#     ./zecret-dev.sh --help       # extra arguments go through to zecret
#
# Development must never open the real diary at ~/.zecret. The working tree
# is the program: an unfinished storage.py is how entries get lost, and a
# format change nothing has migrated yet is how they become unreadable.
#
# Staying clear of it takes *both* overrides -- --path for the entries and
# --config for the preferences -- and only one of them fails loudly. Forget
# --path and you are looking at your own diary, which you will notice.
# Forget --config and nothing appears to happen, while the settings you
# actually use quietly follow whatever the build under development wrote.
# So the pair lives here rather than in anyone's shell history.
#
# Everything is under .zecret-dev/, which is gitignored and outside the
# sdist allowlist. Delete it whenever you like; the next run rebuilds it.
# The password is printed by the seeder and is "dev".

set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dev="$repo/.zecret-dev"

if [ ! -e "$dev/diary.enc" ]; then
    echo "No dev diary at $dev/diary.enc -- seeding one."
    uv run --directory "$repo" python "$repo/tools/seed_dev_diary.py"
    echo
fi

# Absolute paths, and --directory, so this works from any working
# directory. exec so ctrl+c and the exit code belong to the app.
exec uv run --directory "$repo" zecret \
    --path "$dev/diary.enc" \
    --config "$dev/config.json" \
    "$@"
