#!/usr/bin/env python3
"""Opcode-value census over the A11 corpus: low-12-bit value frequencies,
annotated with Mesa's opcode names (and A11 deltas)."""
import os
import glob, os, struct, sys
from collections import Counter

REF = os.environ.get("GPU_WIP_REF", "/home/doug/Known Good State/firmware/GPU/tools/reference-agx-isa")
CORPUS = os.environ.get("GPU_WIP_CORPUS", "/home/doug/Known Good State/firmware/GPU/ds-g10p")
sys.path.insert(0, REF)
import agx_opcodes as A

def norm(e):
    if e is None:
        return None
    ls = e.length_short
    ll = getattr(e, "length_long", None)
    if ll is None:
        ll = ls + (4 if (e.extensible and ls > 8) else (2 if e.extensible else 0))
    return (e.exact, e.mask, ls, ll)

mesa = {}
for name, op in A.opcodes.items():
    e = norm(op.encoding_32) or norm(op.encoding_16)
    if e:
        mesa.setdefault(e[0] & 0xfff, []).append((name, e[1], e[2], e[3]))
    e16 = norm(op.encoding_16)
    if e16:
        mesa.setdefault(e16[0] & 0xfff, []).append((name + "/16", e16[1], e16[2], e16[3]))

def text_words(path):
    d = open(path, "rb").read()
    magic, _, _, _, ncmds, _ = struct.unpack_from("<6I", d, 0)
    if magic != 0xfeedfacf:
        return None
    p = 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", d, p)
        if cmd == 0x19:
            nsects = struct.unpack_from("<I", d, p+64)[0]
            so = p + 72
            for _ in range(nsects):
                sn = d[so:so+16].rstrip(b"\0")
                sg = d[so+16:so+32].rstrip(b"\0")
                addr, size = struct.unpack_from("<QQ", d, so+32)
                foff = struct.unpack_from("<I", d, so+48)[0]
                if sg == b"__TEXT" and sn == b"__text" and size:
                    return struct.unpack_from("<%dH" % (size//2), d, foff)
                so += 80
        p += cmdsize
    return None

cnt = Counter()
files = sorted(glob.glob(os.path.join(CORPUS, "*.g10p-o")))
for f in files:
    w = text_words(f)
    if not w:
        continue
    for x in w:
        cnt[x & 0xfff] += 1

print("corpus files: %d, total words: %d" % (len(files), sum(cnt.values())))
print("\n%-6s %8s  %s" % ("low12", "count", "mesa match"))
for val, c in cnt.most_common(40):
    m = mesa.get(val)
    tag = ""
    if m:
        tag = ", ".join("%s(mask %04x, %d/%d)" % t for t in m)
    else:
        tag = "-- no Mesa signature --"
    print("%04x  %8d  %s" % (val, c, tag))
