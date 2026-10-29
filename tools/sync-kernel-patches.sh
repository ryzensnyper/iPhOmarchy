#!/usr/bin/env bash
# Sync the D21 driver work from the HoolockLinux a11-port tree into this
# repository as a numbered patch series, then commit (push is manual).
#
# Usage: tools/sync-kernel-patches.sh [linux-tree] [base-commit]
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
TREE="${1:-$HOME/hoolock/linux}"
BASE="${2:-30a2e7532}"   # kernel release the running build identifies as

cd "$TREE"
NEW=$(git log --oneline "$BASE..HEAD" -- drivers/input/touchscreen/apple_z2.c \
      | wc -l)
echo "a11-port commits since $BASE touching the driver: $NEW"
[ "$NEW" -eq 0 ] && { echo "nothing to sync"; exit 0; }

# Existing series tail (0001-0003 are the pre-existing DT/makez2fw patches)
LAST=$(ls "$HERE"/patches/0* 2>/dev/null | sed 's/.*patches\///;s/-.*//' | sort -n | tail -1)
START=$((10#$LAST + 1))
echo "exporting as patches/$(printf '%04d' "$START")+ ..."
git format-patch --start-number "$START" -o "$HERE/patches" "$BASE..HEAD" \
	-- drivers/input/touchscreen/apple_z2.c drivers/input/touchscreen/Kconfig \
	   drivers/input/touchscreen/Makefile

cd "$HERE"
git add patches/
git commit -m "patches: sync a11-port apple-z2 series ($NEW new)" || echo "nothing new to commit"
git --no-pager log --oneline -2
echo "review then: git push origin main"
