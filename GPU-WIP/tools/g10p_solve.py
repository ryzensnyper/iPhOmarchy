#!/usr/bin/env python3
"""Solve the A11 (G10P) instruction-length table from the corpus.

Framing model
-------------
An object is: [instruction]* [padding]*.  An instruction starts with a 16-bit
word and is 2/4/6/8/10/12 bytes long.  The length is a property of the opcode,
so the same opcode value has the same length everywhere in the corpus.

At each position the word is one of:
  * a Mesa signature          -> length fixed by Mesa's rule (short vs long via
                                 the L bit in bit 15, unless the mask carries it)
  * a known A11 opcode        -> fixed length (A11_FIXED / A11_LENGTH_OVERRIDE)
  * an A11-only opcode        -> length unknown, solved for, shared corpus-wide
  * padding (0x0008 run)      -> the remainder of the object must be padding

Solving: objects are framed one by one with DFS; a framing proposes lengths for
the A11-only opcodes it meets; proposals must agree with the lengths already
established elsewhere in the corpus.  Among consistent framings the one with
the fewest distinct A11-only opcodes wins.
"""
import glob
import os
import struct
import sys
from collections import defaultdict

REF = os.environ.get("GPU_WIP_REF", "/home/doug/Known Good State/firmware/GPU/tools/reference-agx-isa")
CORPUS = os.environ.get("GPU_WIP_CORPUS", "/home/doug/Known Good State/firmware/GPU/ds-g10p")
sys.path.insert(0, REF)
import agx_opcodes as A

LENGTHS = (2, 4, 6, 8, 10, 12)
PADDING = {0x0008, 0x0000}


def norm(e):
    if e is None:
        return None
    ls = e.length_short
    ll = getattr(e, "length_long", None)
    if ll is None:
        ll = ls + (4 if (e.extensible and ls > 8) else (2 if e.extensible else 0))
    return (e.exact, e.mask, ls, ll)


def build_mesa():
    out = []
    for name, op in A.opcodes.items():
        e = norm(op.encoding_32)
        if e and e[1]:
            out.append((e[0], e[1], e[2], e[3], name))
        e16 = norm(op.encoding_16)
        if e16 and e16[1]:
            out.append((e16[0], e16[1], e16[2], e16[3], name + "/16"))
    seen = {}
    for e in out:
        seen.setdefault((e[0], e[1]), e)
    return list(seen.values())


MESA = build_mesa()

A11_FIXED = {
    0x0108: 2,   # stop            (Mesa 0x0088)
    0xc020: 6,   # jmp_exec_none   (Mesa 0xc200)
    0x0026: 6,   # fadd16          (Mesa 0x8026; A11 carries no L bit)
    0x0036: 6,   # fma16
    0x0016: 6,   # fmul16
    0x00c2: 4,   # mov_imm family  (opcode byte 0xc2, dest in bits 8-11)
}
A11_OVERRIDE = {
    0x001e: (12,),     # imad          (Mesa: fixed 8)
    0x0071: (6, 12),  # texture_load  (Mesa: 8/10)
}


def mesa_length(word):
    """Fixed length for a Mesa-known word, or None."""
    out = []
    for exact, mask, short, long, _n in MESA:
        if (word & mask) == (exact & mask):
            out.append(long if (mask & 0x8000 and (exact & 0x8000)) else
                       (short if mask & 0x8000 else
                        (long if word & 0x8000 else short)))
    return sorted(set(out))[0] if out else None


def text_words(path):
    d = open(path, "rb").read()
    magic, _, _, _, ncmds, _ = struct.unpack_from("<6I", d, 0)
    if magic != 0xfeedfacf:
        return None
    p = 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", d, p)
        if cmd == 0x19:
            nsects = struct.unpack_from("<I", d, p + 64)[0]
            so = p + 72
            for _ in range(nsects):
                sn = d[so:so+16].rstrip(b"\0")
                sg = d[so+16:so+32].rstrip(b"\0")
                addr, size = struct.unpack_from("<QQ", d, so + 32)
                foff = struct.unpack_from("<I", d, so + 48)[0]
                if sg == b"__TEXT" and sn == b"__text" and size:
                    return list(struct.unpack_from("<%dH" % (size // 2), d, foff))
                so += 80
        p += cmdsize
    return None


def frame(words, known, candidates, newly=None, node_budget=[200000]):
    """Frame one object.

    known:      {opcode_word: pinned length}
    candidates: {opcode_word: set of still-possible lengths} - only these words
                may act as A11-only opcodes; any other unknown word aborts the
                framing (and is reported through `newly`).
    Returns (constraints, score) or None.
    """
    n = len(words)
    best = None
    budget = node_budget[0]

    def rec(pos, cons, newops):
        nonlocal best, budget
        budget -= 1
        if budget <= 0:
            return
        if pos == n:
            cand = (len(newops), len(cons), dict(cons))
            if best is None or cand[:2] < best[:2]:
                best = cand
            return
        if words[pos] in PADDING:
            if all(w in PADDING for w in words[pos:]):
                rec(n, cons, newops)
            return
        w = words[pos]
        if w in A11_FIXED:
            cands, fixed = [A11_FIXED[w]], True
        else:
            ml = mesa_length(w)
            if w in A11_OVERRIDE:
                f = [x for x in ([ml] if ml else []) if x in A11_OVERRIDE[w]]
                cands, fixed = (f or list(A11_OVERRIDE[w])), False
            elif ml is not None:
                cands, fixed = [ml], True
            elif w in candidates:
                cands, fixed = sorted(candidates[w]), False
            else:
                if newly is not None:
                    newly.add(w)
                return
        for ln in cands:
            nxt = pos + ln // 2
            if nxt > n:
                continue
            if fixed:
                rec(nxt, cons, newops)
            else:
                prev = cons.get(w)
                if prev is None:
                    if w in known and known[w] != ln:
                        continue
                    nc = dict(cons)
                    nc[w] = ln
                    no = set(newops)
                    no.add(w)
                    rec(nxt, nc, no)
                elif prev == ln:
                    rec(nxt, cons, newops)

    rec(0, {}, set())
    return best


def main():
    sys.setrecursionlimit(200000)
    verbose = "--verbose" in sys.argv
    limit = None
    for i, a in enumerate(sys.argv):
        if a == "--limit":
            limit = int(sys.argv[i + 1])
    files = sorted(glob.glob(os.path.join(CORPUS, "*.g10p-o")))
    if limit:
        files = files[:limit]

    known = {}
    candidates = defaultdict(set)
    for w in A11_FIXED:
        candidates[w] = {A11_FIXED[w]}
    for w, ls in A11_OVERRIDE.items():
        candidates[w] = set(ls)
    conflict = defaultdict(set)
    framed = []
    unframed = []
    discovered = set()
    block_count = {}

    for round_no in range(6):
        newly = set()
        round_framed = []
        round_unframed = []
        obs = defaultdict(set)
        for f in files:
            words = text_words(f)
            if words is None:
                continue
            best = frame(words, known, candidates, newly)
            name = os.path.basename(f)
            if best is None:
                round_unframed.append(name)
                continue
            round_framed.append(name)
            for k, v in best[2].items():
                if k in A11_FIXED:
                    continue
                obs[k].add(v)
        for w in newly:
            block_count[w] = block_count.get(w, 0) + 1
        for w in list(candidates):
            if w not in A11_FIXED and w not in A11_OVERRIDE and block_count.get(w, 0) < 2:
                del candidates[w]
        discovered |= newly
        for w in newly:
            candidates[w] = set(candidates.get(w, set())) | set(LENGTHS)
        # intersect observed lengths with the candidate sets
        changed = False
        for w, ls in obs.items():
            new = candidates[w] & ls if candidates[w] else ls
            if new and new != candidates[w]:
                candidates[w] = new
                changed = True
            if len(candidates[w]) == 1:
                known[w] = next(iter(candidates[w]))
        framed, unframed = round_framed, round_unframed
        if verbose:
            print("round %d: framed %d, new candidate opcodes: %s" %
                  (round_no, len(framed), [hex(w) for w in sorted(newly)]))
        if not newly and not changed:
            break

    print("framed %d / %d objects" % (len(framed), len(files)))
    if unframed:
        print("unframed (%d): %s" % (len(unframed), ", ".join(unframed[:12])))
    print("\nA11-only opcodes (no Mesa signature) -> candidate lengths:")
    for k in sorted(candidates):
        s = candidates[k]
        if k in A11_FIXED:
            continue
        tag = "PINNED %d" % next(iter(s)) if len(s) == 1 else "AMBIGUOUS %s" % sorted(s)
        print("  %04x : %s" % (k, tag))


if __name__ == "__main__":
    main()
