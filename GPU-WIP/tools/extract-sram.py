#!/usr/bin/env python3
"""Rebuild the PMP's runtime firmware image from a boot's kmsg extract.

Boot #69 (tree f439476053cf) dumped the PMP's whole 128 KiB SRAM at
0x232500000 (the firmware is MMU-mapped VA 0x01000000 -> PA 0x232500000)
as "pmp-v2: SR <off> w0 w1 w2 w3" lines, crashed the firmware once with
(cmd 1, dev 149) and printed the changed words as "pmp-v2: DELTA <va>:
<old> -> <new>" lines.

usage: extract-sram.py <boot-log> [out.bin]
Writes the pre-crash runtime image (VA 0x01000000-based, i.e. the SRAM
bytes verbatim) and prints the delta summary vs. the file image.
"""
import re
import struct
import sys

log, out = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "pmp-runtime.bin")
lines = open(log, errors="replace").read().split("\n")
words = {}
for ln in lines:
    if "SRAM dump done" in ln:
        break
    m = re.match(
        r".*pmp-v2: SR ([0-9a-f]+) ([0-9a-f]{8}) ([0-9a-f]{8}) ([0-9a-f]{8}) ([0-9a-f]{8})",
        ln,
    )
    if m:
        off = int(m.group(1), 16)
        for k in range(4):
            words[off + 4 * k] = int(m.group(2 + k), 16)
img = bytearray(0x20000)
for off, w in words.items():
    if off < 0x20000:
        struct.pack_into("<I", img, off, w)
open(out, "wb").write(img)
print("%s: %d words (expected 32768)" % (out, len(words)))

try:
    base = open("pmp-t8015.bin", "rb").read()
except OSError:
    raise SystemExit("(no pmp-t8015.bin alongside; skipping the diff)")
n = min(len(base), len(img))
diffs = [
    off
    for off in range(0, n, 4)
    if struct.unpack_from("<I", base, off)[0]
    != struct.unpack_from("<I", img, off)[0]
]
print("runtime-vs-file diffs: %d words" % len(diffs))
pages = sorted({off >> 12 for off in diffs})
print("diff pages (4K):", " ".join("%#05x" % (p << 12) for p in pages))
