#!/usr/bin/env python3
"""Scan an image inside a dyld subcache for AGX-style opcode tables.

A table entry looks like Mesa's (exact, mask, len_short, len_long):
  - exact & mask == exact            (the exact bits must be inside the mask)
  - mask == 0 or a plausible 16-bit mask
  - lengths in {2,4,6,8,10,12} (bytes) or 0
We report maximal runs of >= 8 consecutive entries that satisfy this.
"""
import os
import struct, sys, collections

CACHE = os.environ.get("GPU_WIP_CACHE", "/home/doug/dsc-cache/allsub/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64.17")
LEN_OK = {0, 2, 4, 6, 8, 10, 12}

def load(img_off):
    data = open(CACHE, "rb").read()
    img = data[img_off:]
    magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds = struct.unpack_from("<6I", img, 0)
    assert magic == 0xfeedfacf, hex(magic)
    p = 32
    sections = []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", img, p)
        if cmd == 0x19:
            segname = img[p+8:p+24].rstrip(b"\0").decode(errors="replace")
            nsects = struct.unpack_from("<I", img, p+64)[0]
            so = p + 72
            for _ in range(nsects):
                sname = img[so:so+16].rstrip(b"\0").decode(errors="replace")
                sseg = img[so+16:so+32].rstrip(b"\0").decode(errors="replace")
                addr, size = struct.unpack_from("<QQ", img, so+32)
                foff = struct.unpack_from("<I", img, so+48)[0]
                sections.append((sseg, sname, addr, size, foff))
                so += 80
        p += cmdsize
    return data, sections

def entry_ok(a, b, c, d):
    if c not in LEN_OK or d not in LEN_OK:
        return False
    if b == 0:
        return a <= 0x0fff
    if b & 0xffff0000:
        return False
    if a & ~b:
        return False
    # mask must have some bits set
    return True

def scan(name, img_off):
    data, sections = load(img_off)
    print("=== %s (file 0x%x) ===" % (name, img_off))
    for sseg, sname, addr, size, foff in sections:
        if sname in ("__bss",) or size == 0:
            continue
        if sseg not in ("__TEXT", "__DATA_CONST", "__DATA", "__DATA_DIRTY"):
            continue
        blob = data[foff:foff+size]
        n = len(blob) // 16
        flags = []
        for i in range(n):
            a, b, c, d = struct.unpack_from("<4I", blob, i*16)
            flags.append(entry_ok(a, b, c, d))
        # maximal runs
        i = 0
        runs = []
        while i < n:
            if flags[i]:
                j = i
                while j < n and flags[j]:
                    j += 1
                if j - i >= 8:
                    runs.append((i, j))
                i = j
            else:
                i += 1
        for (i, j) in runs:
            vm = addr + i*16
            print("  run %-10s %-20s entries %4d  vm 0x%x .. 0x%x" %
                  (sseg, sname, j-i, vm, vm+(j-i)*16))
            a, b, c, d = struct.unpack_from("<4I", blob, i*16)
            print("     first: exact=0x%04x mask=0x%04x len=%d/%d" % (a, b, c, d))
            a, b, c, d = struct.unpack_from("<4I", blob, (j-1)*16)
            print("     last : exact=0x%04x mask=0x%04x len=%d/%d" % (a, b, c, d))
            lens = collections.Counter()
            for k in range(i, j):
                a, b, c, d = struct.unpack_from("<4I", blob, k*16)
                lens[(c, d)] += 1
            print("     len histogram: %s" % dict(lens.most_common(8)))

if __name__ == "__main__":
    scan("AGXCompilerCore", 0x054a6000)
    scan("libGPUCompilerImpl", 0x05632000)
