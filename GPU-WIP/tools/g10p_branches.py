#!/usr/bin/env python3
"""Validate a candidate A11 framing with branch targets.

The AGX branch instructions (`jmp_exec_any` = 0xc000, `jmp_exec_none` =
0xc020, `call` = 0xc010) carry a 32-bit sign-extended *byte* offset
(`next_pc = pc + sign_extend(off, 32)`, per the AGX descriptor table).

That gives an independent, semantic test of the framing: if the framing is
right, branch targets must land on instruction boundaries.  A mis-framed
corpus sends branches into the middle of instructions.

This is also usable as an *objective* for a search over the free parts of
the length table (the A11-only opcodes), which is far better founded than
"the object tiles".

Usage: g10p_branches.py [--corpus DIR] [--vendor DIR] [--only4]
"""
import collections
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CORPUS = os.environ.get(
    "GPU_WIP_CORPUS", "/home/doug/Known Good State/firmware/GPU/ds-g10p")
_SIBLING = os.path.join(_HERE, "reference-agx-isa")
DEFAULT_VENDOR = os.environ.get("GPU_WIP_APPLEGPU") or (
    _SIBLING if os.path.isdir(_SIBLING) else
    "/home/doug/Known Good State/firmware/GPU/tools/reference-agx-isa")

BRANCH = {0xC000: "jmp_exec_any", 0xC020: "jmp_exec_none", 0xC010: "call"}


def main():
    corpus = DEFAULT_CORPUS
    vendor = DEFAULT_VENDOR
    for i, a in enumerate(sys.argv):
        if a == "--corpus":
            corpus = sys.argv[i + 1]
        elif a == "--vendor":
            vendor = sys.argv[i + 1]
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    import applegpu as ag

    sigs = []
    idx = {}
    for o in ag.instruction_descriptors:
        m = o.mask & 0xFFFF
        b = o.bits & 0xFFFF
        if (m, b) not in idx:
            idx[(m, b)] = len(sigs)
            sigs.append({"mask": m, "bits": b, "name": o.name})
        else:
            sigs[idx[(m, b)]]["name"] += "|" + o.name
    if (0xFFFF, 0x0108) not in idx:
        idx[(0xFFFF, 0x0108)] = len(sigs)
        sigs.append({"mask": 0xFFFF, "bits": 0x0108, "name": "stop/A11"})
    wc = collections.defaultdict(list)
    for i, s in enumerate(sigs):
        for w in range(0x10000):
            if (w & s["mask"]) == (s["bits"] & s["mask"]):
                wc[w].append(i)

    FREE = -1
    allcls = set()
    objects = []
    for fn in sorted(f for f in os.listdir(corpus) if f.endswith(".g10p-o")):
        d = open(os.path.join(corpus, fn), "rb").read()
        magic, _, _, _, ncmds, _ = struct.unpack_from("<6I", d, 0)
        q = 32
        code = None
        for _ in range(ncmds):
            cmd, cmdsize = struct.unpack_from("<II", d, q)
            if cmd == 0x19:
                nsects = struct.unpack_from("<I", d, q + 64)[0]
                so = q + 72
                for _ in range(nsects):
                    sn = d[so:so + 16].rstrip(b"\0")
                    sg = d[so + 16:so + 32].rstrip(b"\0")
                    size = struct.unpack_from("<Q", d, so + 40)[0]
                    foff = struct.unpack_from("<I", d, so + 48)[0]
                    if sg == b"__TEXT" and sn == b"__text" and size:
                        code = d[foff:foff + size]
                    so += 80
            q += cmdsize
        if not code:
            continue
        words = list(struct.unpack_from("<%dH" % (len(code) // 2), code, 0))
        cands = []
        for w in words:
            ids = wc.get(w)
            cs = [(i, (w >> 15) & 1) for i in ids] if ids else [(FREE, (w >> 15) & 1)]
            cands.append(cs)
            allcls.update(cs)
        objects.append((fn, words, cands))

    length = {}
    for cls in allcls:
        sid, lb = cls
        if sid == FREE:
            length[cls] = 2 if lb == 0 else 1
        else:
            nm = sigs[sid]["name"].split("|")[0]
            length[cls] = 1 if nm in ("stop", "stop/A11", "trap") else 3

    tot = 0
    hit = 0
    oob = 0
    per = collections.Counter()
    perhit = collections.Counter()
    examples = []
    for fn, words, cands in objects:
        n = len(words)
        # frame: greedy walk (the table tiles the corpus, so any complete
        # walk is a valid framing under the table)
        starts = set()
        seq = []
        p = 0
        while p < n:
            placed = False
            for cls in cands[p]:
                L = length[cls]
                if p + L <= n:
                    starts.add(p)
                    seq.append((p, cls, L))
                    p += L
                    placed = True
                    break
            if not placed:
                break
        for p, cls, L in seq:
            sid, lb = cls
            if sid == FREE:
                continue
            nm = sigs[sid]["name"].split("|")[0]
            if words[p] not in BRANCH:
                continue
            # A11: 16-bit sign-extended offset in the THIRD word
            if p + 3 > n:
                continue
            off = words[p + 2]
            if off & 0x8000:
                off -= 1 << 16
            for base, tag in ((p * 2, "pc"), ((p + 3) * 2, "next")):
                tgt = base + off
                tot += 1
                per[(BRANCH[words[p]], tag)] += 1
                if 0 <= tgt < n * 2 and (tgt // 2) in starts:
                    hit += 1
                    perhit[(BRANCH[words[p]], tag)] += 1
                    if len(examples) < 6 and off != 0:
                        examples.append((fn, p, words[p], off, tgt, tag))
                else:
                    if tgt < 0 or tgt >= n * 2:
                        oob += 1
    print("branch target test (target must be an instruction boundary)")
    print("  branches tested: %d   on a boundary: %d (%.1f%%)   out of section: %d"
          % (tot, hit, 100.0 * hit / max(tot, 1), oob))
    for k in sorted(per):
        print("   %-16s %-5s  %6d  -> %6d on boundary (%.1f%%)"
              % (k[0], k[1], per[k], perhit[k], 100.0 * perhit[k] / per[k]))
    if examples:
        print("\n  examples:")
        for fn, p, w, off, tgt, tag in examples:
            print("    %-34s @%-6d %04x off=%-8d target=%d (%s)"
                  % (fn[:34], p * 2, w, off, tgt, tag))


if __name__ == "__main__":
    main()
