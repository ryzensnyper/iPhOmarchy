#!/usr/bin/env python3
"""Enumerate AppleT8015* firmware tags in the A11 kernelcache and locate payloads."""
import os
import re, struct

KC = os.environ.get("GPU_WIP_KC", "/home/doug/a11-fw/kc/20H392__iPhone10,2/kernelcache.release.iPhone10,2_5")
kc = open(KC, "rb").read()

# 1) all com.apple.driver.* tags with offsets
tags = {}
for m in re.finditer(rb"com\.apple\.[A-Za-z0-9._-]{3,60}", kc):
    s = m.group().decode(errors="replace")
    if "T8015" in s or "PMP" in s.upper() or "SmartIO" in s:
        tags.setdefault(s, []).append(m.start())
for s in sorted(tags):
    print("%-46s %s" % (s, [hex(o) for o in tags[s][:6]]))

# 2) dump the region around the known tag table at 0xc6839e
lo, hi = 0xc68200, 0xc68600
print("\n--- strings 0x%x..0x%x ---" % (lo, hi))
for m in re.finditer(rb"[\x20-\x7e]{5,}", kc[lo:hi]):
    print("  0x%x: %s" % (lo + m.start(), m.group().decode(errors="replace")))

# 3) structure at the AppleT8015SmartIO image header (tag at 0x2cce010)
print("\n--- header bytes at 0x2cce010 ---")
blob = kc[0x2cce010:0x2cce010+0x40]
print("  ", blob[:0x40].hex())
print("  tag:", blob[4:4+0x40].split(b"\0")[0])

# 4) look for IMG4 payload magic 'IM4P' / 'IM4T' near the smartio payload
for magic in (b"IM4P", b"IM4T", b"IM4L"):
    offs = [m.start() for m in re.finditer(re.escape(magic), kc)]
    print("%s occurrences: %d %s" % (magic.decode(), len(offs), [hex(o) for o in offs[:10]]))
