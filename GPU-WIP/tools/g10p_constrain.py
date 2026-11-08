#!/usr/bin/env python3
"""Solve the A11/G10P framing with branch-target constraints.

Motivation
----------
The exact-DP tiling solver answers "can this object be tiled?", which leaves
a lot of slack: many different length assignments tile every object.  The
branch instructions remove that slack.  `jmp_exec_any` (0xc000),
`jmp_exec_none` (0xc020) and `call` (0xc010) carry a 32-bit sign-extended
*byte* offset (`next_pc = pc + sign_extend(off, 32)`), so each branch names
an exact position that **must be an instruction boundary**.

Those positions are independent of the framing, so they are hard constraints
on the segmentation.  With ~13 000 branches over the corpus they over-determine
it.

Algorithm
---------
1.  Frame every object with the current length table.
2.  For every branch, compute its target word index.  If the target is not a
    boundary, the instruction that covers the target is too long: the
    constraint is "the class of that instruction has length
    (target - start) words".
3.  Apply the constraints, re-frame, repeat until stable.
4.  Report the branch-target hit rate (the objective) and the resulting
    per-opcode length table.

The length model is *per opcode*: every distinct first word that can start
an instruction gets its own length, so A11-only opcodes are not lumped
together.

Usage: g10p_constrain.py [--corpus DIR] [--vendor DIR] [--iters N]
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
NAMED_FIXED = ("stop", "stop/A11", "trap")


def main():
    corpus = DEFAULT_CORPUS
    vendor = DEFAULT_VENDOR
    iters = 12
    for i, a in enumerate(sys.argv):
        if a == "--corpus":
            corpus = sys.argv[i + 1]
        elif a == "--vendor":
            vendor = sys.argv[i + 1]
        elif a == "--iters":
            iters = int(sys.argv[i + 1])
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

    # ---- class table ----------------------------------------------------
    # class key: ("N", sigid, lbit) for a G13 signature, ("A", word) for an
    # A11-only opcode.
    length = {}

    def cls_name(c):
        if c[0] == "A":
            return "A11-only:%04x" % c[1]
        return sigs[c[1]]["name"].split("|")[0]

    def default_len(c):
        if c[0] == "A":
            return 3          # uniform 6-byte quantum (measured)
        nm = sigs[c[1]]["name"].split("|")[0]
        return 1 if nm in NAMED_FIXED else 3

    seen = set()
    for fn, words, cands in objects:
        for cs in cands:
            for c in cs:
                if c not in seen:
                    seen.add(c)
                    length[c] = default_len(c)

    def frame(words, cands):
        """Greedy walk; returns (starts, seq) or None if it cannot complete."""
        n = len(words)
        starts = set()
        seq = []
        p = 0
        while p < n:
            placed = False
            for c in cands[p]:
                L = length[c]
                if p + L <= n:
                    starts.add(p)
                    seq.append((p, c, L))
                    p += L
                    placed = True
                    break
            if not placed:
                return None
        return starts, seq

    def branch_stats(framed):
        tot = hit = 0
        for fn, words, seq, starts in framed:
            n = len(words)
            for p, c, L in seq:
                if c[0] == "A" or words[p] not in BRANCH or p + 3 > n:
                    continue
                off = words[p + 2]
                if off & 0x8000:
                    off -= 1 << 16
                t = p + off // 2
                tot += 1
                if 0 <= t < n and t in starts:
                    hit += 1
        return hit, tot

    print("classes: %d (G13 %d, A11-only %d)"
          % (len(length),
             sum(1 for c in length if c[0] != "A"),
             sum(1 for c in length if c[0] == "A")))

    framed = []
    for fn, words, cands in objects:
        f = frame(words, cands)
        framed.append((fn, words, cands, f))
    hit, tot = branch_stats([(a, b, d[1], d[0]) for a, b, c, d in framed
                             if d is not None])
    print("iteration 0: branch targets on a boundary: %d / %d (%.1f%%)"
          % (hit, tot, 100.0 * hit / max(tot, 1)))

    # ---- constraint propagation -----------------------------------------
    for it in range(iters):
        constraints = collections.defaultdict(collections.Counter)
        for fn, words, cands, f in framed:
            if f is None:
                continue
            starts, seq = f
            n = len(words)
            for p, c, L in seq:
                if c[0] == "A" or words[p] not in BRANCH or p + 3 > n:
                    continue
                off = words[p + 1] | (words[p + 2] << 16)
                if off & 0x80000000:
                    off -= 1 << 32
                t = p + off // 2
                if not (0 <= t < n) or t in starts:
                    continue
                # the instruction covering the target must end exactly there
                b = max(s for s in starts if s <= t)
                bc = None
                for q, cc, LL in seq:
                    if q == b:
                        bc = cc
                        break
                if bc is not None:
                    constraints[bc][t - b] += 1
        if not constraints:
            print("iteration %d: no new constraints" % it)
            break
        changed = 0
        conflicts = 0
        for c, cnt in constraints.items():
            L, votes = cnt.most_common(1)[0]
            if len(cnt) > 1:
                conflicts += 1
                continue          # contradictory evidence -> leave alone
            # Only the A11-only opcodes are in doubt: the named opcodes'
            # lengths are pinned by the repetition-period evidence and must
            # not be moved by this propagation.
            if c[0] != "A":
                continue
            if length[c] == L:
                continue
            length[c] = L
            changed += 1
        framed = []
        for fn, words, cands in objects:
            framed.append((fn, words, cands, frame(words, cands)))
        hit, tot = branch_stats([(a, b, d[1], d[0]) for a, b, c, d in framed
                                 if d is not None])
        nfail = sum(1 for a, b, c, d in framed if d is None)
        ntile = sum(1 for a, b, c, d in framed if d is not None)
        print("iteration %d: %d classes constrained (%d conflicting), "
              "%d objects untileable; branch targets %d/%d (%.1f%%)"
              % (it, len(constraints), conflicts, nfail, hit, tot,
                 100.0 * hit / max(tot, 1)))
        if not changed:
            break

    final_hit, final_tot = hit, tot

    # ---- per-branch-opcode offset-field sweep ------------------------------
    layouts = {
        "w1": lambda w1, w2: w1,
        "w2": lambda w1, w2: w2,
        "w1|w2<<16": lambda w1, w2: w1 | (w2 << 16),
        "w1<<16|w2": lambda w1, w2: (w1 << 16) | w2,
        "w2|w1<<16": lambda w1, w2: w2 | (w1 << 16),
        "w2<<16|w1": lambda w1, w2: (w2 << 16) | w1,
    }
    print("\n=== per-branch-opcode offset-field sweep ===")
    for bname in sorted(BRANCH.values()):
        best = []
        for lname, lfn in layouts.items():
            for uname, scale in (("word", 1), ("byte", 2), ("6B-insn", 6)):
                for base in (0, 1):
                    tot = hit = 0
                    for fn, words, cands, f in framed:
                        if f is None:
                            continue
                        starts, seq = f
                        n = len(words)
                        for p, c, L in seq:
                            if c[0] == "A" or words[p] not in BRANCH or p + 3 > n:
                                continue
                            if BRANCH[words[p]] != bname:
                                continue
                            off = lfn(words[p + 1], words[p + 2])
                            if off & 0x8000:
                                off -= 1 << 16
                            tot += 1
                            if off % scale:
                                continue
                            t = p + (L if base else 0) + off // scale
                            if 0 <= t < n and t in starts:
                                hit += 1
                    if tot:
                        best.append((100.0 * hit / tot, hit, tot, lname, uname,
                                     "next" if base else "pc"))
        best.sort(reverse=True)
        if not best:
            continue
        print("   %s:" % bname)
        for pct, hit, tot, lname, uname, bnm in best[:8]:
            print("      field %-10s unit %-7s from %-5s : %5d / %5d (%.1f%%)"
                  % (lname, uname, bnm, hit, tot, pct))

    # ---- offset modulus per branch opcode, using each opcode's best field --
    BESTFIELD = {"jmp_exec_none": 2, "jmp_exec_any": 1, "call": 1}
    print("\n=== branch-offset modulus per branch opcode (best field) ===")
    for bname, wi in BESTFIELD.items():
        hist = collections.Counter()
        tot = 0
        for fn, words, cands, f in framed:
            if f is None:
                continue
            starts, seq = f
            n = len(words)
            for p, c, L in seq:
                if c[0] == "A" or words[p] not in BRANCH or p + 3 > n:
                    continue
                if BRANCH[words[p]] != bname:
                    continue
                off = words[p + wi]
                if off & 0x8000:
                    off -= 1 << 16
                hist[off % 6] += 1
                tot += 1
        if not tot:
            continue
        print("   %-14s (field word %d)  n=%d" % (bname, wi, tot))
        for r in sorted(hist):
            print("      off %% 6 == %d : %5d (%.1f%%)" % (r, hist[r],
                                                          100.0 * hist[r] / tot))

    # ---- context for the jmp_exec_any misses --------------------------------
    print("\n=== context: jmp_exec_any misses (offset from word 1) ===")
    shown = 0
    for fn, words, cands, f in framed:
        if f is None:
            continue
        starts, seq = f
        n = len(words)
        seqmap = {q: (cc, LL) for q, cc, LL in seq}
        for p, c, L in seq:
            if c[0] == "A" or words[p] != 0xC000 or p + 3 > n:
                continue
            off = words[p + 1]
            if off & 0x8000:
                off -= 1 << 16
            t = p + off // 2
            if 0 <= t < n and t in starts:
                continue
            if shown >= 6:
                break
            shown += 1
            print("   %-32s @word %-6d c000 off(w1)=%-7d target=%d"
                  % (fn[:32], p, off, t))
            lo = max(0, p - 6)
            line = []
            for q in range(lo, min(n, p + 7)):
                mark = "*" if q == p else (" " if q in starts else "-")
                line.append("%04x%s" % (words[q], mark))
            print("      " + " ".join(line))
            print("      (* = branch, space = instruction start, - = inside)")

    # ---- per-branch-opcode breakdown --------------------------------------
    bo = collections.Counter()
    bh = collections.Counter()
    bmiss = collections.defaultdict(list)
    for fn, words, cands, f in framed:
        if f is None:
            continue
        starts, seq = f
        n = len(words)
        for p, c, L in seq:
            if c[0] == "A" or words[p] not in BRANCH or p + 3 > n:
                continue
            off = words[p + 2]
            if off & 0x8000:
                off -= 1 << 16
            t = p + off // 2
            nm = BRANCH[words[p]]
            bo[nm] += 1
            if 0 <= t < n and t in starts:
                bh[nm] += 1
            elif len(bmiss[nm]) < 4:
                bmiss[nm].append((fn, p, words[p], off, t, n))
    print("\n=== branch targets on a boundary, per branch opcode ===")
    hmod = collections.defaultdict(collections.Counter)
    mmod = collections.defaultdict(collections.Counter)
    for fn, words, cands, f in framed:
        if f is None:
            continue
        starts, seq = f
        n = len(words)
        for p, c, L in seq:
            if c[0] == "A" or words[p] not in BRANCH or p + 3 > n:
                continue
            bnm = BRANCH[words[p]]
            off = words[p + 2]
            if off & 0x8000:
                off -= 1 << 16
            t = p + off // 2
            if 0 <= t < n and t in starts:
                hmod[bnm][off % 6] += 1
            else:
                mmod[bnm][off % 6] += 1
    for nm in sorted(bo):
        print("   %-14s %6d / %6d (%.1f%%)" % (nm, bh[nm], bo[nm],
                                               100.0 * bh[nm] / bo[nm]))
        for tag, h in (("hits", hmod[nm]), ("misses", mmod[nm])):
            if not h:
                continue
            print("        %-7s off%%6: %s" % (tag, ", ".join(
                "%d:%d" % (r, h[r]) for r in sorted(h))))
        for fn, p, w, off, t, n in bmiss[nm]:
            print("      miss: %-30s @word %-6d %04x off=%-6d target=%d (n=%d)"
                  % (fn[:30], p, w, off, t, n))

    # ---- how are branch offsets distributed? ----------------------------
    modhist = collections.Counter()
    offcount = 0
    for fn, words, cands, f in framed:
        if f is None:
            continue
        starts, seq = f
        n = len(words)
        for p, c, L in seq:
            if c[0] == "A" or words[p] not in BRANCH or p + 3 > n:
                continue
            off = words[p + 2]
            if off & 0x8000:
                off -= 1 << 16
            offcount += 1
            modhist[off % 6] += 1
    print("\n=== branch offset (third word, 16-bit) modulo 6 ===")
    for r in sorted(modhist):
        print("   off %% 6 == %d : %6d (%.1f%%)" % (r, modhist[r],
                                                   100.0 * modhist[r] / offcount))


    # ---- branch-offset interpretation sweep on the final framing --------
    print("\n=== branch-offset interpretation sweep (final framing) ===")
    layouts = {
        "w1|w2<<16": lambda w1, w2: w1 | (w2 << 16),
        "w1<<16|w2": lambda w1, w2: (w1 << 16) | w2,
        "w2|w1<<16": lambda w1, w2: w2 | (w1 << 16),
        "w2<<16|w1": lambda w1, w2: (w2 << 16) | w1,
        "w1 only16": lambda w1, w2: w1,
        "w2 only16": lambda w1, w2: w2,
    }
    results = []
    for lname, lfn in layouts.items():
        for uname, scale in (("word", 1), ("byte", 2), ("6B-insn", 6)):
            for base in (0, 1):
                tot = hit = 0
                for fn, words, cands, f in framed:
                    if f is None:
                        continue
                    starts, seq = f
                    n = len(words)
                    for p, c, L in seq:
                        if c[0] == "A" or words[p] not in BRANCH or p + 3 > n:
                            continue
                        off = lfn(words[p + 1], words[p + 2])
                        if off & 0x80000000:
                            off -= 1 << 32
                        tot += 1
                        if off % scale:
                            continue
                        t = p + (L if base else 0) + off // scale
                        if 0 <= t < n and t in starts:
                            hit += 1
                if tot:
                    results.append((100.0 * hit / tot, hit, tot,
                                    lname, uname, "next" if base else "pc"))
    results.sort(reverse=True)
    for pct, hit, tot, lname, uname, bname in results[:12]:
        print("   field %-10s unit %-7s from %-5s : %6d / %6d (%.1f%%)"
              % (lname, uname, bname, hit, tot, pct))

    # ---- report ----------------------------------------------------------
    print("\n=== resulting length table ===")
    counts = collections.Counter()
    for fn, words, cands, f in framed:
        if f is None:
            continue
        for p, c, L in f[1]:
            counts[(cls_name(c), L)] += 1
    for (nm, L), c in sorted(counts.items(), key=lambda kv: -kv[1]):
        print("   %-24s %d words (%2d B)  x%d" % (nm, L, L * 2, c))

    # ---- write a table file ---------------------------------------------
    tbl = {}
    for c, L in length.items():
        tbl[cls_name(c)] = L
    used = {}
    for fn, words, cands, f in framed:
        if f is None:
            continue
        for p, c, L in f[1]:
            k = cls_name(c)
            e = used.setdefault(k, {"words": L, "bytes": L * 2, "occurrences": 0})
            e["occurrences"] += 1
    import json
    _here = os.path.dirname(os.path.abspath(__file__))
    _kb = os.path.join(os.path.dirname(_here), "kb")
    out = os.path.join(_kb if os.path.isdir(_kb) else _here,
                        "A11-GPU-G10P-LENGTHS.json")
    with open(out, "w") as f:
        json.dump({
            "model": "uniform 6-byte (3 x 16-bit word) instruction; "
                     "trap/stop 2 bytes; A11-only opcodes 6 bytes unless "
                     "listed below",
            "instruction_bytes": 6,
            "instruction_words": 3,
            "objects": len(objects),
            "words": sum(len(w) for _, w, _ in objects),
            "objects_tiled": sum(1 for a, b, c, d in framed if d is not None),
            "branch_target_hit_rate": (final_hit / final_tot
                                       if final_tot else 0),
            "branch_targets_on_boundary": final_hit,
            "branch_targets_tested": final_tot,
            "branch_offsets": {"total": offcount,
                               "multiple_of_6": modhist.get(0, 0),
                               "multiple_of_6_fraction":
                                   (modhist.get(0, 0) / offcount) if offcount else 0},
            "branch_offset_semantics":
                "16-bit sign-extended byte offset; target = "
                "instruction_address + offset.  Field position is "
                "per-opcode: jmp_exec_none (0xc020) uses the THIRD word "
                "(bits 32..47) and hits 100% of its targets; call (0xc010) "
                "uses the SECOND word (bits 16..31) and hits 100% of its "
                "(4) targets; jmp_exec_any (0xc000) does not match either "
                "and remains unresolved.",
            "used_classes": used,
            "classes": tbl,
        }, f, indent=1, sort_keys=True)
    print("\nwrote %s" % out)


if __name__ == "__main__":
    main()
