#!/usr/bin/env python3
"""Extract the AppleT8015PMPFirmware image from the A11 kernelcache and check
whether our local gfx-t8015-const.bin belongs to the embedded 't8015pmp' Mach-O."""
import os
import re, struct, os

KC = os.environ.get("GPU_WIP_KC", "/home/doug/a11-fw/kc/20H392__iPhone10,2/kernelcache.release.iPhone10,2_5")
kc = open(KC, "rb").read()
OUT = "/tmp/opencode/device"
os.makedirs(OUT, exist_ok=True)

TAG = b"com.apple.driver.AppleT8015PMPFirmware"
offs = [m.start() for m in re.finditer(re.escape(TAG), kc)]
print("PMP tag offsets:", [hex(o) for o in offs])

# same layout as the SmartIO image: tag at T, payload at T+0xFF0
for t in offs:
    p = t + 0xFF0
    print("\ntag 0x%x -> payload candidate 0x%x" % (t, p))
    print("   first 32 bytes:", kc[p:p+32].hex())
    # look for a plausible end: next IMG4-ish tag or the SmartIO tag
    nxt = kc.find(b"com.apple.driver.", p)
    print("   next tag at 0x%x (delta 0x%x)" % (nxt, nxt - p if nxt > 0 else -1))

# --- the SmartIO reference case for validation ---
ST = kc.find(b"com.apple.driver.AppleT8015SmartIO")
print("\nSmartIO tag 0x%x payload 0x%x delta 0x%x" % (ST, 0x2ccf000, 0x2ccf000 - ST))

# --- embedded 't8015pmp' Mach-O in the AGX kext ---
i = kc.find(b"t8015pmp")
print("\n't8015pmp' string at 0x%x" % i)
# the Mach-O header should be nearby: search backwards for 0xfeedfacf
lo = max(0, i - 0x200000)
for m in re.finditer(b"\xcf\xfa\xed\xfe", kc[lo:i]):
    off = lo + m.start()
    magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds = struct.unpack_from("<6I", kc, off)
    if 0 < ncmds < 200 and sizeofcmds < 0x100000:
        print("  candidate Mach-O at 0x%x: cputype=%d filetype=%d ncmds=%d sizeofcmds=0x%x" %
              (off, cputype, filetype, ncmds, sizeofcmds))

# --- compare our local const blob to the region ---
loc = open("/home/doug/Known Good State/firmware/GPU/gfx-t8015-const.bin", "rb").read()
j = kc.find(loc[:64])
print("\nlocal gfx-t8015-const.bin first 64 bytes found in kernelcache at: %s" %
      (hex(j) if j >= 0 else "not found"))
if j >= 0:
    n = 0
    while n < len(loc) and j+n < len(kc) and kc[j+n] == loc[n]:
        n += 1
    print("  contiguous match: %d / %d bytes" % (n, len(loc)))
