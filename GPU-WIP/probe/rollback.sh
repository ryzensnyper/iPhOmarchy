#!/bin/sh
# Roll the probe back.  Designed to be safe to run at any point.
set -eu

FIRMWARE="apple/gfx-t8015.bin"
DEST="/lib/firmware/$FIRMWARE"

echo "1. remove any loaded probe module"
if command -v modprobe >/dev/null; then
    modprobe -r apple-t8015-gfx-iop 2>/dev/null || true
fi

echo "2. stop binding the GFX node (if the DT node was added)"
# The node only exists if a DT overlay was applied; doing nothing is safe:
# an unbound node that never matched is harmless.

echo "3. remove the firmware"
if [ -f "$DEST" ]; then
    mv "$DEST" "$DEST.disabled"
    echo "    moved $DEST -> $DEST.disabled"
else
    echo "    $DEST not present (already removed?)"
fi

echo "4. confirm the display still works"
if command -v fbset >/dev/null && [ -e /dev/fb0 ]; then
    fbset || true
fi
echo "5. reboot if in doubt: this phone boots from the m1n1 payload,"
echo "   so a reboot restores the known-good (simplefb) configuration."
echo "rollback done"
