#!/bin/sh
# Phase 2.2, step 3: install the A11 PMP firmware into the payload rootfs.
#
# BUILD-TIME ONLY.  Extracts apple/pmp-t8015.bin out of the D21 kernelcache
# (it is embedded after the AppleT8015PMPFirmware kext's tag, not shipped as
# a file in the IPSW) and copies it into the rootfs overlay, where
# `orchard build` turns it into /lib/firmware/apple/pmp-t8015.bin inside the
# initramfs.
#
#   KC=/path/to/d21ap-kernelcache.macho sh install-pmp-firmware.sh
#
# Without this file pmp_t8015_v1.c fails at probe ("unable to load firmware")
# and the PMP never runs; with it, the driver uploads the image to the PMP's
# SRAM, remaps the AKF window and wakes RTKit.
set -eu

TOOLS="$(cd "$(dirname "$0")/../../tools" && pwd)"
KC="${KC:-/home/doug/orchard/.cache/ipsw/d21ap-kernelcache.macho}"
ROOT="${ROOT:-/home/doug/omarchy-iphone/d21-desktop-boot/rootfs}"
DST="$ROOT/lib/firmware/apple/pmp-t8015.bin"
SHA=2dcf73b5e13fe9c3f93731c7ef09de8e6244de9f610c34fff2981af90010cd52

[ -f "$KC" ] || {
    echo "kernelcache not found: $KC" >&2
    echo "extract it once with:" >&2
    echo "  cd /home/doug/orchard && PYTHONPATH=src python3 -m orchard.apple.remote_ipsw \\" >&2
    echo "      d21 kernelcache d21ap $KC" >&2
    exit 1
}

mkdir -p "$(dirname "$DST")"
python3 "$TOOLS/kc_pmp_extract.py" "$KC" "$DST"
echo "$SHA  $DST" | sha256sum -c -
echo "installed: $DST"
echo "rebuild the payload so it lands in the initramfs"
