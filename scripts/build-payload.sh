#!/bin/bash
# Assemble an m1n1 payload that pongoOS `bootm` runs.
#
# Layout m1n1's payload parser expects (src/payload.c):
#   m1n1.bin | "chosen.bootargs=..." line | devicetree | kernel(.gz)
# (an initramfs, if used, must be gzip/xz and placed after the kernel)
#
# Usage:
#   M1N1=... DTB=... KERNEL=... BOOTARGS="..." ./build-payload.sh out.bin
#
# Example (boot the installed Arch Linux ARM on nvme0n1p2):
#   M1N1=~/hoolock/m1n1/build/m1n1.bin \
#   DTB=~/hoolock/linux/arch/arm64/boot/dts/apple/t8015-d21.dtb \
#   KERNEL=~/hoolock/linux/arch/arm64/boot/Image.gz \
#   BOOTARGS="root=/dev/nvme0n1p2 rootwait rw console=tty0" ./build-payload.sh m1n1-linux-p2.bin
set -euo pipefail

M1N1=${M1N1:?set M1N1=/path/to/build/m1n1.bin}
DTB=${DTB:?set DTB=/path/to/t8015-d21.dtb}
KERNEL=${KERNEL:?set KERNEL=/path/to/Image.gz}
BOOTARGS=${BOOTARGS:-root=/dev/nvme0n1p2 rootwait rw console=tty0}
OUT=${1:-m1n1-linux.bin}

for f in "$M1N1" "$DTB" "$KERNEL"; do
    [ -f "$f" ] || { echo "missing $f" >&2; exit 1; }
done

{
    cat "$M1N1"
    printf 'chosen.bootargs=%s\n' "$BOOTARGS"
    cat "$DTB"
    cat "$KERNEL"
} > "$OUT"

python3 - "$OUT" "$M1N1" "$DTB" "$KERNEL" "$BOOTARGS" <<'PY'
import struct, sys
out, m1n1, dtb, kern, args = sys.argv[1:6]
b = open(out,'rb').read(); m = open(m1n1,'rb').read()
d = open(dtb,'rb').read(); k = open(kern,'rb').read()
line = ('chosen.bootargs=%s\n' % args).encode()
off = 0
assert b[:len(m)] == m, "m1n1 prefix mismatch"; off += len(m)
assert b[off:off+len(line)] == line, "bootargs mismatch"; off += len(line)
assert b[off:off+4] == b'\xd0\x0d\xfe\xed', "dtb magic not where m1n1 looks"
assert struct.unpack('>I', b[off+4:off+8])[0] == len(d), "dtb size field"; off += len(d)
assert b[off:off+2] == b'\x1f\x8b', "kernel is not gzip"; off += len(k)
assert off == len(b), "trailing bytes (%d) would be parsed as an initrd" % (len(b)-off)
print("  m1n1        %9d @0" % len(m))
print("  bootargs    %9d  %s" % (len(line), args))
print("  devicetree  %9d @%d" % (len(d), len(m)+len(line)))
print("  kernel      %9d @%d (gzip)" % (len(k), len(m)+len(line)+len(d)))
print("  total       %9d" % len(b))
PY
echo "==> wrote $OUT"
