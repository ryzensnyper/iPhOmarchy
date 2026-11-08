#!/usr/bin/env python3
"""Recover the A11/G10P field layout from the framed corpus.

With the length table solved, every instruction in the corpus is exactly
three 16-bit words, so the *layout* can be attacked directly: for every
opcode we can look at all of its occurrences and ask which bits are
constant (opcode / fixed fields) and which vary (operand fields).

Two things are produced:

  1. A per-opcode bit profile: for each of the three words, the mask of
     bits that never change and the mask of bits that do, plus how many
     distinct values each varying bit takes.

  2. A G13-vs-A11 field comparison: `applegpu` declares, for every
     instruction, the fields it extracts (bit start, bit size, name).  For
     each declared field we measure the set of values A11 actually puts
     there.  A field that is constant in A11 is part of the opcode there
     (or a fixed immediate); a field whose value range in A11 differs from
     the G13 descriptor's operand domain is a layout delta.

Usage: g10p_fields.py [--top N] [--op NAME] [--corpus DIR] [--vendor DIR]
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

MASK48 = (1 << 48) - 1


def load_applegpu(vendor):
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    import applegpu
    return applegpu


def text_bytes(path):
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


def main():
    corpus = DEFAULT_CORPUS
    vendor = DEFAULT_VENDOR
    top = 30
    only = None
    bitmode = "--bits" in sys.argv
    summ = "--summary" in sys.argv
    for i, a in enumerate(sys.argv):
        if a == "--corpus":
            corpus = sys.argv[i + 1]
        elif a == "--vendor":
            vendor = sys.argv[i + 1]
        elif a == "--top":
            top = int(sys.argv[i + 1])
        elif a == "--op":
            only = sys.argv[i + 1]

    ag = load_applegpu(vendor)

    # ---- signature dictionary (same as g10p_lengths.py) -----------------
    sigs = []
    idx = {}
    for o in ag.instruction_descriptors:
        m = o.mask & 0xFFFF
        b = o.bits & 0xFFFF
        if (m, b) not in idx:
            idx[(m, b)] = len(sigs)
            sigs.append({"mask": m, "bits": b, "name": o.name, "obj": o})
        else:
            sigs[idx[(m, b)]]["name"] += "|" + o.name
    word_class = collections.defaultdict(list)
    for i, s in enumerate(sigs):
        for w in range(0x10000):
            if (w & s["mask"]) == (s["bits"] & s["mask"]):
                word_class[w].append(i)

    FREE = -1
    allcls = set()
    for fn in sorted(f for f in os.listdir(corpus) if f.endswith(".g10p-o")):
        b = text_bytes(os.path.join(corpus, fn))
        if not b:
            continue
        for w in struct.unpack_from("<%dH" % (len(b) // 2), b, 0):
            ids = word_class.get(w)
            cs = [(i, (w >> 15) & 1) for i in ids] if ids else [(FREE, (w >> 15) & 1)]
            allcls.update(cs)

    length = {}
    for cls in allcls:
        sid, lb = cls
        if sid == FREE:
            length[cls] = 2 if lb == 0 else 1
        else:
            nm = sigs[sid]["name"].split("|")[0]
            length[cls] = 1 if nm in ("stop", "stop/A11", "trap") else 3

    # ---- frame the corpus ------------------------------------------------
    # groups[signature-id][lbit] -> list of 48-bit instruction values
    groups = collections.defaultdict(list)
    a11only = collections.Counter()
    ninstr = 0
    for fn in sorted(f for f in os.listdir(corpus) if f.endswith(".g10p-o")):
        code = text_bytes(os.path.join(corpus, fn))
        if not code:
            continue
        nw = len(code) // 2
        words = list(struct.unpack_from("<%dH" % nw, code, 0))
        cands = []
        for w in words:
            ids = word_class.get(w)
            cands.append([(i, (w >> 15) & 1) for i in ids] if ids
                         else [(FREE, (w >> 15) & 1)])
        # greedy forward walk: at each position take a candidate whose length
        # lands on a reachable position (the table tiles the corpus, so a
        # plain greedy walk with the *first* candidate that fits works).
        p = 0
        reach = {0}
        while p < nw:
            placed = False
            for cls in cands[p]:
                L = length[cls]
                if p + L <= nw:
                    sid, lb = cls
                    if sid == FREE:
                        a11only[words[p]] += 1
                    else:
                        # 48-bit little-endian value of the instruction
                        v = 0
                        for q in range(L):
                            v |= words[p + q] << (16 * q)
                        groups[(sid, lb)].append(v)
                    ninstr += 1
                    p += L
                    placed = True
                    break
            if not placed:
                break
    print("instructions framed: %d" % ninstr)
    print("signature classes with data: %d\n" % len(groups))

    def bitprofile(vals):
        """(constant mask, varying mask, per-bit distinct counts)."""
        if not vals:
            return 0, 0, []
        andv = MASK48
        orv = 0
        for v in vals:
            andv &= v
            orv |= v
        varying = orv ^ andv
        counts = []
        for bit in range(48):
            if varying >> bit & 1:
                counts.append(len({(v >> bit) & 1 for v in vals}))
            else:
                counts.append(0)
        return andv, varying, counts

    def fieldreport(o, vals):
        """For every G13-declared field, measure how A11 actually uses it.

        Verdicts:
          UNUSED   -- the field's bits never change in A11 and are always 0:
                      A11 has no such field at that position.
          FIXED    -- the field is constant but non-zero: A11 folds it into
                      the opcode.
          PARTIAL  -- some bits of the field are always 0.
          USED     -- the field behaves like a live operand field.
          beyond   -- the field does not fit in A11's 3-word instruction.
        """
        out = []
        for start, size, name in o.fields:
            if start + size > 48:
                out.append((name, start, size, 0, "beyond", None))
                continue
            m = (1 << size) - 1
            vs = {((v >> start) & m) for v in vals}
            nd = len(vs)
            lo, hi = min(vs), max(vs)
            used = 0
            for v in vals:
                used |= v
            usedmask = used & (m << start)
            if usedmask == 0:
                verdict = "UNUSED"
            elif nd == 1:
                verdict = "FIXED"
            else:
                # how many of the field's bits are ever set
                nz = bin(usedmask).count("1")
                verdict = "USED" if nz == size else "PARTIAL(%d/%d)" % (nz, size)
            out.append((name, start, size, nd, verdict, (lo, hi)))
        return out

    def bitdetail(vals, lo, hi):
        """Per-bit: number of distinct values and the observed value set."""
        out = []
        for bit in range(lo, hi):
            vs = sorted({(v >> bit) & 1 for v in vals})
            out.append((bit, len(vs), vs))
        return out

    rows = []
    for (sid, lb), vals in groups.items():
        o = sigs[sid]["obj"]
        nm = sigs[sid]["name"].split("|")[0]
        andv, varying, counts = bitprofile(vals)
        rows.append((len(vals), nm, lb, o, vals, andv, varying, counts))
    rows.sort(key=lambda r: -r[0])

    if summ:
        print("=== word0 layout check (bits 0..15) ===")
        # G13 puts, in word0: opcode bits 0..5 (or 0..6), then the operand
        # type / register / flag bits in bits 6..15.  If A11 uses the same
        # header, the varying bits of word0 must always lie in bits 6..15 and
        # the opcode bits must always be constant.
        bad_hdr = []
        hdr_ok = 0
        for n, nm, lb, o, vals, andv, varying, counts in rows:
            v0 = varying & 0xFFFF
            # opcode bits: the G13 mask's low part
            omask = o.mask & 0xFFFF
            low = 0xFFFF
            while low:
                if not (omask & low):
                    break
                low = (low - 1) & 0xFFFF
            op_const = True
            for v in vals:
                if (v & omask) != (o.bits & omask):
                    op_const = False
                    break
            if (v0 & 0x003F) == 0 and op_const:
                hdr_ok += 1
            else:
                bad_hdr.append((nm, n, v0, op_const))
        print("opcodes whose word0 is [constant opcode bits 0..5] + "
              "variable bits 6..15: %d / %d" % (hdr_ok, len(rows)))
        for nm, n, v0, op_const in bad_hdr[:15]:
            print("   %-24s x%-7d word0 vary %04x  opcode-bits-constant=%s"
                  % (nm, n, v0, op_const))

        print("\n=== G13 field layout vs A11, all opcodes ===")
        print("%-24s %-7s %-6s %-6s %-6s %-7s  anomalies"
              % ("opcode", "count", "USED", "UNUSED", "FIXED", "beyond"))
        tot_used = tot_unused = tot_fixed = tot_beyond = tot_all = 0
        for n, nm, lb, o, vals, andv, varying, counts in rows:
            fr = fieldreport(o, vals)
            used = unused = fixed = b48 = 0
            other = []
            for name, start, size, ndist, verdict, rng in fr:
                if verdict == "beyond":
                    b48 += 1
                    continue
                if verdict == "USED":
                    used += 1
                elif verdict == "UNUSED":
                    unused += 1
                elif verdict == "FIXED":
                    fixed += 1
                else:
                    other.append("%s(%s)" % (name, verdict))
            tot_used += used
            tot_unused += unused
            tot_fixed += fixed
            tot_beyond += b48
            tot_all += used + unused + fixed + len(other)
            if other or unused or fixed or b48:
                print("%-24s %-7d %-6d %-6d %-6d %-7d  %s"
                      % (nm, n, used, unused, fixed, b48, ", ".join(other[:6])))
        print("\nG13 fields that are live in A11 at the same position : %d" % tot_used)
        print("G13 fields unused in A11 (A11 has no such field)     : %d" % tot_unused)
        print("G13 fields folded into the A11 opcode (constant)     : %d" % tot_fixed)
        print("G13 fields that do not fit in A11's 3-word insn      : %d" % tot_beyond)
        print("total G13 fields examined                            : %d" % tot_all)
        print("usable verbatim                                     : %.1f%%"
              % (100.0 * tot_used / max(tot_all, 1)))
        return

    shown = 0
    for n, nm, lb, o, vals, andv, varying, counts in rows:
        if only and only not in nm:
            continue
        if not only and shown >= top:
            break
        shown += 1
        print("=== %s (L=%d)  x%d" % (nm, lb, n))
        print("    G13 sizes %s   mask %016x bits %016x"
              % (o.sizes, o.mask, o.bits))
        for wi in range(3):
            lo = andv & (0xFFFF << (16 * wi))
            hi = varying & (0xFFFF << (16 * wi))
            print("    word%d const %04x  vary %04x"
                  % (wi, lo >> (16 * wi), hi >> (16 * wi)))
        fr = fieldreport(o, vals)
        if fr:
            print("    G13 fields as seen in A11 (verdict on A11's use):")
            for name, start, size, ndist, verdict, rng in fr:
                if ndist == "beyond-48":
                    print("       %-22s bit %2d+%2d   beyond 48 bits"
                          % (name, start, size))
                    continue
                print("       %-22s bit %2d+%2d   %3d distinct  %-12s %s"
                      % (name, start, size, ndist, verdict,
                         ("range %d..%d" % rng) if rng else ""))
        if bitmode:
            print("    per-bit (operand words), bit: ndistinct / values:")
            for bit, nd, vs in bitdetail(vals, 16, 48):
                if nd <= 1:
                    continue
                mark = "".join(str(x) for x in vs) if nd <= 8 else "-"
                print("       bit %2d  %2d  %s" % (bit, nd, mark))

    print("\n=== A11-only instruction first words (no G13 signature) ===")
    for w, c in a11only.most_common(30):
        print("    %04x  x%d" % (w, c))


if __name__ == "__main__":
    main()
