#!/usr/bin/env python3
"""Exact-DP validation of a candidate framing.

The branch-constrained solver walks the corpus greedily (take the first
candidate that fits).  That is fast but brittle: a length change can break
an object that still has a valid tiling.  This validates a table properly:

  * forward reachability F[p] -- can p be reached from 0?
  * backward reachability B[p] -- can the end be reached from p?
  * a position is *usable* iff F[p] and B[p];
  * the object tiles exactly iff the end is reachable;
  * a branch target is satisfiable iff it is usable.

It also reports, for every A11-only class, how many objects still have a
valid tiling if that class's length is changed -- i.e. which lengths are
*forced* by the tiling requirement alone.

Usage: g10p_dpcheck.py [--corpus DIR] [--vendor DIR]
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

TWO = {0x8000, 0x0040, 0x0001, 0x0030, 0x0080, 0x00c4, 0x00c6,
       0x0810, 0x0830, 0x0840, 0x0850, 0x0853, 0x0860, 0x0870,
       0x0873, 0x0890, 0x08d0, 0x08f0, 0x08f3, 0x0f10, 0x0f40,
       0x0f80, 0x19f0}


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
            cs = [("N", i, (w >> 15) & 1) for i in ids] if ids else [("A", w)]
            cands.append(cs)
        objects.append((fn, words, cands))

    def make(a11_rule):
        length = {}
        for fn, words, cands in objects:
            for cs in cands:
                for c in cs:
                    if c in length:
                        continue
                    if c[0] == "A":
                        length[c] = a11_rule(c[1])
                    else:
                        nm = sigs[c[1]]["name"].split("|")[0]
                        length[c] = 1 if nm in ("stop", "stop/A11", "trap") else 3
        return length

    def reach(words, cands, length):
        """Forward and backward reachability -> set of usable positions."""
        n = len(words)
        F = [False] * (n + 1)
        F[0] = True
        for p in range(n):
            if not F[p]:
                continue
            for c in cands[p]:
                q = p + length[c]
                if q <= n:
                    F[q] = True
        B = [False] * (n + 1)
        B[n] = True
        for p in range(n - 1, -1, -1):
            for c in cands[p]:
                q = p + length[c]
                if q <= n and B[q]:
                    B[p] = True
                    break
        return F, B

    variants = [
        ("baseline: A11-only = 3 words", make(lambda w: 3)),
        ("published: A11-only 2 or 3 words", make(lambda w: 1 if w in TWO else 3)),
        ("old Addendum 5: A11-only by L bit",
         make(lambda w: 2 if not (w >> 15) & 1 else 1)),
    ]

    print("exact-DP validation")
    print("%-36s %-11s %-13s %-13s %-13s %-13s"
          % ("framing", "tiled", "c020 starts",
             "c020 tgt hit", "c000 off%6==0", "c000 tgt hit"))
    for name, length in variants:
        tiled = 0
        c20_starts = c20_mod = c20_hit = 0
        c00_mod = c00_starts = c00_hit = 0
        for fn, words, cands in objects:
            F, B = reach(words, cands, length)
            n = len(words)
            if not F[n]:
                continue
            tiled += 1
            for p in range(n):
                if not (F[p] and B[p]):
                    continue
                w = words[p]
                if w == 0xC020:
                    c20_starts += 1
                    if p + 2 < n and words[p + 2] % 6 == 0:
                        c20_mod += 1
                        t = p + words[p + 2] // 2
                        if 0 <= t < n and F[t] and B[t]:
                            c20_hit += 1
                elif w == 0xC000:
                    c00_starts += 1
                    if p + 1 < n and words[p + 1] % 6 == 0:
                        c00_mod += 1
                        t = p + words[p + 1] // 2
                        if 0 <= t < n and F[t] and B[t]:
                            c00_hit += 1
        print("%-36s %-11s %-13s %-13s %-13s %-13s"
              % (name, "%d/94" % tiled, "%d" % c20_starts,
                 "%d/%d (%.1f%%)" % (c20_hit, c20_mod,
                                     100.0 * c20_hit / max(c20_mod, 1)),
                 "%d/%d" % (c00_mod, c00_starts),
                 "%d/%d (%.1f%%)" % (c00_hit, c00_mod,
                                     100.0 * c00_hit / max(c00_mod, 1))))

    # which A11-only lengths are forced by the tiling requirement alone?
    print("\n=== A11-only classes: lengths that keep every object tileable "
          "(published table) ===")
    base = variants[1][1]
    forced = collections.Counter()
    optional = 0
    for c in list(base):
        if c[0] != "A":
            continue
        keep = []
        for L in (1, 2, 3, 4):
            length = dict(base)
            length[c] = L
            ok = True
            for fn, words, cands in objects:
                F, B = reach(words, cands, length)
                if not F[len(words)]:
                    ok = False
                    break
            if ok:
                keep.append(L)
        if len(keep) == 1:
            forced[(c, keep[0])] += 1
        else:
            optional += 1
    for (c, L), n in forced.most_common(30):
        print("   A11-only:%04x -> %d words is the ONLY tileable length"
              % (c[1], L))
    print("   (%d A11-only classes have more than one tileable length)"
          % optional)


if __name__ == "__main__":
    main()
