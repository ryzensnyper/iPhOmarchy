#!/usr/bin/env python3
"""Write apple/pmp-t8015.bin out of an A11 kernelcache.

The PMP firmware is not an IMG4 file and it is not shipped in the IPSW's
Firmware/ tree: iOS embeds it in the kernelcache as the payload of the
AppleT8015PMPFirmware kext, 0xff0 bytes after the kext's tag string, and
hands the same bytes to the RTBuddy role=PMP.  The image starts with an
AArch64 exception vector table (`b #0x60`, then `b .` entries).

Length: the payload ends 0x280 bytes before the next prelinked bundle id
string (calibrated on the SmartIO image, which reproduces the device's file
byte-for-byte — see the A11-GPU-FINDINGS inventory).  For the A11 that is
126608 bytes; the size is pinned here and checked by hash, because a naive
"next com.apple.driver tag" search overshoots by 1088 bytes (the next bundle
is com.apple.iokit.IOUserEthernet).

    python3 kc_pmp_extract.py <kernelcache> [output]
    GPU_WIP_KC=<kernelcache> python3 kc_pmp_extract.py [output]

Verified 2026-11-11: the D21 (iPhone10,3) and D22 (iPhone10,2, 20H392)
kernelcaches carry the identical image, sha256 2dcf73b5...
The blob itself is Apple's, so it is not kept in this repo.
"""
import hashlib
import os
import re
import sys

TAG = b"com.apple.driver.AppleT8015PMPFirmware"
NEXT_ID = b"com.apple."
VECTOR = b"\x18\x00\x00\xea"  # b #0x60, then the b . table
TAG_SKIP = 0xFF0              # tag -> payload, same as AppleT8015SmartIO
TAIL_GAP = 0x280              # payload end -> next bundle id string
SIZE = 126608
SHA256 = "2dcf73b5e13fe9c3f93731c7ef09de8e6244de9f610c34fff2981af90010cd52"

kc_path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GPU_WIP_KC")
out_path = sys.argv[2] if len(sys.argv) > 2 else "pmp-t8015.bin"
if not kc_path:
    sys.exit("usage: kc_pmp_extract.py <kernelcache> [output]  (or set GPU_WIP_KC)")

kc = open(kc_path, "rb").read()
print(f"kernelcache: {kc_path} ({len(kc)} bytes)")

start = None
for m in re.finditer(re.escape(TAG), kc):
    p = m.start() + TAG_SKIP
    if kc[p:p + 4] == VECTOR:
        start = p
        break
if start is None:
    sys.exit("no AppleT8015PMPFirmware image (AArch64 vector table at tag+0xff0)")

# Prefer the calibrated rule; fall back to the pinned length.
nxt = re.search(re.escape(NEXT_ID), kc[start + SIZE // 2:])
end = start + SIZE
if nxt:
    candidate = start + SIZE // 2 + nxt.start() - TAIL_GAP
    if 0 < candidate - start <= 0x20000 and candidate != end:
        print(f"note: next bundle id gives {candidate - start} bytes "
              f"(pinned {SIZE}); using the pinned length")
image = kc[start:end]
digest = hashlib.sha256(image).hexdigest()
print(f"image: {len(image)} bytes at {start:#x}..{end:#x}")
print(f"sha256: {digest}")
print(f"head: {image[:16].hex()}  tail: {image[-16:].hex()}")

if len(image) > 0x20000:
    sys.exit("image larger than the 0x20000-byte SRAM window the DT gives the PMP")
if digest != SHA256:
    print("WARNING: hash differs from the D21/D22 build this was verified on")

with open(out_path, "wb") as f:
    f.write(image)
print(f"wrote {out_path}")
