#!/usr/bin/env python3
"""Find the embedded 't8015pmp' firmware Mach-O in the A11 kernelcache and check
whether the local gfx-t8015-const.bin is its __TEXT.__const section."""
import os
import re, struct, os

KC = os.environ.get("GPU_WIP_KC", "/home/doug/a11-fw/kc/20H392__iPhone10,2/kernelcache.release.iPhone10,2_5")
kc = open(KC, "rb").read()
LOCAL = os.environ.get("GPU_WIP_LOCAL", "/home/doug/Known Good State/firmware/GPU/gfx-t8015-const.bin")
loc = open(LOCAL, "rb").read()

def sections_at(off):
    try:
        magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds = struct.unpack_from("<6I", kc, off)
    except struct.error:
        return None
    if magic != 0xfeedfacf or not (0 < ncmds < 100) or sizeofcmds > 0x200000:
        return None
    p = off + 32
    out = []
    ok = True
    for _ in range(ncmds):
        if p + 8 > len(kc):
            return None
        cmd, cmdsize = struct.unpack_from("<II", kc, p)
        if cmdsize < 8 or p + cmdsize > len(kc):
            ok = False
            break
        if cmd == 0x19:
            nsects = struct.unpack_from("<I", kc, p + 64)[0]
            so = p + 72
            for _ in range(nsects):
                if so + 80 > len(kc):
                    ok = False
                    break
                sn = kc[so:so+16].rstrip(b"\0").decode(errors="replace")
                sg = kc[so+16:so+32].rstrip(b"\0").decode(errors="replace")
                addr, size = struct.unpack_from("<QQ", kc, so+32)
                foff = struct.unpack_from("<I", kc, so+48)[0]
                out.append((sg, sn, addr, size, foff))
                so += 80
        p += cmdsize
    return out if ok else None

hits = []
for m in re.finditer(b"\xcf\xfa\xed\xfe", kc):
    off = m.start()
    secs = sections_at(off)
    if not secs:
        continue
    names = [s[1] for s in secs]
    if "__TEXT_EXEC" in names or ("__const" in names and "__text" not in names):
        hits.append((off, secs))

print("candidate embedded firmware Mach-Os: %d" % len(hits))
for off, secs in hits[:20]:
    print("\nMach-O at 0x%x" % off)
    for sg, sn, addr, size, foff in secs:
        print("   %-10s %-14s size 0x%x fileoff 0x%x" % (sg, sn, size, foff))
    # compare __const / __TEXT sections against the local blob
    for sg, sn, addr, size, foff in secs:
        if size == 0:
            continue
        blob = kc[foff:foff+size]
        if blob[:16] == loc[:16]:
            n = 0
            while n < len(loc) and n < size and blob[n] == loc[n]:
                n += 1
            print("   -> local gfx-t8015-const.bin matches section %s/%s: %d bytes" % (sg, sn, n))

# also: does the local blob appear anywhere in the kernelcache?
j = kc.find(loc[:64])
print("\nlocal blob first-64-bytes at: %s" % (hex(j) if j >= 0 else "not found"))
if j >= 0:
    n = 0
    while n < len(loc) and j+n < len(kc) and kc[j+n] == loc[n]:
        n += 1
    print("  contiguous match %d / %d" % (n, len(loc)))
    # which section does it sit in?
    for off, secs in hits:
        for sg, sn, addr, size, foff in secs:
            if size and foff <= j < foff+size:
                print("  inside Mach-O 0x%x section %s/%s (fileoff 0x%x size 0x%x) delta 0x%x" %
                      (off, sg, sn, foff, size, j-foff))
