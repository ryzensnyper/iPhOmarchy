#!/bin/sh
# Install the G10P probe firmware (Stage 1).  Nothing else is touched.
#
# Refuses to run unless a flag file /root/.g10p-probe-ok is present, so a
# stray invocation cannot write to the device.
set -eu

FIRMWARE="apple/gfx-t8015.bin"
SOURCE="/home/doug/Known Good State/firmware/GPU/g10p.img"
EXPECTED_SHA="bd7b98e2833142d834bf3ac08dfc4a1d1f00d25a06ce04a67731a808a92bcc5c"

if [ "$(id -u)" -ne 0 ]; then
    echo "must run as root" >&2
    exit 1
fi
if [ ! -f "/root/.g10p-probe-ok" ]; then
    echo "refusing to run: /root/.g10p-probe-ok does not exist" >&2
    echo "create it only if you are sure the display is up and rollback is rehearsed" >&2
    exit 1
fi
if [ ! -f "$SOURCE" ]; then
    echo "firmware not found: $SOURCE" >&2
    exit 1
fi

SHA=$(sha256sum "$SOURCE" | cut -d' ' -f1)
echo "firmware: $SOURCE"
echo "sha256:   $SHA"
if [ "$SHA" != "$EXPECTED_SHA" ]; then
    echo "sha256 mismatch: refusing to install" >&2
    echo "expected: $EXPECTED_SHA" >&2
    echo "got:      $SHA" >&2
    exit 2
fi
echo "sha256 matches"
echo
echo "This copies $FIRMWARE to the firmware path used by the DT node. It does"
echo "not change the kernel, the DT, the display, or anything else."

DEST="/lib/firmware/$FIRMWARE"
mkdir -p "$(dirname "$DEST")"
cp "$SOURCE" "$DEST"
echo "installed: $DEST"
echo "rollback:  mv $DEST ${DEST}.disabled   (or ./rollback.sh)"
