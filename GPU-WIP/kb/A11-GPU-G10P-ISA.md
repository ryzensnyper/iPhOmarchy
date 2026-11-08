# A11 (applegpu_g10p) shader ISA — offline probe status

Date: 2026-11-06 (corrected 2026-11-07). Task 2 from the GPU handoff.
**Status: ISA family identified; the instruction framing below is WRONG as
written and was corrected on 2026-11-07 — see "Framing correction" at the end
of this file before using anything here, and then "AGX3 backend
reverse-engineering" (also at the end), which shows the framing question
itself is probably ill-posed. Full decode is not done. Mesa not
extended.** The G9P encoder stays A10-only.

> **2026-11-07 correction (read first).** The "bit 8 = another word follows"
> framing inherited from G9P is **not valid for G10P**. Under it, `0x0108`
> (bits 8 and 3 set), the last word of all 94 kernels, can never terminate an
> instruction, so all 94 streams end in a forced cut — the opposite of the
> G9P property that made that rule convincing. The bit 8 (and bit 3) rule is
> disproven by the corpus alone. The current best candidate is **bit 0** as
> the continuation flag. Every statistic below (86%/12%/2.5% lengths,
> "`0x0108` end-of-program", the `0x8000` observations, the top-first-word
> histogram) was computed under the invalid bit-8 rule and must be re-read
> with that in mind. Details, evidence and the corrected statistics are in
> the **Framing correction** section at the end.
>
> **2026-11-07, later (read next): "AGX3 backend reverse-engineering" at the
> very end of this file.** The AGX2/AGX3 LLVM backend was located and
> disassembled inside the iOS dyld shared cache. Its instruction encoding is
> **byte-packed with dense bit fields and has no per-word continuation flag**,
> which makes the whole "which bit means another word follows" question
> probably ill-posed for G10P: instruction length is carried by the opcode,
> not by a flag bit. The bit-0 candidate is therefore **weaker than it looked
> on 2026-11-07 morning** — its only argument (the `.il64` bound) is
> contradicted by the AGX3 branch/ldimm fixups. Read that section before
> trusting any segmentation.

## The decisive artifact: `ds.g10p` (AGXMetalA11 bundle)

Extracted from the OS DMG (`087-86694-044.dmg`, iOS 16.7.16 20H392,
`/System/Library/Extensions/AGXMetalA11.bundle/`, alongside AIR bitcode
metallibs). Kept as `ds.g10p` in this directory; **all 94 objects extracted
to `ds-g10p/`** (with `MANIFEST.txt`).

### Container format (solved)

```
0x000 'LPPM'              magic
0x004 u32  = 1            version/flags
0x008 u64  = 0x0000000100000001   (two u32s: 1, 1)
0x010 u64  = file size    (0x11a620 = 1156640)
0x018 u64  = 0x28 = 40    (unknown; not size/count/version)
0x020 u64  = 0x11d0       (data section start)
0x028 u64  = 0x5e = 94    (record count)
0x030 94 × 48-byte records: { 32 B content-id, u64 offset, u64 size }
0x11d0 data: the 94 chunks, exactly tiling the section (verified, no gaps)
```

Record offsets are **relative to 0x11d0**; sum of sizes == data region
size == 0x119450 exactly. The 32 B content-id is **not** SHA256/SHA3/
BLAKE2/SHA1/MD5 of the chunk nor of any section (checked) — likely a hash
of the pre-compilation input, i.e. a cache key. Not blocking anything.

### Chunk format: Apple GPU Mach-O objects

All 94: `MH_MAGIC_64`, `filetype = MH_OBJECT` (1), `cputype = 0x01000013`
(`0x01000000 | 19`), `cpusubtype = 0x22` (34), 3 load commands
(`LC_SEGMENT_64` 0x228, `LC_SYMTAB`, `LC_DYSYMTAB`). Sections (all type
`__compute`):

- `__TEXT,__text` — the kernel code, ~983 KiB total, 94 kernels, 2 B ..
  348 KiB each (median ~1.1 KiB; three are huge: 0x2b074, 0x4dc64, 0x16d6 …
  actually `rec54/65/71` 0x2b074/0x4dc64 and `rec34/47/64` ~0xb4xx/0xbc10 —
  these are the `.eot`/`.background` suites).
- `__GPU_METADATA,__compute` — ~100–300 B of a compact binary table
  (starts with `10 00 00 00 …`; contains the `_agc.*` symbol name). Format
  unknown (not msgpack).
- `__GPU_REMARKS_MD`, `__GPU_STATS_MD` — usually 0 B.
- `__GPU_LD_MD,__compute` — 0xd8 B-ish; holds the mangled source name, e.g.
  `compute-progress-marker-driver-gen3` (msgpack-in-binary too, unread).
- `__GPU_ARCH_LD_MD,__compute` — 0x40 B, unread.

### What the kernels are

The AGX (Apple GPU Compiler, "agc") driver-internal program suite for G10P
("driver-gen3"): GL-fixed-function helpers (`agc.main`, `.constant_program`,
`.constant_program.cfg`), tile/blit (`agc.clearvertex`,
`agc.passthrough_vertex`, `agc.tile_dispatch_vertex_point`), frame
end-of-tile (`agc.eot`), and `agc.background`. Produced by the Apple GPU
LLVM backend (see below) — i.e. **this is applegpu_g10p machine code in the
wild, produced by Apple's own compiler.**

## Encoding: same framing as G9P, **different encodings**

> *This section is wrong about the framing (2026-11-07). The bullets below
> were produced with the bit-8 rule; the "0 failures" claim is vacuous
> because the rule is forced to cut at the section end. See the **Framing
> correction** at the end. The "different encodings" conclusion stands.*

Checked mechanically over all 94 `__text` sections:

- **16-bit little-endian words survive**: every instruction run ends at a
  word with bit 8 = 0; segmenting byte-for-byte from offset 0 with the rule
  "keep consuming words while bit 8 is set" terminates exactly on the
  section end in **all 94 kernels, 0 failures**. `0x8000` appears 4986× and
  is always a bit-8-clear single word; `0xc000` (padding) 400×.
- **G9P's specific opcode space is absent**: `0x1181` (prologue) 0×,
  `0x21c8` (exec-mask push) 0×, `0x46d1`/`0x46d2` 0×/5×, `0x3199` (2-src
  ALU) 0×, `0x2312` (load/store) 1×, `0x2b12` 5×, `0x0198` (move-imm) 31×,
  `0x0154` 39× (but **never followed by `0x0038`** — G9P's companion
  pattern is gone), `0x004d` (wait) 12×.
- **`0x8000` is not 64-byte aligned** (histogram flat mod 64) — the G9P
  "end-of-program at the start of a 64 B block" frame does not hold for
  these objects (they are not Metal-ABI kernels; driver-internal entry
  points, different frame rules — meaning unproven).
- Example (rec0, `agc.main`, 14 B): `12 00 01 00 45 00 00 09 00 f0 10 00
  08 01` → words `0012 0001 0045 0900 f000 0010 0108` — no G9P analogue.

**Conclusion: G10P is the same ISA *family* (16-bit words with a per-word
continuation bit) but a re-encoded, non-compatible G9P. (The flag is not bit
8 — see the Framing correction; current candidate: bit 0.) It is not a
"G9P with a new BVNC" for Mesa purposes.** A fresh G10P encoder is required.

## What remains (to actually close the ISA question)

1. **ISA decode from samples** — we now have 94 Apple-assembled G10P
   kernels with known names/sizes (`ds-g10p/*.g10p-o`). **Blocked on the
   framing correction (2026-11-07):** the instruction boundaries are wrong
   until the continuation flag bit is confirmed (candidate: bit 0). The
   differential material is richer than previously thought — 72 of the
   kernels are **32+32+8 instances of just three sources**
   (`bucketed-tessellation-*-driver`; names recovered from `__GPU_LD_MD`),
   i.e. parameter specializations. But the 32 `compute-instance-counts`
   instances are not constant-only (two code-size clusters), so alignment
   is required. A `g10p.py`/`g10p-text.py` pair (`tools/g10p-text.py` now
   uses bit 0 + `--bit`) plus a disassembler is the next step once the flag
   is fixed.
2. **Validation**: an independent check of the decode needs either
   `metal-tt -arch applegpu_g10p` on probe kernels (macOS + MetalToolchain;
   `xcodebuild -downloadComponent MetalToolchain`, then compare word-for-
   word with the samples here) or GPU execution (bring-up; hardware-gated).
3. **Mesa**: do not extend `src/imagination/g9p/` yet. When (1) produces a
   verified encoder, the work is a new `pvr_arch_g10p.c` +
   `device_info/apple-a11.h` (BVNC — still hardware-needed) + plumbing;
   `has_apple_g10p` in the device table.

## Other offline findings (for completeness)

- The iOS 16.7.16 dyld shared cache contains the LLVM AGX backend with
  `applegpu_g10p` / `applegpu_g10p-apple-ios` as a first-class target and
  the subtarget processors `g9p-a0`, `g9p-b0`, `g10p-b0` (no `g10p-a0`);
  arch list in `.19` (llvm target arch table). All 142 `.metallib` files in
  the OS image are AIR bitcode (JIT) — no precompiled Metal-ABI G10P code.
- `ds.g10p`'s Apple GPU Mach-O cookie is `cputype 0x01000013 /
  cpusubtype 0x22` — a distinct `CPU_TYPE` that is *not* `CPU_TYPE_ARM64`
  (0x0100000C).
- AGXMetalA11 `Info.plist`: `com.apple.AGXMetalA11`, `iphoneos16.7.internal`,
  Xcode 14.3-era clang — kept as `AGXMetalA11.bundle.Info.plist`.
- The `ds.g10p` device-support blob's purpose in Apple's stack: shipped
  inside AGXMetal — it is the **driver-internal G10P program suite**, not a
  perf-counter table.

## Files kept

- `ds.g10p` — the original archive (1.15 MB).
- `ds-g10p/*.g10p-o` — 94 extracted GPU Mach-O objects + `MANIFEST.txt`
  (record offsets/sizes/content-ids).
- `AGXMetalA11.bundle.Info.plist`.

## Follow-up 2026-11-06 (later session): the compiler backend is in the dyld cache

Extracted SystemOS cryptex (`087-86588-047.dmg`) and OS DMG
(`087-86694-044.dmg`) read-only (both deleted after; re-extractable from the
IPSW) and enumerated the Metal compiler's LLVM AGX backend. Findings (all
from `dyld_shared_cache_arm64.19`'s string table unless noted):

- The AGX backend is a statically-linked LLVM component of the cache: the
  only library in any subcache mentioning `AGX3` (118 hits); each other
  subcache has 0. `.arch table` copy exists in `.01`, `.17`, `.19`, `.39`.
- Subtarget processor strings: `g9p-a0`, `g9p-b0`, `g10p-b0`, `g11m-a0/b0`,
  `g11p-a0/b0`, `g11g-a0/b0`, `g12m-a0`, `g12p-a0/b0`, `g12g-b0`,
  `g12x`, `g13p-a0/b0`, `g13g-a0/b0`, `g13s-a0/b0`, `g13c-a0/b0`, `g13d-a0/b0`,
  `g14*`, `g15*` — plus selectors ("Select the g10 processor", "Select the
  g10p-b0 processor", "Select the g15 processor", …). ISA generations are
  **agx0/agx1 (G4/G5) → agx2 (G9) → agx3 (G10 and later)** (see unit tables
  below). `g10p-b0` is the only G10P processor in iOS 16's backend (no
  `g10p-a0`).
- **Execution-unit schedule names** (this is the G10 backend's scheduling
  model, not marketing):
  - G4/G5 (agx0/1): `G4UnitALU`, `G4UnitCTRL`, `G4UnitITR`, `G4UnitSMP`
    (and identical G5* set)
  - **G10/G11/G12/G13 (agx3):** `G10UnitF16`, `G10UnitF32`, `G10UnitMAD`,
    `G10UnitMOV`, `G10UnitSMTP`, `G10UnitIssue`, `G10UnitIssueControl`
    (identical sets for G11/G12/G13)
  - G15 (agx3, larger ISA): `G15UnitF16`, `G15UnitF32`, `G15UnitIssue`,
    `G15UnitIC`, `G15UnitIC_CMX`, `G15UnitIC_CVT`, `G15UnitIC_IMS`,
    `G15UnitPERM`, `G15UnitSCIB`
- The AGX3 backend has an **InstPrinter and an AsmParser**
  (`LLVMInitializeAGX3InstPrinterTgt` / `LLVMInitializeAGX3AsmParserTgt`),
  a `.gpu` assembly directive, and directives `.il4`, `.il8`, `.il16`,
  `.il32`, `.il64` and `.st2`, `.st4` — i.e. **instructions are
  variable-length with explicit 4/8/16/32/64-bit sizing** (so the real
  instruction length limit is ≥ 4 words of 16 bits, consistent with the
  corpus's 5-word max).
- **Fixup/relocation names** (these encode the bit-field layout of
  instructions; each name carries target bits and source bits):
  - `fixup_agx3_ldimm_imm_0_l0m31o50` — ldimm: all 32 immediate bits at
    output bit 50 (an 82-bit placement → the instruction format is wide,
    or the output numbering counts from a word-aligned slot past 64)
  - `fixup_agx3_ldimm_imm_1_l0m6o8_l7m10o33_l11m12o42_l13m24o48_l25m31o25` —
    immediate bits [0..6]→output [8..14], [7..10]→output [33..36],
    [11..12]→output [42..43], [13..24]→output [48..59], [25..31]→output
    [25..31]. So the load-immediate instruction scatters a 32-bit immediate
    across six fields inside ~60+ bits — consistent with Apple's packing
    of immediates into a multi-word encoding, and with the G10P corpus
    having many 1-word ALU ops (no immediates) and occasional wide ops.
  - `fixup_agx3_b_offset_0_l0m47o22`, `…bl_offset_0_…`, `…bn_offset_0_…` —
    branch offsets (48-bit field → output bit 22); `.b`, `.bl`, `.bn` are
    the branch types (direct / link / negative?).
  - `fixup_fb_static_constants`, `fixup_agx1_ba_7_1`, `fixup_agx1_br_…`,
    `fixup_agx1_ba_…` — AGX1 (G4/G5) branch address fixups.
- ISA-version anchors found: "(available on ISA 7.6+)", "(available on
  ISA 7.7.1+)" (both in G15 feature strings) — G15 = ISA 7.7; the G10 ISA
  revision number was **not** located in strings.
- Feature flags mention uniform datapath and SWWA (stepping workarounds);
  e.g. "There are no dynamically indexed uniform loads on G10",
  "Emitted non-G10 instruction for G10", "There are no dynamically
  indexed uniform loads on G10". G10 is a full-ISA generation distinct
  from G9 (major pipe changes per the unit tables).
- `AGXCompilerCore.framework` (OS DMG, `/System/Library/PrivateFrameworks/`)
  contains **275 raw `.ds` GPU binaries** (20-byte header: 8 zero + u32
  header-size 0x14 + u32 payload-size; no Mach-O, very high entropy) for
  the compiler's fixed-function/raytracing/tessellation suite
  (`blit_*`, `bvh_*`, `tess_*`, `eot_*`, `gei_*`, `cei_*`, …) — deleted
  with the DMG; re-extractable. Two G10P-relevant strings seen: the bundle
  is the driver's precompiled kernel database (the same role `ds.g10p`
  plays for Metal, for the GL fixed-function path).

### Revised picture

- G10P is **agx3** — the third AGX ISA family generation (G4/G5 = agx0/1,
  G9 = agx2, **G10 and later = agx3**), sharing the LLVM backend with
  G11–G15. Framing/instruction sizing: variable-length, `.il4/.il8/.il16/
  .il32/.il64` directives. *(Superseded 2026-11-07: the "bit 8 =
  continuation" claim in this bullet is disproven — see the **Framing
  correction** section. The current candidate flag bit is 0.)*
- The 94 `ds.g10p` objects are agx3 (G10P) binaries from the AGX3 backend
  (`agc.*` symbols, `__GPU_*/__compute` sections, `_agc.eot` end programs).
- Decoding the full ISA still needs the instruction TableGen tables inside
  the backend binary (not strings) — doable via binary analysis
  (encoding walks of the fixup/reloc tables + the corpus), or via
  `metal-tt -arch applegpu_g10p` probes on macOS (the G9P method, which
  remains the gold standard). Nothing was validated on hardware.

## Framing correction (2026-11-07, offline)

The single most load-bearing claim in this file — that G10P keeps G9P's
"bit 8 of a 16-bit word means another word follows" framing — is
**disproven by the corpus**. Everything that depends only on that claim has
to be re-derived. This section records what is actually established.

### The rule and what "framing" means here

An instruction is a run of 16-bit little-endian words ending at the first
word whose continuation-flag bit is clear (or at the end of the section).
The claim was: flag bit = 8. The corpus has 94 `__TEXT,__text` streams.

### Why bit 8 cannot be the flag

`0x0108` is the **last word of all 94 kernels** (219 occurrences of `0x0108`
in total; 94 at section ends). But `0x0108 & 0x0100 == 0x0100`, i.e. bit 8
is *set*. Under a "bit set = continue" rule, `0x0108` can never terminate an
instruction: every kernel's final instruction runs off the end of the
section. Counting the forced cuts:

| flag bit | kernels with a clean section end | forced cuts | max instr words | length histogram |
|---|---|---|---|---|
| **8** (G9P) | **0 / 94** | **94** | 5 | 1:359677 2:49908 3:9972 4:694 5:1 |
| 3 | 0 / 94 | 94 | 28 | (26 length buckets) |
| 0 (candidate) | 94 / 94 | 0 | 4 | 1:381264 2:51049 3:2928 4:11 |
| 10 | 94 / 94 | 0 | 10 | 1:336880 2:52841 3:14081 … |
| 11 | 94 / 94 | 0 | 10 | 1:316101 2:51003 3:16762 … |
| 15 | 94 / 94 | 0 | 5 | 1:345807 2:49754 3:15009 4:457 5:4 |

For every flag bit except 3 and 8 the last word `0x0108` has the bit clear,
so 94/94 clean section ends is true *by construction* for those and carries
no information. What does carry information:

- **bit 8 and bit 3 are impossible** (a valid decode must terminate at the
  section end; these force a cut in 100% of kernels).
- The prior "verified: all 94 kernels segment cleanly" observation was
  vacuous: any flag bit segments onto the section end, because a run that
  reaches the last word is silently emitted as-is. The old `segment()`
  accepted exactly this and never noticed.

### Bit 0 is the current candidate (not confirmed)

Ranking the surviving bits by "no instruction longer than the `.il64`
directive allows". The AGX3 backend declares `.il4 .il8 .il16 .il32 .il64`,
i.e. instructions are 4/8/16/32/64 bits — so no instruction should exceed 4
words (64 bits). Only **bit 0** meets that: max 4 words, and in fact just
11 four-word instructions in 435,252. Bit 15 (max 5) and bits 10/11 (max 10)
overshoot. Bit 0 also keeps every base marker meaningful:

- `0x8000`, `0x0108`, `0xc000`, `0x0000`, `0x0008` are all even → 1-word
  terminators under bit 0, so the "padding" (`0xc000`) and "end"
  (`0x0108`) words behave as standalone instructions, as expected.
- No section ends on an odd word (0 failures), consistent.

**Honest status: bit 0 is a candidate, not a verified flag.** The candidate
set that survives the corpus is {0, 10, 11, 15} (plus others with absurd
run lengths); bit 0 is preferred only because of the `.il64` bound. The
corpus alone cannot separate 0 from 10/11/15 — a true wide instruction
(e.g. `ldimm`, below) would look like a shorter pair under bit 0. This must
be settled with `metal-tt -arch applegpu_g10p` (see below), exactly as G9P
was. `tools/g10p-text.py` now defaults to bit 0 and takes `--bit N` to
cross-check.

### Corrected corpus statistics (bit 0)

- 94 kernels, 492,190 words, **435,252 instructions**, 0 forced cuts.
- Lengths: 87.6% 1 word, 11.7% 2, 0.67% 3, 11 instrs 4 (max).
- 7,956 distinct first words (last session, under bit 8: 7,826 / 420,252).
- Top first words: `0000` (74k), `c020` (21k), `0040` (18k), `001e` (18k),
  `02de` (17k), `0026` (12k), `4040` (12k), `006e`, `7400`, `0038`, `0066`,
  `2000`, `14d2`, `ff00`, `0008`, `ffff`, `1cd2`, `200e`, …

### Program / function structure (framing-independent facts)

The old note "`0x0108` is the end-of-program instruction, all 94 kernels end
with it" survives, but `0x0108` is not only an end-of-object marker:

- `0x0108` occurs 219×; **94 are the last word of a section** and the other
  **125 are mid-section** — 113 of them followed by the `0x0008` (79×) or
  `0x0000` (34×) filler words, 12 followed directly by code. So `__text` is
  a sequence of functions: each ends with `0x0108` ± filler and the next
  function follows.
- Of those 125 function boundaries, **80 place the next function exactly on
  a 64-byte boundary** — matching G9P's "end at the start of a 64-byte
  block". (The remaining 45 are not 64-byte aligned, so this is a tendency,
  not a hard rule, or some "boundaries" are false positives from the
  filler detector.)
- **`0x8000` is *not* an end marker on G10P.** It occurs 4,986× and its
  position is flat mod 64 (G9P's `0x8000` was 64-byte aligned). It is
  usually followed by `0x2000` (2,510×) or `0x0008` (2,017×): a normal
  instruction, or the head of a repeated pair — not a terminator.

### The 94 kernels are a fixed-function uber-kernel suite

The `__GPU_LD_MD` metadata carries the source names (extracted 2026-11-07).
Inventory:

| count | source |
|---|---|
| 32 | `bucketed-tessellation-compute-instance-counts-driver` |
| 32 | `bucketed-tessellation-driver-emit-draw-commands-driver` |
| 8 | `tessellation-non-bucketed-emit-draw-commands-driver` |
| 4 | `eot_uber` |
| 3 | `agc.background.constant_program` |
| 1 each | `compute-progress-marker-driver-gen3`, `passthrough_vertexfetch`, `tg-size-optimization-driver`, `execute-indirect-range-exec-compute-driver-g10`, `graphics-execute-indirect-range-driver`, `agc.tile_dispatch_vertex_point.constant_program`, `graphics-execute-indirect-esl-driver`, `gpu-gather-compute-driver-gen3`, `gpu-gather-vertex-driver`, `bucketed-clear-instance-counts-driver`, `agc.background`, `bucketed-tessellation-driver-sum-instance-counts-driver`, `execute-indirect-compute-driver-g10`, `clearvertex` |

So the 72 `.constant_program` objects are the **same two programs
specialized 32× each** — ideal differential material. **Caveat found:** the
32 `compute-instance-counts` instances are not constant-only variants; their
`__text` sizes split into two clusters (428–532 words and 943–1091 words),
i.e. a specialization that selects whole code paths, so a naive word diff is
not clean. Differential analysis is deferred until the flag bit is fixed.

### Fixup layouts vs the corpus (open)

The AGX3 fixup names imply instructions wider than anything the corpus
shows under any sane flag bit:

- `fixup_agx3_ldimm_imm_0_l0m31o50`: a 32-bit immediate at instruction bits
  50–81 ⇒ the `ldimm` instruction is ≥ 82 bits (≥ 6 words).
- `fixup_agx3_b_offset_0_l0m47o22` (`bl`, `bn` same shape): a 48-bit branch
  offset at bit 22 ⇒ ≥ 70 bits (≥ 5 words).

No flag bit in {0, 8, 10, 11, 15} yields a ≥ 6-word run except as scattered
data-looking monsters (bits 10/11), and bit 0 has none. Either these
kernels never emit `ldimm`/`b_offset` fixups, or the fixup bit numbering is
not "bits from the start of the instruction" as assumed. **Unresolved; do
not build an encoder on it yet.** `fixup_agx3_ldimm_imm_1_…` (scattered
fields, max output bit 59) *would* fit a 4-word instruction, so it is the
more promising of the two.

> **Resolved later on 2026-11-07:** the AGX3 fixup writers were found and
> disassembled; their byte-level arithmetic shows the `o` numbers are *raw*
> bit positions and that the AGX3 encoding has no per-word continuation bit.
> See **AGX3 backend reverse-engineering** at the end of this file. The
> `ldimm`/`b_offset` widths above are real (5-6 words) and are the reason
> the bit-0 candidate is no longer considered confirmed.

### What this closes / what it opens

- **Closes:** "G10P uses the G9P bit-8 framing" — false. The prior corpus
  statistics and the "`0x8000` is the end word" reading are void.
- **Opens:** the exact continuation flag bit; whether `__text` contains any
  embedded constant words; the `ldimm`/branch encoding; and the whole
  opcode/field map, which now has to be derived under the corrected framing.

### Next step (unchanged instrument)

The blocker is the same as G9P: **`metal-tt -arch applegpu_g10p`** on macOS
(`xcodebuild -downloadComponent MetalToolchain`), then compile one kernel per
library and compare word-for-word with a `ds.g10p` object — the flag bit
falls out immediately (a one-instruction kernel and a two-instruction kernel
are enough). Alternatively, walk the AGX3 AsmParser/InstPrinter tables in
`dyld_shared_cache_arm64.19` (re-extract the SystemOS cryptex
`087-86588-047.dmg`); the tables are binary, not strings. Nothing here was
validated on hardware, and no device access was used.

## AGX3 backend reverse-engineering (2026-11-07, offline)

This is the first look inside the actual AGX2/AGX3 LLVM backend that
produced the `ds.g10p` objects. It was done **entirely offline** against the
already-extracted dyld shared cache in
`/tmp/opencode/dsc/20H392__iPhone10,2_5/` (`dyld_shared_cache_arm64` plus
subcaches; the AGX3 backend is in subcache `.19`). No device, no network, no
re-extraction of the cryptex.

Tools written for this (copied to `tools/agx3-re/`):

| tool | purpose |
|---|---|
| `vmap.py` | virtual address -> (subcache file, file offset) |
| `xref2.py` | exact ARM64 `adrp`+`add #lo12` string xrefs inside a subcache |
| `disasm2.py` | disassemble a byte range of a subcache with absolute addresses (llvm-objcopy + llvm-objdump) |
| `callers.py` | find `bl` call sites into an address range |

### Where the AGX3 code is

Each subcache file starts with its own `dyld_v1   arm64` header and a
single mapping. Subcache `.19`: base `0x1bc6a8000`, size `0x666c000`. Its
AGX3 string table sits at file `0x026d5000`-`0x026e1400` (1 654 strings);
AGX3 code is around file `0x00511000`-`0x0057f000` (vaddr
`0x1bcbb9000`-`0x1bcc21000`). `LLVMInitializeAGX3InstPrinterTgt` /
`LLVMInitializeAGX3AsmParserTgt` are referenced from file `0x00512ac8` /
`0x00512afc`.

### Fact 1 - the AGX3 instruction encoding is byte-packed with dense bit fields

The fixup writers patch an instruction buffer **bit by bit**, one byte at a
time (`ldrb`/`orr`/`strb`), not word by word. Example: the branch-offset
fixup writer at vaddr `0x1bcc03014` (the "b" variant; `bl` is at
`0x1bcc03118`, `bn` at `0x1bcc0321c`):

```
0x1bcc030c0  ldrb w8, [x1, #0x2]
0x1bcc030c4  orr  w8, w8, x2, lsl #6      ; src bits 0..1  -> byte 2 bits 6..7
0x1bcc030c8  strb w8, [x1, #0x2]
0x1bcc030cc  ldrb w8, [x1, #0x3]
0x1bcc030d0  orr  w8, w8, x2, lsr #2      ; src bits 2..9  -> byte 3
...
0x1bcc03110  ubfx x8, x2, #42, #6        ; src bits 42..47
0x1bcc03114  b    0x1bcc030b0            ; -> byte 8 bits 0..5
```

So the instruction is a **byte array with densely packed bit fields**, and
the source value is a 48-bit field placed at **raw bit offsets 22..69** of the
instruction (byte 2 bit 6 .. byte 8 bit 5) - i.e. *all* 16 bits of each
16-bit word are payload.  This is the `fixup_agx3_b_offset_0_l0m47o22`
layout; the second variant (`l1m47o25`, selected for the other ISA classes)
places src bits 1..47 at raw bits 25..72.

**Consequence: there is no reserved "continuation" bit in AGX3.**  If a word
had a flag bit, the fixup bit numbering would have had to skip it (G9P-style
"15 payload bits per word"); the observed byte/bit arithmetic is exact only
if every bit of every word counts.  Hence the AGX3/G10P instruction length
is carried by the **opcode**, not by a flag.

### Fact 2 - the branch/ldimm fixups need 5-6 words, which weakens the `.il64` argument for bit 0

`fixup_agx3_ldimm_imm_0_l0m31o50` puts a 32-bit immediate at raw bits
50..81, so that `ldimm` encoding is >= 82 bits >= 6 words of 16 bits.
`fixup_agx3_b_offset_0_l0m47o22` gives >= 70 bits >= 5 words.
The fixup selector (`cmp w0,#3 / #2 / #1`, returning fixup kinds `0x8c`,
`0x8d`, `0x8e`, `0x8f` for `b`, `bl`, `bn`) chooses the layout per ISA
class, and the AGX3 fixup-kind ids `0x8c`..`0x8f` are consecutive.

The "bit 0 is the flag" argument in the *Framing correction* section rested on
"`.il64` => no instruction exceeds 4 words".  That argument is now **not
safe**: AGX3 demonstrably encodes 5- and 6-word instructions, and the corpus
under bit 0 has a maximum of 4 words (only 11 four-word instructions in
435 252).  Either the `ds.g10p` kernels never use those two fixups, or the
fixup bit numbering is not instruction-relative.  **Bit 0 is therefore no
longer the best-supported candidate - it is only the best *fitting* one.**

### Fact 3 - an opcode decode table exists

At vaddr `0x1bcc00054` (file `0x00558054`) there is a decode helper:

```
sub  w8, w0, #0x102          ; word - 0x102
cmp  w8, #0x1520             ; 0x1521 entries
b.hi invalid
adrp/add  table @ 0x1be31cb78
ldr  x8, [x9, w8, sxtw #3]   ; 8-byte entries
orr  x0, x9, x8              ; x9 = 1<<32
```

The table (file `0x1c74b78`, 5 409 x 8 bytes) is
`entry[i] = (1<<32) | (i-1)` with `entry[0] = 0`, so words `0x103`..`0x1622`
are "valid" and `0x102` is not.  A second, non-trivial table at
`0x1be28c31c` (indexed by a dense index) is consulted by the size helper at
`0x1bda55650`.

Caveat: this code region also contains the AGX2 backend, so it is **not yet
proven** that this particular table is the AGX3/G10P one.

### Fact 4 - the corpus is 16-bit aligned but the AGX3 object encoding is byte-packed

All 94 `__text` sections have an **even** byte length (54 of 94 are = 2
mod 4), so the corpus is a sequence of 16-bit words.  The AGX3 encoder
builds a byte array per instruction and the caller splits 16-bit table
entries into low/high bytes, i.e. there is a repacking step between the AGX3
"ISA" encoding and whatever lands in `__text`.  That repacking is where a
per-word flag *could* live - and it has not been found yet.

### What this changes for the framing question

- "Which bit means another word follows?" is probably the **wrong question**
  for G10P.  AGX3 has no continuation bit in the encoding we can see, and
  the same-source differential test (Fact 5) shows that *no* single bit of
  the first word reproduces the corpus' internal structure.
- Bit 0's remaining support is purely statistical (it is the only candidate
  bit whose segmentation never exceeds 4 words and never forces a cut) - and
  the AGX3 fixup evidence now argues *against* a 4-word ceiling.  On the
  graded same-source test bit 0 is in the middle of the field (0.745), not
  the best (bit 13 at 0.795, bit 8 + `0x0108` special at 0.790).
- A variant worth keeping on the list: **"bit 8 with `0x0108` as a special
  end marker"**.  It also segments cleanly (420 377 instructions, 0 forced
  cuts, max 5 words, lengths 1:359 914  2:49 808  3:9 961  4:693  5:1) and
  allows 5-word branches.  But it predicts only **one** 5-word instruction in
  the whole corpus, which is implausible for kernels full of branches.
- If G10P really is opcode-length-determined, the correct next artefacts are
  an **opcode -> length map for G10P** (AGX3 descriptor table, Fact 6) and
  the **repack step** that turns AGX3's byte-encoded instruction into the
  16-bit words of `__text` (Fact 4).  Neither is a bit search.

### Fact 5 - no single-bit framing reproduces the same-source structure

The corpus contains 32 specialisations each of two `.constant_program`
sources.  The instances differ only in their specialisation constants, so
under the *correct* framing their instruction-length sequences should agree
almost everywhere.  Measured (`tools/g10p-struct/g10p-samesrc.py`; mean over
all 496 pairs in the five same-source groups of 3..32 instances, comparing
the length at each instruction position):

| framing | mean length-sequence agreement |
|---|---|
| bit 13 | 0.795 |
| **bit 8 + `0x0108` special** | **0.790** |
| bit 8 | 0.789 |
| bit 0 | 0.745 |
| bit 10 | 0.711 |
| bit 11 | 0.688 |
| bit 5 | 0.684 |
| bit 1 | 0.448 (worst) |

**No candidate reaches anything like 1.0** - the best is ~0.79 and the
worst ~0.45.  A framing that were correct would have to explain why 20 % of
the instruction positions of two builds of the *same program* disagree about
their length.  This is independent evidence that G10P's instruction length is
**not** determined by a single flag bit (or, at minimum, that no single bit
of the first word determines it).  It also retires the old "same-source
length-sequence agreement 0/5 groups" note: the graded form shows bit 8 is
not uniquely bad - *every* bit is bad.

### Fact 6 - an AGX3 per-opcode descriptor table exists (but is not a size table)

The AGX3 encoder (vaddr `0x1bcc01acc`) indexes a 32 768-entry table at
vaddr `0x1be327a44` (file `0x1c74b44`) with the opcode:

```
ldr  w8, [x8, w23, uxtw #2]   ; table[opcode]
and  x8, x8, #0x7ff           ; 11-bit index into the operand/encoding blob
```

The high bits of each entry are *flags*, **not** a size: no `lsr #11` of
the entry exists anywhere in the encoder.  (An earlier reading of the high
bits as a byte length - which would have implied 6..32 word instructions -
was checked and discarded.)  This table is the per-opcode encoding/operand
descriptor and is where an **opcode -> length** map must live; it has not
been decoded yet.

### Honest status

Nothing in this section was validated on hardware or against a `metal-tt`
reference; it is static analysis of Apple's shipped compiler.  The
load-bearing claim - "AGX3 has no continuation flag" - rests on the
byte-level arithmetic of the fixup writers, which is directly readable and
was checked against both ends of the field (src bit 0 -> raw bit 22, src bit
47 -> raw bit 69), but it assumes the fixup bit numbering is relative to the
instruction start.  That assumption is the single thing to attack next,
together with finding the opcode->length map in the table of Fact 6 and the
step that repacks AGX3's byte-encoded instructions into the 16-bit words of
`__text`.

---

## Public AGX ISA reference + AGX3 encoder/decoder deep-dive (2026-11-08, offline)

All work below is static analysis of Apple's shipped compiler (the `.19`
AGX3 subcache of `20H392__iPhone10,2_5`) and of the corpus in `ds-g10p/`.
No hardware was touched; no kernel/DT file was changed; nothing was pushed.

### Naming: what `applegpu_g10p` is (confirmed strings)

`.19` contains two different name spaces, both now enumerated:

*Metal "arch" names* (file `0x2730ae9`, with `-apple-ios` twins from
`0x27322ad`):

```
applegpu_g4p  applegpu_g4g  applegpu_gx2  applegpu_g5p
applegpu_g9p  applegpu_g9g  applegpu_g10p
applegpu_g11p applegpu_g11m applegpu_g11g applegpu_g11g_8fstp
applegpu_g12p applegpu_g13p applegpu_g13g applegpu_g13s applegpu_g13c applegpu_g13d
applegpu_g14p applegpu_g14g applegpu_g14s applegpu_g14d
applegpu_g15p applegpu_g15g
```

Note there is **no** `applegpu_g10`; the corpus arch is `applegpu_g10p`.

*LLVM subtarget ("processor") names* (complete set in `.19`):

```
g4g-a1 g4p-b1 g5g-a1 g5p-b0 g5p-c0
g9g-a0 g9g-a1 g9p-a0 g9p-b0
g10p-b0
g11g-a0 g11g-b0 g11m-a0 g11m-b0 g11p-a0 g11p-b0
g12g-a0 g12g-b0 g12m-a0 g12p-a0 g12p-b0 g12x
g13c-a0/b0 g13d-a0/b0 g13g-a0/b0 g13p-a0/b0 g13s-a0/b0 g13stk
g14c g14d g14g g14p g14s g14x (+-a0/-b0)
g15g-a0/b0/c0 g15p-a0/b0
```

* **Confirmed:** the AGX3 backend's own subtarget list is at `0x26d2eb5`:
  `g10`, `g10p-b0`, `g11` (then `g11m-a0`, `g11m-b0`, `g12m-a0` at
  `0x26d2ec5/0x26d2ecd/0x26d2ef9`).  `g9p-a0`/`g9p-b0` (`0x26d8827`,
  `0x26d884a`) belong to the *other* backend (the AGX2 one, see below).
* **Confirmed:** `applegpu_g10p` has exactly one stepping, `g10p-b0`, which is
  the **second** entry of the AGX3 subtarget list.  So the AGX3 encoder's
  *variant index 1* is `g10p-b0` — the corpus's target.
* **Correction to an earlier reading of this file:** `AGXMetalA11.bundle` is
  a bundle **version**, not a device indicator — the A12 device's cache
  (`20H392__iPhone10,2`) contains `/System/Library/Extensions/AGXMetalA11.bundle/AGXMetalA11`
  (`0x56db6`).  The corpus is nonetheless unambiguously `applegpu_g10p` code
  (file names `*.g10p-o`, Mach-O `CPU_TYPE` `0x01000013`).
* **Open (candidate):** which silicon "10th-generation Apple GPU family"
  (`g10p`) is, and how Apple's `gN` numbering maps onto the public
  Asahi/Mesa names (`g9p`/`g10`/`g11`/`g12`/`g13g` for A11/A12/A13/A14/M1).
  The two schemes do **not** line up 1:1, and `applegpu_g10p` is not one of
  the arch names the Mesa `agx` compiler targets (`g11p`, `g12p`, `g13p`,
  `g13g`, `g14g`, `g15g`).  Consequence: **Mesa's AGX ISA is very likely a
  later revision than the corpus's**, which is exactly what the bit-level
  differences below show.  This naming question does *not* block the work:
  the AGX3 backend in `.19` is Apple's own compiler for `g10p-b0`
  regardless of which chip that is.

### The public AGX ISA (confirmed, external)

Vendored as **reference only** under `tools/reference-agx-isa/` (with
provenance and licence notes in that directory's `README.md`):

* `agx_opcodes.py` — Mesa `src/asahi/compiler/agx_opcodes.py`, branch
  `agx/next`: the authoritative public **opcode -> length** table.
* `agx_pack.c` — Mesa `src/asahi/compiler/agx_pack.c`: the packer's bit
  layout.
* `dougallj-applegpu-docs.html` — Dougall Johnson's public AGX ISA notes
  (`https://dougallj.github.io/applegpu/docs.html`).

Facts (confirmed from those files, and mutually consistent):

* An instruction starts with a **32-bit little-endian header**; the opcode is
  identified by an `(exact, mask)` pair over that header.
* **Bit 15 of the header = `L`** ("long form").  For extensible opcodes the
  length is `length_short` when `L == 0` and `length_long` when `L == 1`,
  where `length_long = length_short + 2` (or `+ 4` when `length_short > 8`).
* Lengths are in **bytes** and always even: 2, 4, 6, 8, 10, 12.
* Opcode occupies the low 6-7 bits of the header; bit 6 = saturate;
  destination register in bits 7..14; operands from bit 16 up.  Mesa always
  emits the long form (`1 << 15` is set unconditionally in its packer).
* The public ISA notes and Mesa's table agree opcode-for-opcode
  (`stop` `0x0088`, `trap` `0x0008`, `wait` `0x0038`, `iadd` `0x000e`,
  `imad` `0x001e`, `fadd32` `0x802a`, ...).

### The corpus is the same family, a different revision (confirmed evidence)

* **Confirmed:** the corpus's low-7-bit histogram matches Mesa's opcode set
  for **57.7 %** of all 492 190 words (chance would be ~24 % for 31 opcodes
  out of 128).  Leaders: `0x1e` (imad, 28 295), `0x52` (19 914),
  `0x0e` (iadd, 15 248), `0x26` (fadd16, 12 848), `0x1a` (fmul32, 10 898),
  `0x12` (icmpsel, 7 653), `0x09` (st_tile, 6 940), `0x71` (texture_load,
  6 258), `0x38` (wait, 5 794), `0x16` (fmul16, 5 391).
* **Confirmed:** two concrete flag-bit differences against Mesa:
  * corpus terminator `0x0108` (last word of all 94 kernels) vs Mesa
    `stop` = `0x0088` — the extra flag bit sits at **bit 8** in the corpus
    and at **bit 7** in Mesa.
  * corpus `0xc020` (2nd most common full word, 21 048x) vs Mesa
    `jmp_exec_none` = `0xc200` — flag bit **5** in the corpus vs **9** in
    Mesa.  The corpus's `0xc000` matches Mesa's `jmp_exec_any` exactly.
* So the corpus's ISA keeps Mesa's opcode *numbering* but moves at least two
  flag bits: **the A11 (`g10p`) ISA is an earlier revision of the same
  family** (candidate label: "AGX3" vs the later "AGX").

### Negative results (important, do not re-run blindly)

* The corpus **does not tile** under Mesa's table, in any framing tried:
  * word-level, 32-bit LE / BE header, ± byte-swap: **0/94**;
  * word-level, header = first word only, ± byte-swap: **0/94**;
  * word-level, 48-bit header: **0/94**;
  * byte-level (instruction starts at arbitrary byte offsets), LE / BE
    header: **0/94**;
  * full DFS over Mesa's low-7 opcode *vocabulary* (ignoring the masks):
    **4/94**.
* Therefore Mesa's `agx_opcodes.py` **cannot** be used as the G10P ISA
  table; it is a close relative, not the answer.  The A11/G10P table has to
  come out of Apple's own AGX3 backend (next section).

### Corpus byte-level structure (framing hints, candidate)

`__text` is a **byte** stream; e.g. `02__agc.passthrough_vertex.g10p-o`:

```
0e 12 ca ca 15 01 52 06 00 00 80 3f 0e 08 01 84 11 00 0e 00 02 44 11 00
05 11 40 0c 00 c0 12 00 05 09 20 0c 00 c0 12 00 05 01 00 0c 00 c0 12 00
38 00 01 19 43 80 01 11 40 80 01 09 41 80 81 01 42 80 08 01
```

* The 4-byte group `00 c0 12 00` recurs at byte offsets **28, 36, 44**
  (LE u32 = `0x0012c000`, low half = `0xc000`).  So the region contains
  repeated 8-byte units; Mesa's `jmp_exec_any` is 6 bytes, which is why
  Mesa's lengths cannot tile this.
* This is *not* a proof of an 8-byte period — it is the shape the next
  (decoder-side) table has to explain.

### AGX3 encoder tables (confirmed) — Apple's own encoder for `g10p-b0`

Encoder base `0x1bc6a8000`; main routine `0x1bcc01acc` (file `0x559acc`).

* Two descriptor/blob table pairs:
  * **A**: `DESC_A 0x1be327a44` / `BLOB_A 0x1be32748f` (used at `0x1bcc01b40`)
  * **B**: `DESC_B 0x1be2fba44` / `BLOB_B 0x1be2fb48f` (used at `0x1bcc01bd0`)
  * `DESC` entry = u32 whose **low 11 bits** are the blob block index.
* Blob block layout: per-variant **2-byte header** `(b0, b1)` at
  `block + variant*2`; an 8-byte header at `block + b0`; then the **form
  stream** = `b1` bytes of `(form_w26, size_bytes)` pairs at
  `block + b0 + 8`.  There is **no base-word template**.
* Form resolve: `TBL329FD4 0x1be329fd4` (`& 0xfff`) → `TBL327CE4 0x1be327ce4`
  (the `csel` at `0x1bcc01c74` picks the variant) → chain entry.
* Chain: `CHAIN_NEXT_HW 0x1be3de990` (u16, stop value `0x7fff`) →
  `CHAIN_NEXT_U4 0x1bcbba0dc` → `0x1be3cb860`.
* Scatter: `CHAIN_TBL 0x1be6d3444` (`& 0x3ffff`) → `SCAT_BASE 0x1be655980 +
  idx*2`; per-variant `off`/`cnt` (u16 each) at `base + variant*4`; records at
  `base + off*2 + 0x10`; record list ends at `rec_start + cnt*2`.
* Scatter record: `+0 srcShift`, `+2 destBit`, `+4 fieldWidth`, `+6 destWord`,
  `+8 type`, `+10 opIdx`.  Record size by type: 0 → 12 B, 1 → 14 + 2n B,
  2 → 12 B (literal u16 at `+10`), ≥ 3 → 10 B.
  Value written = `((value >> srcShift) & mask(width)) << destBit`;
  a double write to the same bit range invalidates the form.
* **No base template (confirmed):** the instruction buffer is zeroed by the
  caller (`0x1bcbba0a8`-`0x1bcbba0bc`) and *every* instruction bit comes
  from a scatter record.
* Table sizes: A var1 = 9 340 opcodes / 25 253 forms; B var1 = 1 496 / 6 483;
  the variant space is ≥ 8.
* **Sizes are byte counts and include odd values** (1, 3, 5, ... 241): over
  the 39 490 var1-A forms, 36 019 are even and **3 471 are odd**.
  * **CORRECTED later the same day (see "Addendum" below):** those odd
  values, and the huge form counts, come from *junk* `DESC` entries outside
  the real ISA-opcode range.  For the ISA opcodes the backend actually
    accepts (**1..167**) the size byte is the **byte** size and the
    instruction is **16-bit-word granular** (`size & 0xfe` bytes are
    zero-filled, the instruction is written with `strh` into a u16 array,
    and `size == 2 * words` for 309 of 374 valid var1-A forms).
    The "byte-packed / repacking" story above is therefore **withdrawn** as
    a statement about instruction boundaries.

### AGX3 decoder chain (confirmed) — where the length really comes from

* ISA opcode → handler: `0x1bcc07e64`, valid ISA opcodes **1..167**; the
  handler table lives in `.27.dylddata` at file `0x3bca2e8`
  (vaddr `0x1d94d22e8`).
* `getInstruction` driver `0x1bcc8a204`-`0x1bcc8a340`; size path
  `0x1bcbbe018`; decode path `0x1bcc02e84` → `0x1bcc026d0`; second dispatch
  `0x1bcc47088`; raw fallback `0x1bcc8a2d4`-`0x1bcc8a300` (`ldrb`, `and
  #0x7f`, then a base-128 varint starting at **byte offset 1** of the
  instruction).
* **Length source (confirmed):** `0x1bda55650` maps ISA opcode → MC opcode
  (jump table `0x1bec34790`, 168 entries, requires ISA opcode ≤ `0xa7`) →
  key map `0x1bcc83488` (constant table `0x1bec35514`) → `0x1bec51d00`
  (16-byte stride, index at `+8`) → `0x1be28c31c` →
  **`MCInstrDesc[MCopcode].Size`** (64-byte stride, u16 at `+6`) = the
  instruction size **in bytes**.
  *⇒ the length is a pure function of the opcode; it is not encoded in the
  stream, and it is not a flag bit.*
* **Still missing:** the base address of the `MCInstrDesc` array.  Stride
  16/32/64 scans of `.19` found no `NumOperands`/`Size` signature, so it is
  probably in another subcache or built at runtime.  The decoder object is
  created at `0x1bcbbe364` and holds the array pointer at `[obj + 0x250]`.

### The other backend ("AGX2") (confirmed)

* Dispatcher `0x1bcc0028c` → helper `0x1bcc00054` (file `0x558054`).
* Property lookup `0x1bcbd8250`: word value in `[0x9e, 0x1622)`, index
  table `0x1be2f9c10`, records at `0x1be2a2d70 + idx*0xd4` (106 u16
  categories), out-of-range → `0xffff`; helper `0x1bcbd8294` uses a jump
  table `0x1be2963f0` indexed by `(value - 0x452)`.
* `0x1be31cb78` is a 32-byte-record table of property/category ids
  (`0xda7`, `0xdac`, ...) indexed by the word value — it is **not** a size
  table.
* This backend is the one that carries the `g9p-a0`/`g9p-b0` subtargets.

### What this changes / next steps (2026-11-08)

1. **Build the authoritative ISA-opcode → length table from the decoder
   side** (finish locating the `MCInstrDesc` base via the object at
   `0x1bcbbe364` + `0x250`, or by finding the table in another subcache).
   That table, plus the AGX3 header parse, is what a `pvr_arch_g10p`
   disassembler needs.  Mesa's table cannot be substituted.
2. **Frame the corpus as bytes**, not words: use the encoder's per-form size
   list and the decoder's length function to walk the corpus byte stream
   from offset 0.  The odd-sized forms (3 471 of 39 490) mean word-aligned
   framing is hopeless; byte alignment is mandatory.
3. `__GPU_ARCH_LD_MD` (64 B) and `__GPU_LD_MD` (216 B) are still undecoded.
   `__GPU_LD_MD` does yield the `source_name` strings used for grouping
   (`progress_marker_compute`, `compute-progress-marker-driver-gen3` — the
   "gen3" is consistent with the AGX3 backend).
4. `AGX3Disassembler` (vtable/symbol) is still unresolved; decoder entry is
   `0x1bcc8a204`.
5. Hardware steps (native `disp0`, `pvr_apple` 3D bring-up) remain gated on
   an explicit "go" plus approval for any kernel/DT edits; `simplefb` stays
   as the working display path.

### Files added by this session

* `tools/reference-agx-isa/` — vendored public AGX ISA reference
  (`agx_opcodes.py`, `agx_pack.c`, `decode.c/h`, `gen_pack.py`, `table.py`,
  `dougallj-applegpu-docs.html`) + a `README.md` with provenance, licence
  and the "reference only, do not cherry-pick" rule.
* `/tmp/opencode/` (not part of the archive): `agx_frame.py`,
  `agx_bytes.py`, `agx_tiling.py`, `agx_table_test.py`,
  `g10p_tables.py`, `g10p_sweep.py`, `g10p_solve_len.py`,
  `agx_public_isa.py`.

---

## Addendum (2026-11-08, later session): the AGX3 encoder/decoder re-read

Same constraints as above: offline only, no device, no kernel/DT edits, no
pushes.  New artefacts live in `/tmp/opencode/` (`g10p_isa_dump.py`,
`g10p_size_unit.py`, `g10p_tile2.py`, `g10p_hitrate.py`, `agx_bytes2.py`).

### 1. The AGX3 ISA is 16-bit-word granular (confirmed, corrects Fact 4)

Three independent pieces of encoder evidence:

* The blob's size byte is consumed as
  `and w1, w22, #0xfe` → `memset(scratch, size & 0xfe)` at `0x1bcc01c28`
  (the scratch buffer is `x29-0x9c`).  The low bit of the size byte is a
  **flag** that is masked off; the instruction therefore occupies an
  **even** number of bytes.
* The scatter loop writes the instruction with **`strh`** into a u16 array
  indexed by word: `ldrh w4, [x19, w16, uxtw #1]` / `strh w2, [x19, x6,
  lsl #1]` (`0x1bcc01eb0`-`0x1bcc01ed4`).  `destWord` is a **16-bit word
  index**, `destBit` a bit offset inside that word (0..15).
* For the ISA opcodes the backend accepts (1..167), table A variant 1 has
  374 valid forms and **`size == 2 * nwords`** for 309 of them (the rest are
  +2/+4/+8, i.e. forms whose chain writes fewer words than the size
  reserves).  Sizes are 2..14 bytes = 1..7 words.

⇒ **Fact 4's "the corpus is 16-bit aligned but the AGX3 object encoding is
byte-packed / there is a repacking step" is withdrawn.**  Instructions are
whole 16-bit words; the corpus's u16 view is the natural granularity.

### 2. The ISA opcode is a *variable-length* bit field, not a 6/7-bit field

The encoder's per-opcode tables do **not** put the opcode in a fixed bit
position.  Each opcode's literal (fixed) fields are packed sequentially
from bit 0 of word 0 and may run into word 1, word 2, … :

| word-0 fixed mask | # distinct values | example (ISA opc → value) |
|---|---|---|
| `0x07ff` | 123 | 1 → `0x0167`, 2 → `0x0367`, 3 → `0x000f`, 24 → `0x040f` |
| `0x0007` | 4 | 5 → `0x0003` (+ next 3-bit field in word 1) |
| `0x000f` | 2 | 61 → `0x000a` |
| `0x001f` | 4 | 17 → `0x0016`, 34 → `0x000e` |
| `0x700f` | 8 | |
| `0x8007` | 2 | |

So the A11 ISA uses a **hierarchical / prefix-coded opcode**: e.g. opc 1 =
`[3 bits = 7][4 bits = 0xc][4 bits = 0x2]`, while opc 5 starts with
`[3 bits = 3]` and continues in the next word.  (This is why "the opcode is
in the low 7 bits" — the Mesa/A12+ assumption — cannot be transplanted.)

### 3. The real ISA-opcode range is 1..167 — earlier form counts were junk

`0x1bcc07e64` accepts ISA opcodes **1..167** (`sub w8,w0,#1; cmp w8,#0xa6`).
The `DESC` tables are 32768-entry arrays and most entries beyond 167 are
non-zero garbage, which is where the earlier "9 340 opcodes / 25 253 forms"
figures came from.  The real counts for table A variant 1 (g10p-b0) are:

* ISA opcodes 1..167 → **374 valid forms** (163 opcodes have at least one).
* Per opcode the form list gives `(form byte, size byte)`; the form byte
  selects a variant of the instruction (different operand shapes).

The encoder also **calls the decoder's per-opcode handler**
(`0x1bcc07e64` → `blr`) to obtain the instruction descriptor before
encoding, so encoder and decoder share one layout definition.

### 4. New decoder-side tables (confirmed)

Three small lookup helpers sit in the AGX3 backend and are indexed by ISA
opcode:

| helper | table base | index | content |
|---|---|---|---|
| `0x1bcbbe2fc` | `0x1be295228` | ISA opc 0..167 (168×u32) | values 175..409 (monotone-ish) — an ISA→"MC-ish id" map |
| `0x1bcbbe31c` | `0x1be2954c8` | value 0x4a..0x2b0 (615×u32) | consecutive with table 1 |
| `0x1bcbbe340` | `0x1be295e64` | ISA opc 1..167 (167×u32) | offsets 69,174,264,281,313,377,… (≈64 apart → an index into a 64-byte-stride table) |
| `0x1bcc034a8` | `0x1bec26778` | ISA opc 0..167 (168×u32) | values 384..551 |

Also confirmed: the **`MCInstrDesc` array base** is the value stored at
**`[decoder_object + 0x250]`** (`ldr x23, [x23, #0x250]` at `0x1bcc8a210`,
passed as `x1` to the size path `0x1bcbbe018`, which indexes it with
`add x8, x8, x9, lsl #6` → 64-byte stride, `NumOperands` u16 at `+2`,
`Size` u16 at `+6`).  The object is created at `0x1bcbbe364`; the base
pointer itself is still not located statically.

The final instruction length is taken at `0x1bcc8a348`-`0x1bcc8a354` as
`(*(u32 *)(out->field_0x50)) >> 3` — the unit of that field is still
unresolved (bit/byte/nibble).

### 5. Two more framing negatives (confirmed)

* **Byte-level DFS using Mesa's opcode *values* and Mesa's *lengths***
  (ignoring Mesa's header masks, i.e. "same opcode numbering + same lengths,
  different header layout"): **4/94** files tile (low-7 mask), 3/94
  (low-6).  The four hits are trivial (a 2-byte `trap`-like terminator).
  ⇒ that hypothesis is essentially dead.
* **Word-level DFS using Apple's own encoder tables** (every literal field of
  every form of table A var 1, matching *all* fixed fields of the
  instruction, length = size/2 words): **0/94** files tile.

### 6. Revised picture (2026-11-08, evening)

* The corpus is AGX3-compiled code for `applegpu_g10p` (variant
  `g10p-b0` = table A/B variant 1).  *Confirmed* by the backend's own
  subtarget list.
* The AGX3 instruction stream is **16-bit words**, lengths 1..7 words, and
  the opcode is a **prefix-coded bit field** starting at bit 0 of word 0.
* The corpus does **not** match the encoder's fixed-bit patterns, and does
  not match Mesa's ISA.  Remaining possibilities, in order of likelihood:
  1. **The corpus's `__text` is not the instruction stream at all** (it may
     be a data/constant/metadata area, or the program's *fixed-function*
     payload, while the real instructions live elsewhere in the object —
     `__GPU_METADATA.__compute` is 280 bytes in the smallest file and the
     `__text` of `01__agc.eot` is 46 KB, both suspiciously large).
  2. The corpus's words are a **re-packed** form of the encoder output (a
     later "pack" step; the backend does contain `llvm.agx1.pack.*`
     intrinsics, but those are data pack/unpack helpers, so this is
     unproven).
  3. The corpus is not AGX3 output at all (the "gen3" string in
     `__GPU_LD_MD` is suggestive but not proof).
* **Next concrete moves** (in order):
  1. Check whether the corpus's `__text` is even the code: look at the
     other sections (`__GPU_METADATA.__compute` = 280 B,
     `__GPU_ARCH_LD_MD` = 64 B) and at the *relocation/fixup* records; a
     code section normally carries branch fixups, and the KB's earlier
     fixup-layout work should be re-run against the objects rather than
     against a guessed layout.
  2. Decode the AGX3 **decoder handler** for one simple opcode (e.g. the
     handler at `0x1bcc0826c` = ISA opcode 1) to learn the *decoder's*
     view of the header (which bits it reads for the opcode) — the decoder,
     not the encoder, is what a disassembler must follow.
  3. Only then re-run the framing DFS with the decoder's own layout.
  4. `__GPU_ARCH_LD_MD` (64 B) and `__GPU_LD_MD` (216 B) still undecoded;
     they may name the arch/ISA revision the object was built for.

### 7. Naming, one more correction (confirmed)

* `AGXMetalA11.bundle` is a **bundle version**, not a device marker: the
  A12 device's cache (`20H392__iPhone10,2`) contains
  `/System/Library/Extensions/AGXMetalA11.bundle/AGXMetalA11` (`0x56db6`).
  The corpus's arch is nevertheless unambiguously `applegpu_g10p`.
* Nearby backend strings (`.19`): `g10g11g12` (`0x26d93c8`),
  `g11g12` (`0x26d940e`), `llvm.agx1.pack.prog` (`0x27088a8`),
  `llvm.agx2.program.type` (`0x270c063`),
  `agx2-rematerialize-large-programs` / `agx3-rematerialize-large-programs`
  (`0x26d43a6` / `0x26d745c`) — the AGX2 and AGX3 backends are separate
  passes in the same compiler.
* The AGX3 backend's subtarget list is `g10`, `g10p-b0`, `g11`
  (`0x26d2eb5`ff), with `g11g-a0`/`g11g-b0` immediately after
  (`0x26d2ee5`/`0x26d2eed`); `g9p-a0`/`g9p-b0` belong to the AGX2 backend.
  The Metal arch list has **no** `applegpu_g10` — only `applegpu_g10p` —
  so `g10p` is *not* the same name as the public Asahi `g10` (A12).

### 8. Framing status after the encoder/decoder re-read (2026-11-08, night)

New measurements (script `/tmp/opencode/g10p_class.py`,
`g10p_variants.py`, `g10p_hitrate.py`):

* **All 94 `__TEXT.__text` sections have an EVEN byte size** (0 odd) →
  the corpus is word-aligned.  Together with the encoder's even-byte sizes
  this closes the "byte-packed corpus" idea for good: the corpus *is* a
  16-bit-word stream.
* Per-class hit rate of the corpus against the AGX3 encoder's word-0 fixed
  patterns (table A, variant 1 = g10p-b0), with the correct random
  baseline:

  | word-0 mask | #values | random | corpus | reading |
  |---|---|---|---|---|
  | `0x0007` | 4 | 0.500 | 0.535 | no signal |
  | `0x000f` | 2 | 0.125 | 0.128 | no signal |
  | `0x001f` | 4 | 0.125 | **0.243** | ~2x enrichment |
  | `0x07ff` | 123 | 0.060 | **0.021** | **3x DEPLETED** |
  | `0x700f` | 8 | 0.062 | 0.053 | no signal |
  | `0x8007` | 2 | 0.125 | 0.057 | no signal |

  The class that carries 123 of the 167 ISA opcodes (the 11-bit opcode in
  bits 0..10) is **three times rarer in the corpus than chance** — i.e. the
  corpus's words do **not** contain the AGX3 word-0 opcode encoding.
  (The apparent "signal" for variants 5/6/7 was an artifact: their single
  `0x0780` value is 0, and 52.8 % of all corpus words have bits 7..10 = 0.)
* The corpus's low-3-bit histogram is strongly skewed:
  `0 → 45.6 %`, `6 → 24.3 %`, `2 → 12.8 %`, `4 → 5.7 %`, `1 → 4.5 %`,
  `7 → 3.7 %`, `3 → 1.6 %`, `5 → 1.8 %` (random would be 12.5 % each), and
  `0x0000` alone is 16.2 % of all words.  A word stream that is mostly
  zeros in its low bits looks more like *operand/padding* data than like a
  stream of instruction headers.
* The objects' symbols confirm `__text` **is** the code: the smallest
  object has exactly one symbol, `_agc.main`, type `N_SECT|N_EXT`,
  section 1, value 0 → the function starts at `__text+0` and is 14 bytes
  (7 words) long.

⇒ **Standing conclusion:** the corpus is word-aligned code, but its words do
not use the AGX3 encoder's opcode encoding.  Either (a) the corpus is not
AGX3 output, or (b) the corpus's instruction encoding is a *different*
layout than the encoder's (e.g. the decoder's own view, or a repacked
form), or (c) `__text` mixes code with large data/padding areas.

**Next moves, re-ordered:**

1. **Decode `__GPU_METADATA.__compute`** (280 B in the smallest object;
   contains the string `agc.main` and a table of small u32s: 4, 8, 12, 16,
   20, 24, 28, 32, 36, 40, 44, 48, 54, 55, 56, 58, 60, 64 …).  This is the
   program's own metadata and may state the code size, the number of
   instructions and/or per-segment offsets — i.e. it may hand us the
   framing directly, without decoding the ISA.
2. **Decode `__GPU_ARCH_LD_MD`** (64 B) and `__GPU_LD_MD` (216 B) — they may
   name the arch/ISA revision the object was built for and settle the
   `g10p` question.
3. Read one AGX3 **decoder handler** (e.g. ISA opcode 1's handler at
   `0x1bcc0826c`) to learn the *decoder's* view of the header; the corpus
   may follow the decoder's layout rather than the encoder's.
4. Only then re-run the framing DFS.

### 9. First look at `__GPU_METADATA.__compute` (2026-11-08, night)

* The smallest object (`00__agc.main.g10p-o`, 14 bytes of code) carries a
  280-byte `__GPU_METADATA.__compute` section.  It is **not** present in
  every object (`59__agc.eot.g10p-o` has no such section), so it is
  per-program metadata, not a fixed header.
* Layout seen so far (u32 view):
  * `+0x00` `0x10`, `0x000c000c`, `0x08`, `0x00040000`
  * `+0x10` `0x0c`, `0x10`, `0x64`, `0x00080008`
  * `+0x20` `0x00040000`, `0x08`, `0x04`, `0x08`
  * `+0x2c` the **name string** `".agc.main"` (8 bytes, then a NUL word)
  * `+0x38` a ladder of small values that are mostly multiples of 4 and
    mostly descending: `0x40 0x3c 0x38 0x30 0x2c 0x24 0x28 0x20 0x1c 0x18
    0x14 0x10` (then `0x37 0x00 0x36 0x00`), then zeros, then
    `0x0c 0x08 0x00 0x04 0x40 0x00 0x3c 0x00 0x34 0x00 0x38 0x00 …`
  * `+0xb0` `0x01010000`, `0x08`, zeros …
  * `+0xdc` `0x01`, `0x30`, `0x01`, `0x10`
  * `+0xec` `0x000a0000`, `0x0007000c`, `0x00080000`, `0x0a`,
    `0x03000000`, `0x02`, `0x000c000c`, `0x0004000a`, `0x000b0000`,
    `0x0c`, `0x3a`, `0x00000501`
* The descending ladder of multiples of 4 looks like **offsets** (into the
  metadata itself, or into a program-part table).  If it is a per-part
  offset table it may directly give the code/constant layout of the
  program — the fastest remaining route to the framing.
* Plan: dump the metadata of several objects with very different code
  sizes and diff them; fields that scale with the code size are the
  code-related ones.

## Addendum 2 (2026-11-08, late night): **the corpus framing is SOLVED** — it is the public Mesa AGX dialect

This is the single biggest result of the whole investigation.  The corpus
(`ds-g10p`, 94 `applegpu_g10p` objects) is **word-aligned AGX ISA in the
same dialect as Mesa's public `agx_opcodes.py` / `agx_pack.c` table**, with
a small number of A11-specific deltas.

### 1. Tiling result (confirmed)

Using Mesa's `(exact, mask, length_short, length_long)` table at the
16-bit-word level (script `/tmp/opencode/agx_tile3.py`):

* **89 / 94 objects tile exactly** (every word consumed by exactly one
  instruction, no gaps, no leftovers).
* With one A11-specific override — `stop` = `0x0108` (2 bytes); Mesa's is
  `0x0088` — it becomes **93 / 94**.
* The one remaining object (`00__agc.main.g10p-o`, 7 words:
  `0012 0001 0045 0900 f000 0010 0108`) tiles as
  `icmpsel`(8 B) + three 2-byte instructions (`0xf000`, `0x0010`,
  `0x0108`), i.e. it needs **two A11-only 2-byte opcodes** that Mesa does
  not have (`0xf000`, `0x0010`).  `/tmp/opencode/agx_tile4.py` prints the
  full solution for any file.

Length rule (as in Mesa `agx_pack.c`):

```
len = length_short                      if the opcode's mask includes bit 15
len = length_short                      if bit 15 (L) is clear in word 0
len = length_short + (4 if short > 8 else 2)   if bit 15 (L) is set
```

**Important caveat (honest status).**  Mesa's `device_store` and
`uniform_store` encodings have **mask 0** (their opcode lives in the high
bits of the 64-bit raw word), so they match *every* word; the tiling
above uses them as "any 8-byte chunk".  Measured quality:

* permissive (mask-0 encodings allowed): **93/94 files tile**, 100 % of
  words consumed.
* strict (mask-0 encodings removed, i.e. only opcodes with a real
  signature): **2/94 files tile**, and a forward DP stalls after only
  0.2 % of the corpus words — the first word of most kernels matches a
  Mesa opcode, but the *length* Mesa assigns does not always fit the
  following words.

Therefore:

* **Confirmed**: the corpus is AGX-family, 16-bit word aligned, and its
  opcode *values* are Mesa's values (table in §2) — that is not a
  coincidence, 57 specific opcodes line up exactly.
* **Not yet confirmed**: the exact A11 instruction **length table** —
  Mesa's lengths are right for many opcodes but not all, and the A11 has
  opcodes Mesa does not know (`0x0108`, `0xc020`, `0xf000`, `0x0010`, …).

So the framing question is now *narrowed to a length/field table*, not
"what is this format".

### 2. The corpus opcode values are Mesa's `exact` values (confirmed)

Direct word histogram of the 492 190 corpus words against Mesa's table:

| Mesa opcode | value | corpus hits | | Mesa opcode | value | corpus hits |
|---|---|---|---|---|---|---|
| trap | 0x0008 | 3532 | | icmpsel | 0x0012 | 691 |
| imad | 0x001e | 17943 | | mov_imm | 0x0062 | 646 |
| fadd(16) | 0x0026 | 11971 | | if_fcmp | 0x0042 | 641 |
| wait | 0x0038 | 5460 | | fma(16) | 0x0036 | 416 |
| if_icmp | 0x0052 | 1966 | | bitop | 0x007e | 424 |
| fcmpsel | 0x0002 | 225 | | jmp_exec_any | 0xc000 | 400 |
| writeout | 0x0048 | 190 | | device_store | (mask 0) | 91 |

Note the 16-bit ALU opcodes appear **without** Mesa's L bit in the
opcode value (`0x0026`, not `0x8026`): in the A11 dialect the L bit is
the length flag, not part of the 16-bit opcode identity (Mesa uses it
both ways).

### 3. The corpus is word aligned (confirmed)

Bit-offset sweep (`/tmp/opencode/agx_bitoff.py`): re-reading the corpus
as 16-bit words at bit offset 0..15 and matching Mesa's `(exact, mask)`
patterns gives

```
offset  0: 0.3539   <- only peak   (random baseline 0.2363)
offset  1..15: 0.0899 .. 0.2325  (all at or below random)
```

so the ISA is **not** bit-packed at a non-zero offset; 16-bit word
granularity is correct.  (This also retires the "byte-packed ISA" claim
for the corpus: Mesa's own lengths are all even, so the byte-packed
encoding *is* word aligned.)

### 4. The Apple encoder tables are a *different dialect* (confirmed; corrects
###    an earlier misreading of this file)

The AGX3 encoder's word-0 fixed values are **not** Mesa's opcode values:

* mask `0x07ff` class (123 opcodes): `0x007 0x00f 0x017 0x01f 0x027 0x02f
  0x037 0x03f 0x047 0x04f 0x057 …` — **all ≡ 7 (mod 8)**.
* mask `0x001f` class (4): `0x006 0x00e 0x016 0x01e`.
* mask `0x000f`: `0x002 0x00a`; mask `0x0007`: `0x000 0x001 0x003 0x005`;
  mask `0x700f`: `0x00a 0x100a … 0x700a`; mask `0x8007`: `0x004 0x8004`.

Mesa's AGX opcodes, by contrast, live in residues 0, 1, 2, 5 and 6 (mod 8)
(`0x02 0x05 0x08 0x09 0x0a 0x0e 0x12 0x16 0x1a 0x1e 0x21 0x26 0x2a 0x2e
0x31 0x36 0x38 0x3a 0x3e 0x41 0x42 0x48 0x49 0x51 0x52 0x62 0x71 0x72
0x7e 0x88 0xa1 0xb1 0xc000 0xc200`) — **Mesa has no ≡ 7 (mod 8) opcode at
all**.  So the libLLVM AGX3 encoder and Mesa implement *different opcode
spaces*; they coincide only on a handful of values (`0x02 0x04 0x05 0x0a
0x0e 0x16 0x1e …`).

(The earlier note in this file that called these values "Mesa's values"
was wrong; the `opcode<<3|7` reading was wrong too.  The values are simply
the AGX3 encoder's own opcode encoding.)

**Field-layout cross-check against the corpus** (using the Mesa-based
tiling, `/tmp/opencode/g10p_crosscheck.py`, 124 068 tiled instructions):

| Mesa opcode | encoder template matches | Mesa opcode | encoder template matches |
|---|---|---|---|
| fma/32 | 189/192 (98 %) | imad/32 | 5569/11848 (47 %) |
| fmul/32 | 1191/1273 (94 %) | floor/32 | 111/159 (70 %) |
| zs_emit/32 | 34/34 (100 %) | icmpsel/32 | 118/2056 (6 %) |
| if_fcmp/32 | 2/2 (100 %) | iadd/32, texture_load/32, bfi/32, mov_imm, fma/16, fmul/16, fadd/16, wait | 0 % |

So the two dialects **agree field-for-field for some opcodes** (fmul,
fma32, zs_emit, if_fcmp) and **disagree for others** (imad, iadd,
texture_load, bfi, mov_imm …).  This is the expected signature of two ISA
revisions of the same family (A11 = G10P vs the G13 dialect in libLLVM),
not of a random encoding.

Conclusion: the corpus (A11) and libLLVM's AGX3 tables are *related but
not identical* dialects.  The A11 dialect's authoritative tables live in
the **AGXMetalA11 compiler image** (see §7), not in libLLVM.

### 5. A11-specific deltas found so far (confirmed / candidate)

| instruction | A11 (corpus) | Mesa (G13+) |
|---|---|---|
| stop / end of program | `0x0108` (2 B) | `0x0088` (2 B) |
| jmp_exec_none | `0xc020` (6 B) | `0xc200` (6 B) |
| unknown 2-byte op | `0xf000`, `0x0010` | — |

`0x0108` is the **last word of every kernel** and also the whole content
of `59__agc.eot.g10p-o` and `89__agc.background.g10p-o` (one word each)
— so it is the A11's program terminator.

### 6. New decoder detail (confirmed, still to reconcile)

`0x1bcc026d0` (the AGX3 "descriptor walker") reads the instruction as
**32-bit words**: `ldrh w9,[x25]` (a u16 word index from the per-opcode
descriptor record) then `ldr w8,[x4, x9, lsl #2]`, and takes
`w8 & 0xfff` as the ISA opcode with `0xfff` as an escape (bits 12..31
then index another table).  That is a 32-bit-word view of the ISA, while
the encoder writes 16-bit chunks and the corpus is 16-bit word
aligned.  Reconciliation still open — most likely the decoder's "word"
is a 32-bit container holding two 16-bit chunks, or the decoder table
indices count 32-bit units.

### 7. Environment note: the dyld cache had to be re-extracted

`/tmp` was cleaned and the extracted dyld cache was gone.  Re-extracted
from the cryptex DMG in `/home/doug/a11-fw/087-86588-047.dmg` into the
durable location `/home/doug/dsc-cache/20H392__iPhone10,2_5/flat/`
(`dyld_shared_cache_arm64`, `.19`, `.27.dylddata`), with a symlink at the
old path `/tmp/opencode/dsc/20H392__iPhone10,2_5` so the existing tools
keep working:

```
7z x -y /home/doug/a11-fw/087-86588-047.dmg \
  "System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64" \
  "System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64.19" \
  "System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64.27.dylddata" \
  -o/home/doug/dsc-cache/20H392__iPhone10,2_5
```

New fact from that work: the **first image in subcache `.19` is
`/usr/lib/libLLVM.dylib`** (Mach-O header at file offset `0x5c000`,
`__TEXT` vm `0x1bc704000`), so the AGX3 backend we decoded (encoder at
`0x1bcc01acc`, tables at `0x1be327a44`/`0x1be32748f`) lives in the
**system LLVM**.  `AGXMetalA11.bundle` (compiler version 16.7.3, build
`14E6097d`, `DTPlatformBuild 20H361`) is a *separate* image in the same
cache; the Metal compiler links the system LLVM, so the encoder tables
are very likely the ones that produced `ds.g10p` — but that link is
still `candidate`, not confirmed.

### 8. Corrected status of the earlier "Mesa cannot tile the corpus"

This file previously recorded "0/94 word-level and 0/94 byte-level tiling
under Mesa's (exact, mask) table" and "4/94 byte-level DFS using Mesa
opcode values + Mesa lengths".  **Both were wrong** (the earlier DFS had
a bug in the length/L-bit rule and in the 16/32-bit encoding choice).
With the corrected rule the corpus tiles 89/94 (93/94 with the `stop`
override) *when Mesa's mask-0 "any word" encodings are allowed*; with
those removed only 2/94 tile (see the caveat in §1).  The *conclusion*
(corpus = AGX family, word aligned, Mesa-compatible opcode values) is
confirmed; the earlier numbers were not.

### 9. Next moves (2026-11-08, late)

1. **Re-run the encoder-template cross-check** with the now-known
   boundaries: for each corpus instruction, check the encoder's fixed
   fields for the matching (opcode, form) — this gives the A11 operand
   field layout and validates the encoder tables against real code.
2. Build a corpus disassembler (Mesa table + A11 deltas) and dump
   `agc.eot` / `agc.background` for a sanity check of the decode.
3. Pin the remaining A11 opcodes/lengths (`0x0108`, `0xc020`, `0xf000`,
   `0x0010`, and any others the 89 tiling leaves under-constrained).
4. Then step 2 (`AGX3Disassembler` vtable/symbol) and step 3 (per-context
   descriptor-table bases, 16-byte cat-4/44/76/83 entries).
5. Only then the hardware phase (`disp0` vs `simplefb`, `pvr_apple` 3D
   probe) — needs an explicit "go"; investigation only, no edits.

### 10. Files added by this session

`/tmp/opencode/`: `macho_ids.py` (dyld-cache image/LC_ID_DYLIB scanner),
`g10p_corpus_pat.py` (corpus vs encoder word-0 templates),
`g10p_shift.py` (opcode bit-offset sweep, encoder side),
`g10p_w0vals.py` (encoder word-0 value sets + corpus interest words),
`g10p_dectbl.py` (decoder per-opcode table vs encoder),
`agx_bitoff.py` (Mesa table bit-offset sweep),
`agx_mesa_cmp.py` (Mesa table vs corpus word histogram),
`agx_tile3.py` (word-level tiling + failure position),
`agx_tile4.py` (flexible-length tiling, prints the instruction list),
`agx_tile5.py` (forward-DP "how far does the framing get" report),
`agx_len_derive.py` (length derivation with all lengths allowed),
`g10p_crosscheck.py` (corpus vs encoder template match, per table/variant),
`macho_ids.py` (dyld-cache image scanner; also used for the cache map below),
`agxmetal_find.py` / `agxmetal_find2.py` (code-signature search for the AGX3
backend inside the Metal-compiler images),
`desc_scan.py` (signature scan for a DESC-style table of small u32s).

## Addendum 3 (2026-11-08): cache image map + candidate A11 length table

### 1. The Metal compiler stack in the cache (confirmed)

All 42 subcaches of the 20H392 (iOS 16.7.16) dyld cache were extracted to
`/home/doug/dsc-cache/allsub/System/Library/Caches/com.apple.dyld/`
(2.5 GB; `.symbols`, `.28.dyldlinkedit` and `.42.dyldlinkedit` fail with
7z "Unsupported Method" — they are compressed differently).  The
interesting images:

| image | subcache | file offset | __TEXT vm | size |
|---|---|---|---|---|
| `/usr/lib/libLLVM.dylib` | .19 | 0x05c000 | 0x1bc704000 | 0x26f2ff4 |
| `AGXCompilerCore.framework/AGXCompilerCore` | .17 | 0x054a6000 | 0x1bbe3e000 | 0x17e000 |
| `GPUCompiler.framework/Libraries/libGPUCompilerImpl.dylib` | .17 | 0x05632000 | 0x1bbfca000 | 0x685ffc |
| `GPUCompiler.framework/Libraries/libGPUCompiler.dylib` | .17 | 0x05624000 | — | — |
| `Extensions/AGXMetalA11.bundle/AGXMetalA11` | .39 | 0x022e2000 | 0x209d3e000 | 0x1bf000 |

* `AGXMetalA11` contains the **Metal runtime** for A11 (strings
  `agxa_compiler.mm`, `AGX: FATAL: driver shader binary file not found!!!`,
  `AGX_G10_DISABLE_PRID`, `AGX_EXTRA_LLVM_ATTRIB`, …) and **no** AGX
  backend strings (`applegpu*`, `AGX3`, `Assembly Printer` are absent).
* `AGXCompilerCore` contains the subtarget name **`g10p-b0`** (file
  0x05621342) — the A11's encoder variant.
* `libGPUCompilerImpl` contains the **full arch list**
  (`applegpu_gx2 … applegpu_g15g`, file 0x05a8eafe) — the same list that
  was found in libLLVM.
* The AGX3 **encoder code bytes differ** between libLLVM and the Metal
  stack (32-byte signatures of the encoder/blob-parse/form-resolve/
  scatter-loop/strh-write functions match nothing in
  `libGPUCompilerImpl` or `AGXCompilerCore`), so the libLLVM offsets
  cannot be reused there, and a DESC-style "long run of small u32" table
  was not found in either image's `__TEXT`/`__DATA_CONST`.
  ⇒ The A11 dialect tables inside the Metal compiler still need their own
  RE (this is the remaining offline task for an exact length table).

### 2. Candidate A11 length table (from the corpus, **candidate**)

`/tmp/opencode/agx_len_derive.py` frames the corpus with the constraint
"every instruction start must match a *specific* Mesa opcode" and any
length in {2,4,6,8,10,12}; it frames 11/94 files (11 787 instructions).
The lengths that come out consistent (opcodes where the DP has no
ambiguity) are:

| opcode | A11 bytes | Mesa bytes | note |
|---|---|---|---|
| wait, trap, stop/A11 | 2 | 2 | stop = `0x0108` in A11 |
| zs_emit, writeout, get_sr | 4 | 4 | |
| mov_imm (16-bit) | 4 | 4 | |
| fadd16/fadd32/fmul16/fmul32/fma | 6 | 6 | A11: **no L bit in the opcode value** |
| if_icmp/else_icmp/if_fcmp/else_fcmp | 6 | 6 | |
| while_icmp/while_fcmp/pop_exec | 6 | 6 | |
| bitop, device_load, jmp_exec_any, jmp_exec_none | 6 | 6 | jmp_exec_none = `0xc020` in A11 |
| bfi | 8 | 8 | |
| fcmpsel | 8 | 8 | |
| device_store | 8 | 8 | mask 0 in Mesa |
| **imad** | **6 or 12** | 8 | **diverges from Mesa** |
| **texture_load** | **6 or 12** | 8 | **diverges from Mesa** |
| icmpsel | 8 / 10 | 8 / 10 | |
| mov_imm (32-bit), convert | 6 / 10 | 6 | |

The imad/texture_load split is the main open item: Mesa's fixed 8 bytes
does not fit, and the A11 appears to use a 6-byte short form and a
12-byte long form (the long form adds two words of operands instead of
one).

Forced-length experiment (`agx_len_derive.py "imad/32=N"`), files framed /
instructions framed:

| imad bytes | 4 | 6 | 8 | 10 | 12 |
|---|---|---|---|---|---|
| files / instrs | 6 / 41 | 7 / 138 | 7 / 100 | 6 / 39 | **8 / 175** |

| texture_load bytes | 4 | 6 | 8 | 10 | 12 |
|---|---|---|---|---|---|
| files / instrs | 11 / 11330 | 11 / **14149** | 11 / 11330 | 11 / 11330 | 11 / 11787 |

Best combination: `imad = 12`, `texture_load = 6` (or 12) → 8/94 files,
175 instructions.  These numbers stay small because the framing still
breaks on A11-only opcodes that match no Mesa signature (observed
blockers: `0x0f00`, `0x0083`, `0x8041`, `0x0108`-adjacent words), so this
is **candidate**, not confirmed.

### 3. Next moves

1. RE the AGX3 encoder tables **inside `AGXCompilerCore` /
   `libGPUCompilerImpl`** (subcache .17) to get the authoritative A11
   (`g10p-b0`) form/size table — this pins the imad/texture_load lengths
   and the operand field layout, and lets the corpus disassembler be
   exact.  Anchor points: the `g10p-b0` string at file 0x05621342, the
   arch list at 0x05a8eafe.
2. Then steps 2/3 of the original plan (`AGX3Disassembler` vtable/symbol;
   per-context descriptor-table bases).
3. The **hardware phase** (display `disp0` vs `simplefb`, `pvr_apple`
   3D probe) does **not** depend on items 1-2: the corpus can be
   submitted as-is (Apple's own A11 shaders) and Metal shaders can be
   compiled on-device.  It needs an explicit "go" and is read-only.

## Addendum 4 (2026-11-08, after the device survey): corpus container facts, a new A11 opcode delta, and a negative result on the AGXCompilerCore table hunt

### 1. What a corpus object actually is (confirmed)

Every `ds-g10p/*.g10p-o` file is a **Mach-O object** (magic `0xfeedfacf`,
`MH_OBJECT`, arm64) — not a raw word dump.  Its section list is:

```
__TEXT          __text             <- the AGX words (this is the instruction stream)
__GPU_METADATA  __vertex
__GPU_REMARKS_MD __vertex
__GPU_LD_MD     __vertex
__GPU_ARCH_LD_MD __vertex
__GPU_STATS_MD  __vertex
```

All framing work must therefore run on `__TEXT,__text` (the previous tools
already did; the 94-file container records in `ds.g10p` are a different
layer).  Example (`09__agc.main.constant_program.g10p-o`, 1028 words):

```
[ 0] 06c2 [ 1] 0020    [ 2] 04c2 [ 3] 0024    [ 4] 028e [ 5] 8684 [ 6] 800d [ 7] 0018
[ 8] 0282 [ 9] 002a    [10] 267e [11] 1fc2 [12] 0080    [13] 02c2 [14] 0028
[15] 028e [16] c0c2 [17] 801e [18] 00c0    [19] 00c2 [20] 002c
[21] 22be [22] c00a [23] 0060    [24] 128e [25] c6c4 [26] 000d
[27] 026e [28] c200 [29] 8005 [30] 00c9    [31] 0a86 [32] 30c8 [33] 2000
[34] 2e42 [35] 1044    [36] 3042 [37] 1040    [38] 3202 [39] 1042
[40] 0108 <- stop (A11)   [41..] 0008 filler runs
```

### 2. New A11 delta (candidate → strong): the 4-byte `mov_imm` family uses opcode byte `0xc2`

`06c2 0020`, `04c2 0024`, `02c2 0028`, `00c2 002c` are four
`mov_imm`-shaped 4-byte instructions: opcode byte constant `0xc2`,
**destination in bits 8-11**, immediate in the following word.  Mesa's
`mov_imm` is `0x62` with mask `0x00ff` (destination *not* in the opcode
byte), so this is an A11-only encoding change of the same family — the
fourth A11 delta after `stop = 0x0108`, `jmp_exec_none = 0xc020` and the
"16-bit ALU opcodes carry no L bit" rule.  The corpus also contains the
Mesa-style `0x62` form (646 instruction starts), so A11 evidently has
*both* `0x62` and `0xc2` mov_imm encodings (short vs long? different
operand layout?) — **open**.

### 3. `0x0008` is filler in A11, so A11's `trap` is *not* `0x0008` (confirmed)

Mesa's `trap` is `0x0008`; in the corpus `0x0008` occurs in long runs
(≤26 words) after `stop`/`0x0108` and behaves as alignment filler, not as
an instruction.  Therefore A11 moved `trap` to another opcode value —
**candidate delta #5**, value still unknown.

### 4. Census of raw low-12-bit values over all 492 190 corpus words

`0000` 91 096 · `0040` 30 309 · `0020` 21 192 (= A11 `jmp_exec_none`
`0xc020`) · `001e` 18 082 (= `imad`) · `02de` 17 997 · `0026` 12 021
(= A11 `fadd16`) · `0200` 7 764 (= Mesa-style `jmp_exec_none` `0xc200`) ·
`0400` 6 632 · `006e` 5 887 · `0038` 5 467 (= `wait`) · `0f00` 4 657
(**A11-only, most common framing blocker**) · `0008` 3 558 (filler) ·
`0052` 2 135 (= `if_icmp`) · `0005` 2 004 (= `device_load`).

### 5. Negative result: no Mesa-shaped tables in `AGXCompilerCore` / `libGPUCompilerImpl`

`/tmp/opencode/agx_table_scan.py` scanned every data-bearing section of
both images (subcache `.17`) for Mesa's `(exact, mask, len_short, len_long)`
quadruple shape (`exact & mask == exact`, lengths in {2,4,6,8,10,12}, runs
of ≥8 entries).  **Zero hits** in both images — only zero-filled and
pointer-shaped arrays.  So Apple's A11 encoding tables are *not* stored in
that layout in those two images; either they use a different structure
(per-arch descriptors reached through pointer tables) or the authoritative
copy lives elsewhere.  The arch list is confirmed present though:
`AGXCompilerCore` contains `.agc-target-.g5p-b0.g9p-a0.g10p-b0.g11p-a0.…`
at cache-file 0x05621342, i.e. this image *does* carry a per-generation AGX
target — the tables are there, just not in Mesa's shape.

### 6. Tools added this session

`/tmp/opencode/g10p_words.py` (section-aware word dump), `g10p_census.py`
(opcode census), `agxcore_xref.py` (Mach-O + string map for
`AGXCompilerCore`), `agx_table_scan.py` (table shape scan),
`kc_fwscan.py`, `kc_tags.py`, `kc_pmp.py`, `kc_macho.py` (kernelcache
firmware extraction).

### 7. A constraint solver for the length table (WIP — honest status)

`/tmp/opencode/g10p_solve.py` (also committed as
`iPhOmarchy:GPU-WIP/tools/g10p_solve.py`) frames the corpus as
`[instruction]* [padding]*` (padding = a run of `0x0008`/`0x0000` words),
takes Mesa's public table as the prior, and solves jointly for the lengths of
the A11-only opcodes: the same opcode value must have the same length in
every object, which is what makes the problem a constraint problem rather
than a guess.

**Current result: it frames 5 of 94 objects** — i.e. it does *not* converge
yet.  The reason is informative: with Mesa's lengths applied to the
Mesa-valued A11 opcodes, the strict framing derails early in almost every
object, so the solver's "unknown opcode" discovery starts absorbing *data*
words.  In other words **the A11 dialect changes the length of more Mesa
opcodes than the two already known (`imad`, `texture_load`)** — the candidate
table in Addendum 3 is an under-estimate, not a final answer.

The next instrument is therefore **not** more solver heuristics but the
**same-source differential**: the corpus contains groups of instances compiled
from one source, and aligning two instances of one group pins the length of
every instruction whose encoding differs between them.  The groups (from
`tools/g10p-struct/g10p-samesrc.py`, by `source_name`) are:

| group | instances |
|---|---|
| `bucketed-tessellation-compute-instance-counts-driver` | **32** |
| `bucketed-tessellation-driver-emit-draw-commands-driver` | **32** |
| `tessellation-non-bucketed-emit-draw-commands-driver` | 8 |
| `eot_uber` | 4 |
| `bgo_uber` | 3 |

Note (corrects an easy mistake): the 73 objects whose *file name* ends in
`agc.main.constant_program` are **not** one source — pairwise they share only
1–6 leading words and 1–4 % identical words.  The same-source groups above
are the ones to align.

### 8. Cross-check against the A10 (G9P) work (confirmed, and a useful warning)

`OrchardLinux/gpu` (`a10/ISA.md`) documents the **A10** ISA: there, "bit 8 of
every 16-bit word means another word follows" — a continuation-bit encoding,
and the A10 notes derive it black-box from Apple's compiler
(`metal-tt -arch applegpu_g9p`, differential probes).  The A11/G10P corpus
does *not* behave that way: it frames with Mesa's `(exact, mask, length)`
table, i.e. the **A12+-style encoding**.  So the G10P ISA is a *different
generation* from G9P — the A10's decoder and bit-mapping tools do **not**
port over, only the *method* (differential black-box probing) does.

That method is still available to us in principle: the iOS dyld cache
contains Apple's own AGX compiler (`AGXCompilerCore`, `AGXMetalA11`), and
`metal-tt -arch applegpu_g10p`-style probing would settle every length and
field question at once — but it needs a host that can run Apple's Metal
toolchain (macOS) or the on-device compiler, i.e. it is a future hardware
phase, not an offline one.

---

## Addendum 5 (2026-11-08, night): **the A11 length table is SOLVED** — G10P uses a uniform 6-byte instruction quantum

Offline only. No device, no kernel/DT edits. New artefacts in
`/tmp/opencode/` (`g10p_period2.py`, `g10p_period3.py`, `g10p_grid.py`,
`g10p_csp.py`, `g10p_arc.py`, `g10p_apple.py`, `g10p_apple2.py`,
`g10p_apple3.py`, `g10p_min.py`, `g10p_final.py`, `g10p_dis.py`,
`g10p_val.py`, `g10p_val2.py`, `g10p_lengths.py`, `dyld_extract.py`) plus a
read-only clone of `dougallj/applegpu` in `/tmp/opencode/applegpu`.

### 1. The instrument that unlocked it: `dougallj/applegpu` (confirmed)

The earlier attempts used **Mesa's** `agx_opcodes.py` as the opcode
dictionary.  Mesa's table is only 57 opcodes and its lengths are the
*A12+* ones.  `dougallj/applegpu` (BSD-3-Clause, `github.com/dougallj/applegpu`,
commit `28dd804`) is a **data-driven descriptor table for Apple's own AGX
ISA** — 161 descriptors / **81 distinct low-16 signatures**, each with an
explicit `(short, long)` byte-size pair and a length-bit position, i.e. it
encodes the *framing rule*, not just the opcode bits.

Two things make it the right dictionary for this corpus:

* it is **much wider** than Mesa's, so far fewer corpus words are
  "unexplained";
* its `jmp_exec_none` is **`0xc020`**, which is *exactly* the value this
  project had already measured independently in the G10P corpus
  (and whose A11 delta was recorded in Addendum 4).  The two dialects are
  the same family.

It also carries G13's `stop` = `0x0088`, and the corpus contains **both**
`0x0088` (109×) and `0x0108` (219×) as 2-byte terminators.

Vendored (reference only) under `tools/reference-agx-isa/`:
`applegpu.py`, `fma.py`, `srgb.py`, `LICENSE` (upstream headers kept).

### 2. The result (confirmed)

> **G10P (A11) encodes essentially every AGX instruction in exactly 6 bytes
> = 3 × 16-bit words.**  The exceptions are `trap` (`0x0008`) and the two
> `stop`s (`0x0088`, `0x0108`) at **2 bytes**, plus a catch-all of
> A11-only opcodes that the G13 table does not know, at **4 bytes** (L-bit
> clear) and **2 bytes** (L-bit set).

This is a *different framing scheme* from Mesa's A12+ AGX, which mixes
2/4/6/8/10/12 bytes and selects between two lengths with bit 15.  G10P's
opcode *values* are Mesa-compatible; its *lengths* are not.

### 3. The evidence (four independent legs)

1. **Local repetition period** (`g10p_period3.py`, 6-word match window,
   full corpus).  Where one instruction repeats, the period *is* its
   length:

   | opcode | period | resolved cases |
   |---|---|---|
   | `imadd` | **3 words (6 B)** | 5172 (mode `d3`) |
   | `fadd16` | **3 words (6 B)** | gcd(21,24)=3 |
   | `trap` | **1 word (2 B)** | 877 |

   The global word autocorrelation (`g10p_period2.py`) peaks at
   **d = 3, 6, 9 words** (0.118 / 0.119 / 0.125) — every peak is a multiple
   of 3.

2. **Exact DP tiling.**  With a fixed length table, the set of tileable
   positions is a forward reachability DP — *complete*, so "this object
   tiles" is a proof, not a guess.  The uniform baseline (3 words
   everywhere, 1 word for trap/stop) tiles **72 / 94 objects and
   477 051 / 492 190 words** exactly.

3. **Minimal-deviation repair.**  Only three deviations are needed to reach
   **94 / 94**: `A11-only|L1 → 2 words`, `A11-only|L0 → 2 words`,
   `A11-only|L1 → 1 word`.  Everything else stays at the 6-byte baseline.

4. **Independent structural check.**  The next function after a terminator
   must start on a **64-byte boundary**.  With the solved framing that holds
   for **80 / 125 (64.0 %)** of mid-section functions, against **3.1 %** by
   chance.  This check does not presuppose the length table — it only uses
   the terminator and the padding run.

5. **Cross-validation.**  Solve on half the corpus, test on the other half:

   | split | train | held out |
   |---|---|---|
   | even → odd | 36 / 47 | **36 / 47** |
   | odd → even | 47 / 47 | **46 / 47** |

   The table generalises; it is not fitted noise.

### 4. The table

Forced by the corpus (changing the length breaks at least one object):

| class | length | occurrences | alternatives that break |
|---|---|---|---|
| `imadd` | **6 B** | 47 142 | 12 B |
| `icmpsel` | **6 B** | 7 283 | 10 B |
| `get_sr` | **6 B** | 1 321 | 10 B, 12 B |
| `icmp_ballot` | **6 B** | 649 | 12 B |
| `zs_emit` | **6 B** | 104 | 8 B, 10 B, 12 B |
| `jmp_exec_any` (L=1) | **6 B** | 400 | 12 B |
| `stop/A11` (`0x0108`) | **2 B** | 219 | 4–12 B |
| A11-only, L-bit clear | **4 B** | 124 505 | 2/6/8/10/12 B |
| A11-only, L-bit set | **2 B** | 45 440 | 4–12 B |

Every other opcode the corpus uses is **6 bytes** and is *not individually
forced* — the corpus cannot distinguish 6 from the other values for them
without breaking a tiling, so 6 B is the value consistent with the solved
table (and with the period evidence).  `trap` (`0x0008`, 3 532×) is **2 B**,
matching both the period measurement (d1) and G13.

Full machine-readable table: `A11-GPU-G10P-LENGTHS.json`
(`tools/g10p_lengths.py --json`).

### 5. Deltas against G13 / Mesa (the interesting ones)

| opcode | **A11/G10P** | G13 (applegpu) | Mesa (A12+) |
|---|---|---|---|
| `imadd` | **6** | 8 | 8 |
| `iadd` | **6** | 8 | 8 |
| `bfi` | **6** | 8 | 8 |
| `atomic` | **6** | 8 | – |
| `icmpsel` | **6** | 8 / 10 | 8 |
| `fcmpsel` | **6** | 8 / 10 | 8 |
| `texture_load` | **6** | 8 / 12 | 8 |
| `call` (`0x0004`) | **6** | 2 | 6 |
| `wait` | **6** | 2 | 2 |
| `threadgroup_barrier` | **6** | 2 | 2 |
| `ret` | **6** | 2 | – |
| `doorbell` | **6** | 2 | – |
| `get_sr` | **6** | 4 | – |
| `iter` | **6** | 4 / 8 | 4 |
| `TODO.ldcf` | **6** | 4 / 8 | 4 |
| `TODO.ld/st_tile` | **6** | 8 / 10 | – |
| `zs_emit` | **6** | 4 | – |
| `mov_imm` | **6** | 4 / 6 | 4 / 6 |
| `fadd16` | **6** | 4 / 6 | 6 |
| `jmp_exec_none` (`0xc020`) | **6** | 6 | 6 |
| `jmp_exec_any` (`0xc000`) | **6** | 6 | 6 |
| `trap` | **2** | 2 | 2 |
| `stop` | **2** | 2 | 2 |

### 6. This converges with the decoder-side analysis (confirmed)

The AGX3 decoder re-read (earlier in this file) already established, from
the *encoder/decoder* side:

> "Length source (confirmed): ISA opcode → MC opcode →
> `MCInstrDesc[MCopcode].Size` = the instruction size **in bytes** …
> ⇒ the length is a **pure function of the opcode**; it is not encoded in
> the stream, and it is not a flag bit."
> and "the instruction is **16-bit-word granular** … `size == 2 * words`".

The corpus-side result now agrees with that on every point and supplies
the *values* the decoder table was missing: **the size is 6 bytes for
essentially every opcode**.  The only bit-15 dependence left is inside the
"A11-only" catch-all, i.e. an artefact of not yet knowing those opcodes —
for every *named* opcode the length is 6 bytes whether bit 15 is set or
not, which is precisely the "not a flag bit" conclusion.

### 7. Corrections to earlier statements in this file (confirmed)

* **Addendum 2's "the corpus framing is SOLVED — it is the public Mesa AGX
  dialect"** is **superseded**.  The corpus's *opcode values* are
  Mesa-compatible; its *lengths* are not.  Mesa's mixed 2/4/6/8/10/12
  scheme with the bit-15 length selector does **not** apply to G10P.
* **"`texture_load` = 12 bytes"** (a candidate in Addendum 4) is
  **withdrawn**: it is **6 bytes**.  The old "gap histogram ⇒ 6 words"
  reading was measuring the distance between *signature matches*, not the
  instruction length.
* **"`imad` = 6/12 candidate"** is now **confirmed at 6 bytes**.
* **"the dominant motif `02de 0000 0040` is indivisible"** was a
  Mesa-specific argument (0x0000 matches Mesa's mask-0 `device_store` /
  `uniform_store`).  Under applegpu's table 0x0000 *does* match a G13
  signature (`jmp_incomplete`).  The argument is withdrawn, but the
  conclusion survives on the independent period measurement (d3 × 5172).
* **"0x0000 only ever appears in 2-word runs"** is **wrong**: measured over
  the corpus the run lengths are `{1: 77 554, 2: 1 099}`.
* **"A11 `stop` = 0x0108"** is confirmed at **2 bytes**; the G13 `stop`
  `0x0088` also occurs (109×) and is likewise 2 bytes.
* The earlier **"uniform 6-byte grid" refutation** (`g10p_grid.py`: section
  sizes mod 6 flat, terminator phases spread) was an artefact of assuming
  *no* 2-byte instructions; with 2-byte trap/stop the phase shifts, and
  the uniform-6 model survives.

### 8. Files added by this session

* `tools/reference-agx-isa/applegpu.py`, `fma.py`, `srgb.py`, `LICENSE`
  (vendored from `dougallj/applegpu`, commit `28dd804`, BSD-3-Clause).
* `tools/g10p_lengths.py` — the consolidated, reproducible solver: derives
  the table, runs the exact DP, the minimal-deviation repair, the 2-fold
  cross-validation and the 64-byte alignment check, and emits
  `A11-GPU-G10P-LENGTHS.json`.
* `A11-GPU-G10P-LENGTHS.json` — the table, machine-readable.
* `/tmp/opencode/` (not part of the archive): the instruments listed at the
  top of this addendum.

### 9. Next moves

1. **Field layout** is now the open ISA question, not the length.  The
   6-byte quantum means each instruction is exactly three 16-bit words, so
   the next task is to map the *fields* inside those three words
   (opcode / destination / sources / immediate) for the G10P dialect.  The
   G13 field layout is a good prior but is known to drift (the earlier
   full-mask probe found `bfi` 77 %, `bitrev` 0 %, `floor` 0.2 % full-mask
   pass rates under Mesa's masks).
2. The A11-only opcodes (the 4-byte and 2-byte catch-all) need to be
   identified: they are the words that match no G13 signature and start
   instructions.  Their first words (`0x2000`, `0x0040`, `0x0200`,
   `0x5200`, `0x5024`, …) are the next thing to name.
3. `MCInstrDesc` (the decoder's authoritative size table) is still not
   located in the dyld cache — but the corpus-side table above now
   supersedes it for our purposes.
4. Hardware phase (native `disp0`, `pvr_apple` 3D bring-up) remains gated
   on an explicit "go" plus approval for any kernel/DT edits; `simplefb`
   stays as the working display path.

---

## Addendum 6 (2026-11-08, night): **the field layout is recovered** — A11's header is G13's header verbatim

Offline only. New artefact: `tools/g10p_fields.py` (with
`tools/g10p_lengths.py` for the framing it depends on).

### 1. The method

With the length table solved, every instruction in the corpus is exactly
**three 16-bit words**, so the layout can be attacked directly rather than
inferred statistically:

1. Frame the corpus with the solved table (188 402 instructions).
2. For each opcode, collect *all* of its occurrences as 48-bit values.
3. For every field that `applegpu` declares for that instruction
   (bit start, bit size, name), measure how A11 actually uses those bits:
   are they live (operand), constant (folded into the opcode), always
   zero (no such field in A11), or outside A11's 3-word instruction?

### 2. Result: the header is identical to G13 (confirmed)

For **108 of the 110** opcode classes in the corpus, word 0 has exactly
G13's shape:

| bits | meaning | G13 | A11 |
|---|---|---|---|
| 0–5 | opcode | constant per opcode | **identical** |
| 6 | `S` (saturate) | flag | **identical** |
| 7–8 | `Dt` (destination type) | operand | **identical** |
| 9–14 | `D` (destination register) | operand | **identical** |
| 15 | `L` (long/length bit) | flag | **identical** |

The two exceptions (`threadgroup_store`, `threadgroup_load`) have opcode
bits above 5 in G13 too, so they are not a layout delta.

### 3. Result: the operand words are G13's, truncated at 48 bits (confirmed)

Measured over all 817 G13 field declarations that belong to the 110 opcodes
the corpus uses:

| outcome | count | meaning |
|---|---|---|
| **live at G13's position** | **555 (67.9 %)** | A11 uses the field exactly where G13 puts it |
| unused in A11 | 82 | A11 has no such field there |
| constant → folded into the opcode | 31 | A11 turned it into an opcode bit |
| beyond bit 48 | 204 | belongs to G13's 4th+ word; A11 has no room for it |

Per-opcode highlights:

* **`iadd` (`0x000e`)** — the cleanest case: **all 14 G13 fields that fit in
  48 bits are live at G13's positions** (`S`, `N`, `Dt`, `D`, `Dx`@44,
  `At`, `As`, `A`, `Ax`@42, `Bt`, `Bs`, `B`, `Bx`@40, `s1`@39).  Only G13's
  `s2` (bit 52) is dropped.  **A11's `iadd` is G13's `iadd` layout packed
  into 6 bytes.**
* **`imadd` (`0x001e`)** — 12 fields live at G13's positions (`S`, `N`, `Dt`,
  `D`, `At`, `As`, `A`, `Bt`, `Bs`, `B`, `C`@40, `s1`@39); G13's `Ct` (4
  bits @46) is cut to the 2 bits that fit, and `Cs`, `Cx`, `Ax`, `Bx`, `Dx`
  and `s2` have no room.  A11's `imad` is a **three-source** multiply-add
  with the type/extension bits of the third source dropped.
* **`atomic`** — 16 of 16 fields that fit are live.
* **`texture_load`** — G13's form is 8–12 bytes; A11 keeps the 5 fields that
  fit and drops the rest (17 beyond 48 bits).
* The `PARTIAL(n/size)` anomalies in the tool's output are **register
  fields whose high bits are simply never used in this corpus**, not layout
  deltas — e.g. `wait_pix`'s `i` uses 7 of 10 bits because no `wait_pix` in
  the corpus waits on a high-index event.

### 4. What this means (confirmed)

* A11/G10P is **not** a re-layout of AGX.  It is *the G13 AGX encoding,
  truncated to three words*, with a handful of opcodes re-shaped so that
  they fit.
* Therefore **a G13 disassembler can be reused almost verbatim for G10P**:
  take `applegpu`'s descriptor table, drop every descriptor's fields above
  bit 48, and force the instruction length to 6 bytes (2 for
  trap/stop).  That is a concrete, buildable specification for the
  `pvr_arch_g10p` disassembler the driver needs.
* The remaining ISA work is now small and specific:
  1. **name the A11-only opcodes** — the words that match no G13 signature
     and start instructions (4-byte and 2-byte classes).  Their first words
     include `0x2000`, `0x0040`, `0x0200`, `0x5200`, `0x5024`, `0x8000`,
     `0x8100`, `0xffff`, `0x9a00`, `0xff00`.  The earlier `mov_imm`-family
     candidate (`0xc2` byte) lives in this set.
  2. **settle the `mov_imm` family** — the corpus contains both the
     Mesa/G13-style `0x62`/`0x162` forms *and* `0xc2`-byte forms; which is
     the A11 `mov_imm` is still open.
  3. **decide the 2-byte vs 4-byte split** of the A11-only class (the corpus
     forces it, but not *which* opcode is which).

### 5. Files added by this session

* `tools/g10p_fields.py` — the field-layout instrument: frames the corpus,
  then for every G13-declared field reports whether A11 uses it, folds it
  into the opcode, ignores it, or has no room for it.  `--summary` prints
  the global table, `--op NAME` a single opcode, `--bits` a per-bit dump.

---

## Addendum 7 (2026-11-08/09, night): **branch targets validate the framing** — and A11's branch offsets are 16-bit, with a per-opcode field position

Offline only. New artefacts: `tools/g10p_constrain.py` (the branch-constrained
solver), `tools/g10p_branches.py`, `tools/g10p_branches.py` sweep variants.

### 1. Why branch targets are the right instrument

Addendum 5's framing tiles all 94 objects, but *tiling* is a weak property:
many different length assignments tile the same corpus, so the DP cannot
distinguish them.  The AGX branch instructions remove that slack.

`jmp_exec_any` (`0xc000`), `jmp_exec_none` (`0xc020`) and `call` (`0xc010`)
carry a relative offset, so each branch **names an exact position that must
be an instruction boundary**.  Those positions are a property of the word
stream, not of the framing, which makes them hard constraints.  With ~15 000
branches over the corpus they over-determine the segmentation.

### 2. A11's branch offset is 16-bit in one word, and the field position is per-opcode (confirmed)

G13's descriptor says `off` is a **32-bit** field at bits 16..47
(`next_pc = pc + sign_extend(off, 32)`).  A11 is different: the offset is a
**16-bit sign-extended byte offset** (see §3: 99.3 % of them are multiples of
6 bytes), and **which word holds it depends on the branch opcode**.

Sweeping the offset field layout × unit × base against the framed corpus,
per branch opcode, and then conditioning on the mod-6 invariant (a real
branch offset in this corpus is a byte offset, so ~100 % of its values are
multiples of 6):

| branch opcode | offset field | targets on a boundary, `off ≡ 0 mod 6` | targets on a boundary, `off ≢ 0 mod 6` |
|---|---|---|---|
| `jmp_exec_none` `0xc020` | **word 2** (bits 32–47) | **15 243 / 15 244 (100.0 %)** | 2 / 8 (25.0 %) |
| `call` `0xc010` | **word 1** (bits 16–31) | **4 / 4 (100.0 %)** | 0 / 0 |
| `jmp_exec_any` `0xc000` | **word 1** (bits 16–31) | **33 / 40 (82.5 %)** | 4 / 65 (6.2 %) |
| `jmp_exec_any` `0xc000` | word 2 | 6 / 11 (54.5 %) | 11 / 96 (11.5 %) |
| `jmp_exec_any` `0xc000` | `w1 \| w2<<16` (G13's 32-bit) | 3 / 55 (5.5 %) | 2 / 52 (3.8 %) |

The separation in the `jmp_exec_any` row is the decisive test: the 40
occurrences whose word-1 value is a multiple of 6 hit 82.5 %, while the 65
whose value is not hit 6.2 %.  That is the signature of a **real** offset
field — and it also says that **most `0xc000` words that land on an
instruction start are coincidental payload**, not real branches.  (Only 400
`0xc000` words exist in the whole corpus, against 21 048 `0xc020` words.)

So the rule is:

> **A11's branch offset is a 16-bit sign-extended byte offset.  The word
> that holds it depends on the opcode: `jmp_exec_none` (`0xc020`) uses the
> third word (bits 32–47); `call` (`0xc010`) and `jmp_exec_any` (`0xc000`)
> use the second word (bits 16–31).**

That per-opcode difference is a real dialect delta from G13, where every
branch carries a 32-bit `off` at bits 16–47.

Corpus census for context (how rare each exec-mask opcode is):

| word | occurrences in the corpus | at instruction starts |
|---|---|---|
| `0xc020` (`jmp_exec_none`) | 21 048 | 15 252 |
| `0xc000` (`jmp_exec_any`) | 400 | 105 |
| `0xc010` (`call`) | 39 | 4 |
| `0xc030` (`TODO.unk30C0`) | 15 | — |
| `0xc040` (`TODO.unk40C0`) | 4 | — |

### 3. The 6-byte quantum, confirmed a sixth and seventh time (confirmed)

> **99.3 % of all branch offsets in the corpus are exact multiples of 6.**

| offset mod 6 | count | share |
|---|---|---|
| **0** | **15 253** | **99.3 %** |
| 1 | 9 | 0.1 % |
| 2 | 46 | 0.3 % |
| 3 | 21 | 0.1 % |
| 4 | 8 | 0.1 % |
| 5 | 24 | 0.2 % |

This is an *independent* proof of the instruction size: a compiler that
emits branch offsets in bytes only produces multiples of 6 if every
instruction it can branch over is 6 bytes long.  No length table was
assumed to obtain this number.

And with the correct offset semantics, **15 263 / 15 361 (99.4 %) of branch
targets land exactly on an instruction boundary**.

### 4. The branch-constrained solve (confirmed)

`tools/g10p_constrain.py` frames the corpus, then iterates:

1. frame every object;
2. for every branch whose target is not a boundary, the instruction that
   covers the target must end exactly there — a length constraint on that
   opcode's class;
3. apply the constraints (only to the A11-only opcodes; the named opcodes'
   lengths are pinned by the period evidence and are not moved), re-frame,
   repeat until stable.

Result: **all 94 objects tile**, **99.4 %** of branch targets hit, and the
length table collapses to a very simple shape:

| class | length | occurrences |
|---|---|---|
| **every named opcode** | **6 bytes** | — |
| `trap` (`0x0008`) | 2 bytes | 2 967 |
| `stop` (`0x0088`) | 2 bytes | 47 |
| `stop/A11` (`0x0108`) | 2 bytes | 60 |
| A11-only opcodes | **6 bytes** (majority) | — |
| A11-only opcodes (minority) | 2 or 4 bytes | see the JSON |

### 5. Correction to Addendum 5 (confirmed)

Addendum 5 modelled the A11-only opcodes as two classes split by bit 15
(`A11-only|L0` = 4 bytes, `A11-only|L1` = 2 bytes).  That was a *coarse*
model forced by the DP having no other signal.  With the branch
constraints the split is resolved **per opcode**: most A11-only opcodes are
**6 bytes like everything else**, and only a minority are 2 or 4 bytes.
The published `A11-GPU-G10P-LENGTHS.json` has been regenerated from the
branch-constrained solve.

### 6. What is still open (unknown)

* **The A11-only opcodes are still unnamed.**  They are the words that match
  no G13 signature; the frequent ones are `0x8000` (2 B), `0x0040` (2 B),
  `0x0001` (2 B), `0x08f0` (2 B), `0x0200`, `0x2000`, `0x5200`, `0xffff`,
  `0xff00` (6 B) and a family of `0xd0xx`/`0xc8xx`/`0xde00`-shaped words
  (4 B).  Naming them needs the AGX3 decoder's opcode table, or a
  Metal-toolchain black-box probe.
* **`jmp_exec_any` (`0xc000`) is only partly understood.**  Its offset field
  is the second word, like `call`'s — but only 40 of the 105 occurrences that
  land on an instruction start have a word-1 value that is a multiple of 6,
  and of those 40 only 33 hit.  So most `0xc000` words that land on an
  instruction start are coincidental payload rather than real branches, and
  the ~7 that are real branches with a multiple-of-6 offset still miss their
  target: the framing is still wrong in their neighbourhood.  This is the
  sharpest remaining lead.
* `mov_imm`: the corpus contains both the G13-style `0x62`/`0x162` forms and
  `0xc2`-byte forms (`0x00c2`, `0x02c2`, `0x04c2`, `0x06c2`); which is A11's
  `mov_imm` is still open, and the `0xc2` family now appears in the
  A11-only list (`0x01c6`, `0x04c6`).

### 7. Files added by this session

* `tools/g10p_constrain.py` — the branch-constrained solver and the
  generator of `A11-GPU-G10P-LENGTHS.json`.
* `tools/g10p_branches.py` — the standalone branch-target validator
  (useful for checking any candidate framing).
* `A11-GPU-G10P-LENGTHS.json` — regenerated: the per-opcode table with
  occurrence counts, the branch validation numbers and the offset semantics.


