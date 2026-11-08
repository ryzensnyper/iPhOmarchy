#!/usr/bin/env python3
"""Dump the AGX instruction words of a .g10p-o Mach-O object (section-aware)."""
import os
import struct, sys, os

CORPUS = os.environ.get("GPU_WIP_CORPUS", "/home/doug/Known Good State/firmware/GPU/ds-g10p")

def macho_text(path):
    d = open(path, "rb").read()
    magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds = struct.unpack_from("<6I", d, 0)
    assert magic == 0xfeedfacf, hex(magic)
    p = 32
    secs = []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", d, p)
        if cmd == 0x19:
            nsects = struct.unpack_from("<I", d, p+64)[0]
            so = p + 72
            for _ in range(nsects):
                sn = d[so:so+16].rstrip(b"\0").decode(errors="replace")
                sg = d[so+16:so+32].rstrip(b"\0").decode(errors="replace")
                addr, size = struct.unpack_from("<QQ", d, so+32)
                foff = struct.unpack_from("<I", d, so+48)[0]
                secs.append((sg, sn, addr, size, foff))
                so += 80
        p += cmdsize
    return secs, d

for name in sys.argv[1:]:
    path = os.path.join(CORPUS, name)
    secs, d = macho_text(path)
    print("=== %s ===" % name)
    for sg, sn, addr, size, foff in secs:
        print("   %-10s %-14s size 0x%-6x file 0x%x" % (sg, sn, size, foff))
    # the code section is usually __TEXT,__text or __TEXT,__const
    code = None
    for sg, sn, addr, size, foff in secs:
        if sn in ("__text", "__const", "__code") and sg == "__TEXT" and size:
            code = (sn, foff, size)
            break
    if not code:
        print("   (no code section found)")
        continue
    sn, foff, size = code
    words = struct.unpack_from("<%dH" % (size//2), d, foff)
    print("   section %s: %d words" % (sn, len(words)))
    for i in range(0, min(len(words), 120)):
        w = words[i]
        print("   [%3d] 0x%04x  %s" % (i, w, ""), end="")
        print()
