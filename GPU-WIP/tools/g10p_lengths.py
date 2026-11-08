#!/usr/bin/env python3
"""Derive and validate the A11 (G10P) AGX instruction length table.

    G10P ISA -- length table
    =========================

Background
----------
The G10P corpus (`ds-g10p/`, 94 Mach-O shader objects, 492 190 words of
`__TEXT,__text`) is A11 (`applegpu_g10p`) code.  Its *opcode values* agree
with the public AGX ISA used by A12+ (Mesa `agx_opcodes.py`, and
dougallj/applegpu's `applegpu.py`), but its *instruction lengths* do not:
Mesa/G13 mix 2/4/6/8/10/12-byte instructions, while G10P is dominated by a
single 6-byte quantum.

This tool derives the table from the corpus alone and validates it.

Method
------
1.  Opcode dictionary: applegpu's descriptor table, reduced to its low-16
    signature (mask, bits).  81 distinct signatures; `jmp_exec_none` =
    0xc020 in applegpu, which is exactly the value independently measured in
    the G10P corpus, so the two dialects are the same family.

2.  Length quantum: the *local repetition period* at an opcode occurrence.
    Where a single instruction repeats, the period is its length.  Measured
    over the whole corpus with a 6-word match window:
        imadd  -> period 3 words (6 B) in 5172 resolved cases
        fadd16 -> period gcd 3 (6 B)
        trap   -> period 1 word  (2 B) in 877 cases
    The global word autocorrelation peaks at d = 3, 6, 9 words.
    => baseline: every instruction is 3 words (6 bytes); trap/stop are 1.

3.  Exact tiling: with a fixed length table the set of tileable positions is
    computed by a forward reachability DP.  That is *complete* (no greedy
    walk, no heuristic), so "this object tiles" is a proof.
    The baseline already tiles 72/94 objects and 477 051/492 190 words.

4.  Minimal-deviation repair: for every object that does not tile, every
    single-class length change is tested; the change that repairs the most
    objects is applied, and the process repeats.  Only the deviations that
    are *forced* (changing them breaks some object) are ISA statements.

5.  Validation:
      * exact tiling of all 94 objects;
      * 2-fold cross-validation (solve on half, test on the other half);
      * an independent structural check: the next function after a
        terminator must start on a 64-byte boundary (80/125 = 64 % of
        mid-section functions, against 3.1 % by chance).

Usage: g10p_lengths.py [--corpus DIR] [--vendor DIR] [--json OUT]
                       [--quiet]

Environment overrides: GPU_WIP_CORPUS, GPU_WIP_APPLEGPU
"""
import collections
import json
import os
import struct
import sys

UNITS = [1, 2, 3, 4, 5, 6]                 # words: 2,4,6,8,10,12 bytes

DEFAULT_CORPUS = os.environ.get(
    "GPU_WIP_CORPUS", "/home/doug/Known Good State/firmware/GPU/ds-g10p")

# Where the vendored applegpu descriptor table lives.  Follows the same
# convention as the other GPU-WIP tools: an environment-variable override,
# with our local layout as the default.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SIBLING = os.path.join(_HERE, "reference-agx-isa")
DEFAULT_VENDOR = os.environ.get("GPU_WIP_APPLEGPU") or (
    _SIBLING if os.path.isdir(_SIBLING) else
    "/home/doug/Known Good State/firmware/GPU/tools/reference-agx-isa")

# A11's terminator differs from G13's: corpus uses 0x0108, G13 uses 0x0088.
A11_EXTRA_SIGS = [(0xFFFF, 0x0108, "stop/A11")]


def load_applegpu(vendor):
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    import applegpu                                   # noqa: E402
    return applegpu


def build_sigs(applegpu):
    sigs = []
    idx = {}
    for o in applegpu.instruction_descriptors:
        m = o.mask & 0xFFFF
        b = o.bits & 0xFFFF
        if (m, b) not in idx:
            idx[(m, b)] = len(sigs)
            sigs.append({"mask": m, "bits": b, "name": o.name,
                         "g13_short": o.sizes[0], "g13_long": o.sizes[1]})
        else:
            sigs[idx[(m, b)]]["name"] += "|" + o.name
    for m, b, nm in A11_EXTRA_SIGS:
        key = (m, b)
        if key in idx:
            sigs[idx[key]]["name"] += "|" + nm
            continue
        idx[key] = len(sigs)
        sigs.append({"mask": m, "bits": b, "name": nm,
                     "g13_short": 2, "g13_long": 2})
    word_class = collections.defaultdict(list)
    for i, s in enumerate(sigs):
        for w in range(0x10000):
            if (w & s["mask"]) == (s["bits"] & s["mask"]):
                word_class[w].append(i)
    return sigs, word_class


def text_bytes(path):
    """Return the bytes of __TEXT,__text from a Mach-O object."""
    d = open(path, "rb").read()
    magic, _, _, _, ncmds, _ = struct.unpack_from("<6I", d, 0)
    if magic != 0xFEEDFACF:
        return None
    p = 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", d, p)
        if cmd == 0x19:
            nsects = struct.unpack_from("<I", d, p + 64)[0]
            so = p + 72
            for _ in range(nsects):
                sn = d[so:so + 16].rstrip(b"\0")
                sg = d[so + 16:so + 32].rstrip(b"\0")
                size = struct.unpack_from("<Q", d, so + 40)[0]
                foff = struct.unpack_from("<I", d, so + 48)[0]
                if sg == b"__TEXT" and sn == b"__text" and size:
                    return d[foff:foff + size]
                so += 80
        p += cmdsize
    return None


class Model(object):
    FREE = -1

    def __init__(self, corpus, vendor):
        self.applegpu = load_applegpu(vendor)
        self.sigs, self.word_class = build_sigs(self.applegpu)
        self.objects = []
        self.allcls = set()
        files = sorted(f for f in os.listdir(corpus) if f.endswith(".g10p-o"))
        for fn in files:
            b = text_bytes(os.path.join(corpus, fn))
            if not b:
                continue
            words = list(struct.unpack_from("<%dH" % (len(b) // 2), b, 0))
            cands = []
            for w in words:
                ids = self.word_class.get(w)
                cs = ([(i, (w >> 15) & 1) for i in ids] if ids
                      else [(self.FREE, (w >> 15) & 1)])
                cands.append(cs)
                self.allcls.update(cs)
            self.objects.append((fn, words, cands))
        self.allcls = sorted(self.allcls)

    # -- naming ----------------------------------------------------------
    def label(self, cls):
        sid, lb = cls
        if sid == self.FREE:
            return "A11-only"
        return self.sigs[sid]["name"].split("|")[0]

    def key(self, cls):
        sid, lb = cls
        if sid == self.FREE:
            return "A11-only|L%d" % lb
        return "%s|L%d" % (self.sigs[sid]["name"].split("|")[0], lb)

    # -- exact DP --------------------------------------------------------
    def tiles(self, cands, n, length):
        fwd = bytearray(n + 1)
        fwd[0] = 1
        for p in range(n):
            if not fwd[p]:
                continue
            for cls in cands[p]:
                q = p + length[cls]
                if q <= n:
                    fwd[q] = 1
        return bool(fwd[n])

    def count_tiled(self, objects, length):
        return sum(1 for _, w, c in objects
                   if self.tiles(c, len(w), length))

    # -- baseline --------------------------------------------------------
    def baseline(self):
        """The measured baseline: 3 words (6 B) for everything, 1 word for
        trap/stop."""
        length = {}
        for cls in self.allcls:
            sid, lb = cls
            if sid == self.FREE:
                length[cls] = 3
                continue
            nm = self.sigs[sid]["name"].split("|")[0]
            length[cls] = 1 if nm in ("stop", "stop/A11", "trap") else 3
        return length

    # -- minimal-deviation repair ---------------------------------------
    def solve(self, objects, verbose=False):
        length = self.baseline()
        for it in range(20):
            bad = [o for o in objects
                   if not self.tiles(o[2], len(o[1]), length)]
            if not bad:
                break
            best = None
            for cls in self.allcls:
                cur = length[cls]
                for L in UNITS:
                    if L == cur:
                        continue
                    length[cls] = L
                    gain = sum(1 for o in bad
                               if self.tiles(o[2], len(o[1]), length))
                    length[cls] = cur
                    if gain:
                        rank = (-gain, abs(L - cur), self.key(cls), L)
                        if best is None or rank < best[0]:
                            best = (rank, cls, L, gain)
            if best is None:
                break
            _, cls, L, gain = best
            length[cls] = L
            if verbose:
                print("    repair %d: %s = %d words (%d B)  [+%d objects]"
                      % (it, self.key(cls), L, L * 2, gain))
        return length

    # -- structural validation ------------------------------------------
    def alignment_check(self, length):
        """Next function after a terminator should be 64-byte aligned."""
        ok = tot = 0
        for fn, words, _ in self.objects:
            term = [i for i, w in enumerate(words) if w == 0x0108]
            starts = []
            prev = -1
            for t in term:
                s = prev + 1
                while s < t and words[s] in (0x0008, 0x0000):
                    s += 1
                starts.append(s)
                prev = t
            for i in range(len(starts) - 1):
                tot += 1
                if (starts[i + 1] * 2) % 64 == 0:
                    ok += 1
        return ok, tot


def main():
    corpus = DEFAULT_CORPUS
    vendor = DEFAULT_VENDOR
    jsonout = None
    quiet = "--quiet" in sys.argv
    for i, a in enumerate(sys.argv):
        if a == "--corpus":
            corpus = sys.argv[i + 1]
        elif a == "--vendor":
            vendor = sys.argv[i + 1]
        elif a == "--json":
            jsonout = sys.argv[i + 1]

    m = Model(corpus, vendor)
    if not quiet:
        print("corpus: %s" % corpus)
        print("objects: %d   words: %d   signatures: %d"
              % (len(m.objects), sum(len(w) for _, w, _ in m.objects),
                 len(m.sigs)))

    base = m.baseline()
    nbase = m.count_tiled(m.objects, base)
    if not quiet:
        print("\nbaseline (3 words = 6 B, trap/stop = 1 word): "
              "%d / %d objects tile" % (nbase, len(m.objects)))

    tbl = m.solve(m.objects, verbose=not quiet)
    nok = m.count_tiled(m.objects, tbl)
    if not quiet:
        print("\nafter minimal-deviation repair: %d / %d objects tile"
              % (nok, len(m.objects)))

    # ---- cross-validation ---------------------------------------------
    even = [o for i, o in enumerate(m.objects) if i % 2 == 0]
    odd = [o for i, o in enumerate(m.objects) if i % 2 == 1]
    cv = []
    for name, train, test in (("even->odd", even, odd),
                               ("odd->even", odd, even)):
        t = m.solve(train)
        cv.append((name, m.count_tiled(train, t), len(train),
                   m.count_tiled(test, t), len(test)))
    if not quiet:
        print("\n2-fold cross-validation:")
        for name, a, na, b, nb in cv:
            print("   %-10s train %d/%d   held-out %d/%d" % (name, a, na, b, nb))

    # ---- structural validation ----------------------------------------
    ok, tot = m.alignment_check(tbl)
    if not quiet:
        print("\nstructural check: next function 64-byte aligned in %d/%d "
              "(%.1f%%; 3.1%% by chance)" % (ok, tot, 100.0 * ok / tot))

    # ---- forcedness ----------------------------------------------------
    occ = collections.Counter()
    for _, _, cands in m.objects:
        for cs in cands:
            for c in cs:
                occ[c] += 1
    forced = {}
    free = []
    for cls in m.allcls:
        cur = tbl[cls]
        alts = []
        for L in UNITS:
            if L == cur:
                continue
            tbl[cls] = L
            if m.count_tiled(m.objects, tbl) < nok:
                alts.append(L)
            tbl[cls] = cur
        if alts:
            forced[m.key(cls)] = {"words": cur, "bytes": cur * 2,
                                  "occurrences": occ[cls],
                                  "other_lengths_break": alts}
        else:
            free.append((m.key(cls), cur, occ[cls]))

    if not quiet:
        print("\n=== A11 length table ===")
        print("forced by the corpus (changing the length breaks an object):")
        for k in sorted(forced):
            v = forced[k]
            print("   %-28s %d words (%2d B)  x%-7d  alternatives that "
                  "break: %s" % (k, v["words"], v["bytes"], v["occurrences"],
                                 v["other_lengths_break"]))
        print("\nnot individually forced, but 3 words (6 B) is the value that "
              "tilings the corpus:")
        for k, cur, c in sorted(free, key=lambda x: -x[2]):
            print("   %-28s %d words (%2d B)  x%d" % (k, cur, cur * 2, c))

    if jsonout:
        out = {"baseline_words": 3,
               "baseline_bytes": 6,
               "objects": len(m.objects),
               "words": sum(len(w) for _, w, _ in m.objects),
               "objects_tiled": nok,
               "forced": forced,
               "free": [{"class": k, "words": c, "bytes": c * 2,
                         "occurrences": n} for k, c, n in free]}
        with open(jsonout, "w") as f:
            json.dump(out, f, indent=1, sort_keys=True)
        if not quiet:
            print("\nwrote %s" % jsonout)


if __name__ == "__main__":
    main()
