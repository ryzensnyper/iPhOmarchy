#!/bin/sh
# Phase 2.2, step 2: install the G10P firmware into the payload rootfs.
#
# BUILD-TIME ONLY.  This copies the blob into the project's rootfs overlay,
# where `orchard build` turns it into /lib/firmware/apple/gfx-t8015.bin inside
# the initramfs.  It does not touch the phone and does not touch the kernel.
#
#   sh install-firmware.sh
#
# The driver gates on this file: without it the same kernel is a Phase 2.1
# boot (domain up, IOP untouched).
set -eu

SRC="${SRC:-/home/doug/Known Good State/firmware/GPU/g10p.img}"
ROOT="${ROOT:-/home/doug/omarchy-iphone/d21-desktop-boot/rootfs}"
DST="$ROOT/lib/firmware/apple/gfx-t8015.bin"
SHA=bd7b98e2833142d834bf3ac08dfc4a1d1f00d25a06ce04a67731a808a92bcc5c

[ -f "$SRC" ] || { echo "missing source: $SRC" >&2; exit 1; }
echo "$SHA  $SRC" | sha256sum -c - >/dev/null 2>&1 || {
    echo "source hash mismatch: $SRC" >&2; exit 1; }

mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
echo "$SHA  $DST" | sha256sum -c -
echo "installed: $DST"
echo "rebuild the payload so it lands in the initramfs"
