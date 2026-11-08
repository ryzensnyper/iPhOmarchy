#!/usr/bin/env python3
"""Locate 'g10p-b0' in AGXCompilerCore (dyld subcache .17) and find code xrefs.

Images in a dyld subcache are contiguous Mach-O files; we parse one directly.
"""
import os
import struct, sys

CACHE = os.environ.get("GPU_WIP_CACHE", "/home/doug/dsc-cache/allsub/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64.17")
IMG_OFF = 0x054a6000          # file offset of AGXCompilerCore inside .17
IMG_VM  = 0x1bbe3e000         # vmaddr of image base (= __TEXT vm per prior session)

data = open(CACHE, "rb").read()
img = data[IMG_OFF:]
print("image size (to end of file): %d bytes" % len(img))

# --- Mach-O header (64-bit LE) ---
magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags, reserved = struct.unpack_from("<8I", img, 0)
print("magic=%08x cputype=%d subtype=%d filetype=%d ncmds=%d sizeofcmds=0x%x" %
      (magic, cputype & 0xffffffff, cpusubtype & 0xffffffff, filetype, ncmds, sizeofcmds))
if magic != 0xfeedfacf:
    sys.exit("not a 64-bit Mach-O")

p = 32
segments = []
sections = []
for _ in range(ncmds):
    cmd, cmdsize = struct.unpack_from("<II", img, p)
    if cmd == 0x19:  # LC_SEGMENT_64
        segname = img[p+8:p+24].rstrip(b"\0").decode(errors="replace")
        vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<4Q", img, p+24)
        nsects = struct.unpack_from("<I", img, p+64)[0]
        segments.append((segname, vmaddr, vmsize, fileoff, filesize))
        so = p + 72
        for _ in range(nsects):
            sname = img[so:so+16].rstrip(b"\0").decode(errors="replace")
            sseg  = img[so+16:so+32].rstrip(b"\0").decode(errors="replace")
            addr, size = struct.unpack_from("<QQ", img, so+32)
            foff = struct.unpack_from("<I", img, so+48)[0]
            sections.append((sseg, sname, addr, size, foff))
            so += 80
    p += cmdsize

slide = IMG_VM  # vmaddr of file offset 0 within image

def f2v(fo):
    for sname, s, addr, size, foff in sections:
        if foff <= fo < foff + size:
            return addr + (fo - foff)
    return None

print("\nsegments:")
for s in segments:
    print("  %-16s vm 0x%x..0x%x fileoff 0x%x size 0x%x" % (s[0], s[1], s[1]+s[2], s[3], s[4]))
print("\nsections:")
for sseg, sname, addr, size, foff in sections:
    print("  %-10s %-20s vm 0x%012x size 0x%08x file 0x%08x" % (sseg, sname, addr, size, foff))

# --- locate strings of interest ---
def find_all(needle):
    out = []
    start = 0
    n = needle.encode()
    while True:
        i = img.find(n, start)
        if i < 0:
            break
        out.append(i)
        start = i + 1
    return out

for needle in ("g10p-b0", "g10p", "g11b", "g12b", "applegpu"):
    hits = find_all(needle)
    print("\n'%s' occurrences: %d" % (needle, len(hits)))
    for h in hits[:12]:
        vm = f2v(h)
        # print surrounding printable context
        s = max(0, h - 40)
        ctx = img[s:h+60]
        txt = "".join(chr(c) if 32 <= c < 127 else "." for c in ctx)
        print("   file 0x%08x vm %s  ...%s..." % (h, hex(vm) if vm else "?", txt))
