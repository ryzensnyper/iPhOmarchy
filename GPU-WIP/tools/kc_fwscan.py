#!/usr/bin/env python3
"""Locate firmware payloads inside the A11 kernelcache (IMG4/IM4 blob)."""
import os
import sys, re

KC = os.environ.get("GPU_WIP_KC", "/home/doug/a11-fw/kc/20H392__iPhone10,2/kernelcache.release.iPhone10,2_5")
SMARTIO = os.environ.get("GPU_WIP_SMARTIO", "/home/doug/a11-fw/out/t8015-smartio.bin")

kc = open(KC, "rb").read()
sm = open(SMARTIO, "rb").read()
print("kernelcache %d bytes; smartio %d bytes" % (len(kc), len(sm)))

i = kc.find(sm[:64])
print("smartio payload offset in kernelcache: %s" % (hex(i) if i >= 0 else "not found"))
if i >= 0:
    # verify full match
    n = 0
    while n < len(sm) and i + n < len(kc) and kc[i+n] == sm[n]:
        n += 1
    print("  contiguous bytes matching: %d / %d" % (n, len(sm)))

# all occurrences of interesting tags
for tag in (b"t8015pmp", b"t8015", b"AppleT8015", b"SmartIO", b"smartio", b"PMP", b"pmp"):
    offs = [m.start() for m in re.finditer(re.escape(tag), kc)]
    print("%-12s occurrences: %d %s" % (tag.decode(), len(offs), [hex(o) for o in offs[:12]]))

# print printable strings around the smartio payload
if i >= 0:
    lo = max(0, i - 0x4000)
    hi = min(len(kc), i + len(sm) + 0x4000)
    blob = kc[lo:hi]
    print("\n--- printable strings in [payload-0x4000, payload+len+0x4000] ---")
    for m in re.finditer(rb"[\x20-\x7e]{6,}", blob):
        s = m.group().decode(errors="replace")
        if any(k in s.lower() for k in ("t8015", "pmp", "smart", "gfx", "agx", "apple", "img", "fw")):
            print("  0x%x: %s" % (lo + m.start(), s[:120]))
