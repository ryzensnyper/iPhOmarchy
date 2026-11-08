# A11 (G10P) init-data layout — offline RE, part 1

Session 2026-11-06 (offline, no device). Follows `A11-GPU-FINDINGS.md`.
This resolves the "firmware extraction gotcha" and starts step 1 (the init-data
layout in `pvr_apple_layout.c`), plus step 2 (runtime size) and step 3 (Fender).
Conclusion so far: **the G10P init layout is a different firmware build; the A10
offsets do not carry over field-for-field.** The method is now established.

## 0. Firmware image: the `\0Release\0` wrapper is NOT loaded

Prior notes treated `gfx-t8015-const.bin` (the kext `__TEXT.__const`, 0x5d329 B)
as the image and were puzzled that offsets did not line up. The G10P firmware
kext's `requestFirmwareBinary` (disasm below) returns **`__const + 9`**, size
**0x5d320** — i.e. the 9-byte `\0Release\0` header is a container wrapper, and the
real loadable image starts 9 bytes in, at load base 0.

Proof, from `AGXFirmwareKextG10PRTBuddy` `__TEXT_EXEC,__text`
(`__const` vm `0xfffffff00503299f`):

```
0x...60f0  adrp x8, 0xfffffff005032000
0x...60f4  add  x8, x8, #0x9a8        ; = __const + 9   (image base)
0x...60f8  str  x8, [x1]              ; *out_ptr
0x...60fc  mov  w8, #0xd320
0x...6100  movk w8, #5, lsl #16       ; w8 = 0x5d320
0x...6104  str  x8, [x2]              ; *out_size
```

So: **image = `gfx-t8015-const.bin[9 : 9+0x5d320]`** (saved here as `g10p.img`).
It is an ARM (A32) vector table at offset 0 (`b 0x20`, then `b .` x7), an ARM
reset stub (`cpsid`, `mcr p15` MMU setup) at 0x20, then Thumb-2 code. This
matches the A10 reference ("A32 vector table, then Thumb-2") and explains why
string xrefs could not be found before: every offset was 9 bytes off and a
Thumb linear sweep on the unshifted blob desynced.

Extraction is reproducible from the kernelcache with
`omarchy-iphone/tools/kernelcache-re/kc-extract.py` (or the copy in `tools/`),
keyed on `CFBundleName` (this kext has no `_PrelinkBundlePath`).

## 1. Runtime size — step 2 DONE

`getRuntimeBinSize` returns **0x8f000** — the *same* as A10 — from the same kext:

```
0x...6250  mov  w0, #0xf000
0x...6254  movk w0, #8, lsl #16       ; 0x8f000
```
(the function first checks `[x0+0x8c] == 3`, i.e. core-config type 3.)

So `PVR_APPLE_FW_RUNTIME 0x8f000` stays. Image 0x5d320 + zeroed BSS/heap to
0x8f000; allocate 0x8f000 contiguous, 16 KiB aligned, same as A10.

The same kext also gives the other getters (type 3): image base
`__const+0` (`0x...299f`), `__const+0x9a0`, `__const+9`+size (requestFirmware),
and two getters returning 0 (boot-config offset / resume-flag / pdump patch —
unused, as on A10).

## 2. Fender registers — step 3 partly confirmed

From `agxg10p.asm` (AGXG10P kext):

- Power state `Fender+0x1000`: `str w8,[x0,#0x1000]` / `ldr w8,[x0,#0x1000]`
  at kext `0x2600` (state|0x10, poll bit 4) — matches A10 and the earlier finding.
- Window block dummy-read at `+0x200c / +0x2010 / +0x2014 / +0x2018 / +0x201c /
  +0x2020` (kext `0x42d14..0x42d28`) — exactly the A10 `FENDER_WINDOW` range.
- A10's `FENDER_RUN 0x2048` was not found as a bare immediate in this build; it
  is likely built via base+offset. Keep 0x2048 pending a direct check.
- IOP window offsets (A10: `+0x08..+0x30` 8-byte stride, enable `+0x38`) not yet
  re-confirmed in G10P asm; IOP base is `0x04D20000`.

## 3. Init handler (the 0x81 message) — located

G10P firmware, Thumb-2, handler at **img 0x19318** (A10 reference: fw 0x179e0).
Locate by xref to the string "Unable to grab init data from host" (img 0x30a0d,
built with movw/movt @0x19350). Decoded flow:

```
0x19332  movs r0, #0x20                     ; EP 0x20
0x1933c  bl   0x29444                        ; rtk_recv(ep, &msg, -1, 0)
0x19340  cmp  r0, #0
0x19344  ldreq r4, [sp, #0x24]               ; msg hi word
0x19346  andeq r0, r4, #0xbf0000
0x1934a  cmpeq.w r0, #0x810000               ; type 0x81 / 0xc1
0x1934e  beq  0x1935c
0x19350  print "Unable to grab init data from host"
0x1935c  ldr  r6, [sp, #0x20]                 ; msg lo = PA lo
0x1935e  bfc  r4, #0xc, #0x14                 ; hi = hi & 0xfff   (44-bit PA)
0x19372  bl   0x2b7a4                         ; map(pa, 0x1000, &va, &desc)
0x19382  r8 = 0x8e158                          ; fw global: init-data copy
0x1938c  movs r2, #0x98
0x19390  bl   0x16e4                           ; memcpy(0x8e158, va, 0x98)
0x19394  unmap
0x19410  r0 = [r8+0x8c] ; r1 = [r8+0x90]      ; PA of mem-desc page
0x1941a  r2 = 0x4000
0x19422  bl   0x2b7a4                          ; map(pa2, 0x4000)
0x19432  r0 = [r8+0x94]                        ; descriptor count
0x19436.. loop over 16-byte entries:
         {u32 va, u32 pfn, u32 -, u16 npages, u16 flags}
         flags bit1 -> attr 0x11b else 0x41b   ; same format as A10
0x1953c  r1 = 0x8e154 ; [r1] = [r8+0x20]       ; init+0x20 stored to 0x8e154
0x19548  sl = [r8+0x18]                         ; X (main context)
0x1954c  r4 = [r8+0x1c]                         ; T
0x19552  bl 0x15cf2
0x1955c  r0 = [X + 0xfc]!                       ; P = X[0xfc]  (device context)
```

### 3.1 Init page (fw global 0x8e158; `build_init_page()`)

| off | G10P | A10 | note |
|---|---|---|---|
| +0x18 | X (main context) | X | same |
| +0x1c | T (MMU ctx table) | T | same |
| +0x20 | mapping-ring control ptr | (unused) | **new** |
| +0x8c/+0x90 | mem-desc page PA | same | same |
| +0x94 | mem-desc entry count | same | same |
| copied size | **0x98** | 0xa4 | fields ≥0x98 not copied |

So U (A10 `init+0x98`), V (A10 `init+0x9c`) and A0 (A10 `init+0xa0`) are **gone**
from the init page. The mapping ring that A10 had at `V+0x455c/+0x4560` is now
reached through `init+0x20` directly: `*(0x8e154)` -> control struct
`{+0: entries base, +4: ?, read idx at [base+0x0], write idx at [base+0x10]}`.
The ready/debug flags must be found through X (A10 used U+0x14) — TBD.

### 3.2 X (main context)

The init buffer (fw `0x8e158`) holds X at `+0x18`; the firmware everywhere reads
it as `base = 0x8e158; X = [base+0x18]`.

- `X+0xfc` = **P (device context)**. A10 had P at `X+0x00`; the index moved.
  Confirmed twice: handler 0x1955c and `0x15cf2` 0x15d40.
- `X+0x15c`, `X+0x168`: read at 0x1978e/0x19796 (new; A10 had no such).
- `X+0x00..` (A10's P/Q/Z and the 13 ring descriptors, event/trace rings,
  `X+0x301` power-state struct) — **not yet mapped for G10P.** The 13-ring scan
  and the power-state pointer must be re-found. An automated sweep of the 178
  Thumb sites that load `0x8e158` found no further X fields (the loads are
  usually split across calls), so this needs a recursive pass, not a linear one.

### 3.2b Helpers that use P (cross-checks)

`0x15cf2` (called from the handler after X/T are loaded) does:

```
r0 = 0x8e158; r0 = [r0+0x18]   ; X
r0 = [r0+0xfc]                 ; P
fp = [P+0x640] ; r1 = [P+0x644] ; r6 = fp + 0x110000
```

So **`P+0x640/+0x644` (PA R) carries over from A10**, and `R+0x110000` is still
the scratch page the firmware remaps — the A10 `P+0x640/0x644` meaning is
unchanged. The R-region map path here uses `P+0x688/+0x68c/+0x694` and
`P+0x884..` config copy (section 3.3).

Power-state candidate: the "GPU is not powered on after power kick!" cleanup
(0x1c81a) reads base `*(0x8e420)` and offsets `+0x69a8`; this is the likely
G10P replacement for A10's `X+0x301` power-state struct pointer. Needs
confirmation.

### 3.3 P (device context, `X+0xfc`) field map

The handler copies a large set of P fields into firmware RAM at `0x32000`.
Confirmed copies (host field -> fw 0x32000 offset):

```
P+0x884 -> +0x420   P+0x888 -> +0x424   P+0x88c -> +0x428   P+0x890 -> +0x42c
P+0x894 -> +0x430   P+0x89c -> +0x434   P+0x898 -> +0x438   P+0x8b8 -> +0x43c
P+0x8a0 -> +0x440   P+0x8a4 -> +0x444   P+0x8a8 -> +0x448   P+0x8b0 -> +0x44c
P+0x8b4 -> +0x450   P+0x8bc -> +0x454   P+0x8c0 -> +0x458   P+0x8c4 -> +0x45c
P+0x8c8 -> +0x460   P+0x8cc -> +0x464   P+0x8d0 -> +0x468   P+0x8e4 -> +0x46c
P+0x8f8 -> +0x470   P+0x8fc -> +0x474   P+0x904 -> +0x478   P+0x908 -> +0x47c
P+0x90c -> +0x480   P+0x910 -> +0x484   P+0x938 -> +0x490   P+0x93c -> +0x494
P+0x948 -> +0x498   P+0x960 -> +0x49c   P+0x964 -> +0x4a0   P+0x968 -> +0x4a4
P+0x96c -> +0x4a8   P+0x970 -> +0x4ac   P+0x978 -> +0x4b0
P+0x97c -> +0x744   P+0x980 -> +0x748   P+0x984 -> +0x74c   P+0x988 -> +0x750
P+0x98c -> +0x754   P+0x990 -> +0x784   P+0x8ec -> +0x738   P+0x8f0 -> +0x73c
P+0x900 -> +0x740   P+0x964.. (above)
per-unit loop r0 = 0,4,..,0x3c:
P+0x9ac+r0 -> +0x4b4   P+0x9ec+8r0 -> +0x4f4   P+0xbec+8r0 -> +0x534
P+0xe2c+r0 -> +0x5b4   P+0xe6c+r0 -> +0x5f4   P+0xeac+r0 -> +0x634   P+0xeec+r0 -> +0x674
block copy: memcpy(fw+0x6b4, P+0xf2c, 0x80)
```

Plus earlier: `P+0x688/+0x68c` (PA lo/hi) and `P+0x694` (size) are mapped with
attr `0x21b` (0x19568..0x19584) — same sub-offsets as A10's "R region", so the
A10 `P+0x688/0x68c/0x694` triple *does* carry over.

`P+0x16c0` (A10 engine unit masks) and `P+0x00..0x27` (A10 GPU window values)
were not seen in this handler and must be located separately. `P+0x640/+0x644`
(A10 PA R) **does** carry over (see 3.2b).

### 3.4 The firmware builds its own config at fw 0x32000 from P

The handler is not the only consumer of P. A function at **0x1c290**
(MMU-context setup) does:

```
r0 = 0x8e420 ; r0 = [r0]        ; fw global -> main context (same chain as X)
r1 = [r0 + 0xfc]                ; P
r2 = 0x162c
r3 = [P + 0x162c] ; [fw 0x32000+0x7e0] = r3   ; GPU page-table root (candidate)
r1 = [P + 0x1630] ; [fw 0x32000+0x7e4] = r1   ; root mask (candidate)
```

So `fw 0x32000` is a firmware-internal config struct that the firmware fills
from P fields; it is **not** the A10 `T` structure. `P+0x162c/+0x1630` are new
G10P fields (GPU page-table root + mask).

This is the main architectural shift vs A10: on A10 the host wrote `T+0x7e0`
(page-table roots) directly. On G10P the host fills P, and the firmware derives
its MMU/context config from P. **`pvr_apple_layout.c`'s T handling cannot be
reused as-is.**

Also confirmed along the way (all X-relative, `sl = X` in the handler):
`X+0x15c`, `X+0x168` (section 3.2). The many `[base+0xdc/0xe0/0xec/0xf0/0xf4/
0xf8]` and `[base+0x134..0x140]` sites seen in the linear dump are **not yet
proven** to be X-relative (their base registers were not tracked), so treat the
A10 event/trace/unit-state offsets as *candidates only* until confirmed.

### 3.4b Work-dispatch context (function 0x1c9a2)

The work-classifier/dispatcher at **0x1c9a2** (A10's doorbell/work dispatch was
near fw 0x1c9e2) confirms the context is large:

```
fp = 0x8e420 ; r6 = [fp]        ; r6 = main context (== X)
[r6 + 0x6aa5]                   ; nonzero gate
r3 = [r6 + 0x70] ; [r6 + 0x74]  ; queue/entry arrays
[r6 + r0*4 + 0x12c]             ; per-work-type counter, incremented
```
and classifies a work item by comparing `[0x3717c]` against fw globals
`0x8e158+{0xa0, 0x120, 0x148, 0x168, 0x178}` (values 0..5).

So **X is a large context (fields to at least +0x6aa5)** — far bigger than A10's
X (~0xe70). The A10 X-quad/Q/Z and 13-ring-descriptor block at `X+0x00..0xdc`
is therefore not simply reusable; the ring wiring sits inside this larger
structure and must be mapped from the consumer code (0x1c9a2 and neighbours).

### 3.5 Methods that did not work (so they are not retried)

- Linear Thumb sweep from offset 0 fails: the image starts in ARM mode. Sweep
  from 0x1000 upward with `skipdata` works for grep-style hunting.
- A 0x8e158-site heuristic (178 sites) found no X fields beyond `X+0xfc`,
  because the loads are split across calls. A recursive pass with per-block
  register tracking is required to finish X/T/ring wiring.

## 4. What this means for the driver port

- `pvr_apple_layout.c` must be rewritten for G10P, not offset-patched: the init
  page shrinks (0x98, U/V/A0 gone), P moves to `X+0xfc`, and P's field set is
  different. `pvr_apple_layout.h` `PVR_APPLE_FW_RUNTIME` stays 0x8f000.
- The window/heap model, mem-desc format, I/O table and Fender power state are
  unchanged from A10, so the driver skeleton carries over.
- Remaining to derive (in order): all X fields (ring descriptors, event/trace
  rings, ready flag, power-state pointer), the full P map (windows, IO table,
  unit masks, DVFS), the `init+0x20` ring-control layout, and the `0x32000`
  fw-config structure (for cross-check).

## 4b. Derived field maps (provenance pass, 2026-11-06)

`tools/prov2.py` seeds at every Thumb materialization of `0x8e158`/`0x8e420`
and interprets forward (worklist, follows conditional branches), resolving
`INIT` (init buffer), `X` (`[INIT+0x18]`), `P` (`[X+0xfc]`), `T`
(`[INIT+0x1c]`). Full output: **`A11-GPU-G10P-FIELDS.txt`**. Caveats: register-
indexed and register-added (`add rX, rP, rN`) accesses are not resolved, so a
few fields (e.g. `P+0x162c`, below) are missed; and `loads` that cross function
calls can drop out.

### Host init page (`INIT+0x00..0x97`, the 0x98 bytes the host must fill)

```
+0x00 +0x18 +0x1c +0x20 +0x24 +0x29 +0x2a +0x2b +0x38
+0x48 +0x49 +0x4a +0x4b +0x50 +0x54 +0x58 +0x5c +0x60 +0x64 +0x68 +0x69
+0x6a +0x6b +0x78 +0x7c +0x80 +0x84 +0x8c +0x90 +0x94
```

That is far more host fields than A10's init page. Note the repeated `+1/+2/+3`
byte triples at `0x28/0x48/0x68` and the 4-byte pairs at `0x50/0x54`,
`0x58/0x5c`, `0x60/0x64`, `0x78/0x7c`, `0x80/0x84` — the host page is a
structured table, and `build_init_page()` must be re-authored for it. `+0x8c/
+0x90/+0x94` remain the mem-desc PA/count.

### X (main context) — fixed offsets the firmware touches

```
+0x00 (ptr) +0x04 +0x08 +0x0c +0x10 +0x14 +0x18 +0x1c +0x20 +0x24 +0x28
+0x30 +0x38 +0x40 +0x48 +0x4c +0x50 +0x58 +0x60 +0x64 +0x68 +0x6c +0x70
+0x74 +0x78 +0x7c +0x80 +0x84
+0xb0 +0xb4 +0xb8 +0xbc +0xc0 +0xc4
+0xe0 +0xe4 +0xe8 +0xec +0xf0          <-- busy block: event/trace rings
+0xfc                                  <-- P (device context), 131 sites
+0x100 +0x104
+0x15c +0x168
+0x170..+0x184 +0x190 +0x19a +0x1a0..+0x1b0 +0x1c0..+0x1da   <-- packed block
+0x1d80
```

`X+0xe0/+0xe4/+0xe8/+0xec/+0xf0` is the busiest non-P block and matches A10's
event/SKU/firmware-trace ring pair region (`A10 X+0xdc..+0xf8`), but offset by
~4, so it is *not* a drop-in. The `+0x170..+0x1da` block (packed 4/1-byte
fields) is new.

### P (device context) — 211 offsets, `+0x0000..+0x09a8` in the resolved pass

Confirmed A10-compatible sub-fields: `P+0x640/+0x644` (PA R), `P+0x688/+0x68c/
+0x694`. The per-unit loop fields `P+0x9ac/+0x9ec/+0xbec/+0xe2c/+0xe6c/+0xeac/
+0xeec` and the config block `P+0x884..` are as in the handler (section 3.3).
A10's `P+0x16c0` engine masks were not seen. Full list in the FIELDS file.

## 4c. Semantic labels for the X context (2026-11-06, offline, step 1 continued)

Method: with `tools/prov2.py` now resolving register-added/indexed accesses
(§5), the full site list per offset (`prov2.py g10p.img full`) was disassembled
(`tools/pdis2.py`). "confirmed" means the access pattern itself reveals the
structure (record stride, index width, producer/consumer); "candidate" is
inferred; "differs" means the A10 meaning does not transfer.

### The host rings live at X+0x00..+0x84, NOT at X+0xdc..+0xf8

The A10 X map (event control `X+0xdc` / entries `X+0xe0`; SKU `X+0xec`/`X+0xf0`;
fw trace `X+0xf4`/`X+0xf8`) does **not** transfer. G10P keeps the same record
*formats* at different offsets. The **13 work rings** come first (see below),
then three trace rings:

| G10P | Role | Evidence | A10 | tag |
|---|---|---|---|---|
| `X+0x60` | work ring 12 (control ring): **object ptr** (consumer `+0x00`, producer `+0x20`) | fw `0x219d8`: `[X[0x60]]` index advanced with `uxtb` (mod 256), then dispatch | A10 `X+0xd8` / ring 12 | **confirms** ring 12 |
| `X+0x64` | work ring 12: **entries ptr**, 32-byte entries (opcodes 3..0x26, `tbh` at `0x219fc`) | fw `0x219ee`: `r1=r4<<5; [X[0x64]+r4*32]` | ring 12, 32 B | candidate |
| `X+0x68` | **event-ring control** (consumer `+0x00`, producer `+0x20`) | fw `0x5886`/`0x6b1e`/`0x1b58a`: `sl=X[0x68]`; spin `while (producer+1)&0xff == [sl]`; then `[sl+0x20]=…` | `X+0xdc` | **differs** |
| `X+0x6c` | **event-ring records**, 256 × `0x24` | fw `0x58ba`/`0x6b46`/`0x1b5b8`: copy 36 B to `X[0x6c] + producer*36` | `X+0xe0` | **differs** |
| `X+0x78` | **SKU debug-trace control** (index at `+0x20`, **512**) | fw `0x120a2`: `r6=[X[0x78]+0x20]`; wrap `bfc r0,#9,#0x17` (mod 512) | `X+0xec` | **differs** |
| `X+0x7c` | **SKU trace records**, 512 × `0x24` | fw `0x121d0`/`0x12402`: `str [X[0x7c] + idx*36]` | `X+0xf0` | **differs** |
| `X+0x80` | **firmware-trace control** (consumer `+0x00`, producer `+0x20`, 256) | fw `0xbf1c`: `r8=[X[0x80]]`; `r4=[r8+0x20]`; `r0=[r8]`; wrap `uxtb` | `X+0xf4` | **differs** |
| `X+0x84` | **firmware-trace records**, 256 × `0x3c` | fw `0xbfe4`: `[X[0x84] + idx*60]` (`rsb r1,r4,r4,lsl#4` → ×15, `lsl#2` → ×60) | `X+0xf8` | **differs** |

`X+0x68/+0x6c`, `X+0x78/+0x7c` and `X+0x80/+0x84` reproduce the A10 producer/
consumer + modulo-256 (or 512) + 36/60-byte record scheme exactly; only the X
offsets moved. So the driver's event/SKU/fw-trace setup must use these offsets.

### X+0xe0..+0xf4 are engine/power controls, not the trace rings

The brief's candidate block is repurposed. Evidence: fw `0x4794` (work
dispatcher), fw `0x4eca` and fw `0x1dbac..0x1dc00` ("any engine has work"),
fw `0x902c` (DVFS update), fw `0x1c588`.

| G10P | Role | Evidence | A10 | tag |
|---|---|---|---|---|
| `X+0xe0` | per-engine unit-state ptr: record array, state `+0x0c` (enum 1/2/5), flag `+0x08`, **20-byte** records | fw `0x47d6`, `0x1dbae`; `0x4702`/`0x3be2` | unit-state page `X+0x134` | candidate |
| `X+0xe4` | per-engine unit-state ptr + pending bitmap: state `[rec+0x20]`, bitmap `+0x100`, **36-byte** records indexed by bit number (`rbit/clz`) | fw `0x47e0`/`0x4ef0`, `0x4a04`/`0x6d70`, `0x27d6` | unit-state page `X+0x138` | candidate |
| `X+0xe8` | per-engine/queue unit-state ptr: state `[rec+0xc]==1`, flag `+0x98`, **24-byte** records | fw `0x47ee`/`0x4f16`, `0x4b20` | unit-state page `X+0x13c` | candidate |
| `X+0xec` | **power/engine state ptr** (~0x4190 B): `[X[0xec]+0x38]` = "GPU powered" flag; sub-blocks `+0x1220`, `+0x40b4` | fw `0x1c588..0x1c590`: if `[X[0xec]+0x38]==0` → `0x1c80e` "GPU is not powered on after power kick!" (string img `0x30bf7`, xref `0x1c80e`) | `X+0x301` → struct | **differs** |
| `X+0xf0` | work-dispatch/scheduler control (state machine `[0]`=0/1/2; current-work record `+0x1c..+0x34`) | fw `0x47c6`, `0x1c568`, `0x4e86` | `X+0xf0` = SKU records | **differs** |
| `X+0xf4` | firmware **config/parameter block** (~0x84 B), copied at boot | fw `0x1cc00` → `0xba58`: `memcpy(0x5d4b8, X[0xf4]+4, 0x60)`, `X[0xf4]+0x64 → 0x5d518` | `X+0xf4` = fw trace control | **differs** |

(All six are **loads**: the host/driver must allocate them and store their fw VAs
in X, the same contract as A10.)

(The three `+0xe0/+0xe4/+0xe8` blocks are the A10 "unit-state pages
`X+0x134/+0x138/+0x13c`" analogue, not the event ring.)

### Power-state struct = X+0x69a8 (embedded), tag: confirmed

A10 reached its power state via a pointer at `*(X+0x301)`; G10P instead
**embeds** the struct in X and the failure cleanup recomputes it:

```
0x1c81a  r0 = [[0x8e420]]        ; = X
0x1c826  r1 = 0x69a8
0x1c836  add r0, r1              ; r0 = X + 0x69a8
0x1c838  str r0, [r6]            ; cache at fw global 0x5d6d0
0x1c83a  memset(0x5d6d8, 0, 0x428)
```

`X+0x69a8` is the G10P replacement for `*(X+0x301)`. Its fields are exactly the
provenance cluster `X+0x69ac, +0x69b0, +0x69b4, +0x69b8, +0x69bc, +0x69c0,
+0x69c8, +0x69cc, +0x69d0, +0x69d4/+0x69d8, +0x69ec/+0x69f0, +0x6a04/+0x6a08,
+0x6a1c/+0x6a20/+0x6a24, …, +0x6aa5` (power/DVFS counters, `0x902c` and
`0x90e0` read/write them). The A10 `X+0x301` field itself **differs**.

### Ready flag — not located (tag: differs / open)

A10 polled `U+0x14`, where `U` was the host page at `init+0x98`. G10P's init
page is only `0x98` bytes, so there is no host `U`. The `INIT+0x98/+0x9c/+0xa0`
globals are **firmware-private** (`0x8e1f0..`): `INIT+0x98` is a 64-bit atomic
(`ldrexd`/`strexd`, fw `0x4632`, `0x4e60`), and `INIT+0xa0` is the
`agx_background` task handle (fw `0x1cb7c`, fw `0x1224a` reads it). The nearest
host-resident bytes, `X+0x178`/`X+0x17a`, are GPU-MMU/mapping flags (fw
`0x18486`, `0x3b34`, `0x1c628`), not a ready flag. A host-ready signal must be
in an X field or the remapped shared page (`R+0x110000`, A10's fw `0x30000`);
**not yet identified.**

### X+0x170..+0x17c and X+0x1a8.. (mapping descriptors), tags: candidate

From the mapping/MMU routines fw `0x18460`, `0x18810`, `0x18f9a`, `0x1923e`,
fw `0x21af0`:

| G10P | Role | Evidence |
|---|---|---|
| `X+0x170` | base ptr of an 8-byte-entry array | fw `0x18fa2`, `0x1923e`: `[X[0x170] + i*8]` filled with `{flags 0xc003, 0xfeed…}` |
| `X+0x174` | that array's size/modulus | fw `0x18faa`/`0x18fd4`: `udiv/mls …, X[0x174]` |
| `X+0x178` (byte) | mapping-path flag | fw `0x3b34`, `0x1c628` (`cbz`/`bne`) |
| `X+0x179` (byte) | mapping type, values 0/2/3/4 | fw `0x184bc`..`0x18538` selects the address arithmetic |
| `X+0x17a` (byte) | flag bit 0 | fw `0x473a`/`0x3e92`: `lsls #0x1e; bmi` |
| `X+0x17b` (byte) | flag bit 0 | fw `0x18486`/`0x185ae` |
| `X+0x17c` (word) | address base/offset in the mapping maths | fw `0x18596` |
| `X+0x1a8` | base of a **0x20-byte descriptor array** (`fp += 0x20`, fw `0x18872`): `{+0 flags/type (&0x3f==1), +4, +8 addr lo, +0xc addr hi/type, +0x14, +0x18 count, +0x19 type, +0x1a index}` | fw `0x18824`, `0x18a44` |
| `X+0x1ac` | `+4` word of the same descriptors | fw `0x18828` |
| `X+0x1c0/+0x1c4/+0x1d4/+0x1d8/+0x1d9/+0x1da` | further fields of the descriptor aggregation | fw `0x18a44`/`0x18ba0` |

### 13 work-ring descriptors = X + 0x08*i (object) / X + 0x08*i + 4 (entries)

**Confirmed.** A10's `X+0x0c + 0x10*i` model does not exist in this firmware
build. G10P (and, byte-for-byte, the A10 `g9p.img`) instead scan **13 ring
objects at `X + 0x08*i`, `i = 0..12`** (offsets `X+0x00,0x08,…,0x60`) and
compare `*(u32*)object != *(u32*)(object+0x20)`. The scan is a fully unrolled
leaf:

```
fw 0x6d94: r0 = [[0x8e420]]            ; X
           r1 = [r0]        ; X[0x00] = ring 0 object
           r2 = [r1]        ; consumer
           r1 = [r1, #0x20] ; producer
           cmp r2, r1
           bne 0x6e24       ; return 1 (busy)
           ...                 ; X+0x08 (ring 1) … X+0x58 (ring 11)
0x6e16:    r0 = [r0, #0x60]  ; ring 12 object
0x6e18:    r1 = [r0]         ; consumer
0x6e1a:    r0 = [r0, #0x20]  ; producer
0x6e1c:    subs r0, r1, r0   ; consumer - producer
0x6e1e:    it ne; movne r0, #1
0x6e22:    bx lr
0x6e24:    movs r0, #1
0x6e26:    bx lr
```

Layout of the 13 ring descriptors (each 8 bytes):

| Slot | Value |
|---|---|
| `X + 0x08*i` (i=0..12) | ring `i` **object** ptr: consumer index at `+0x00`, producer index at `+0x20`, a field at `+0x10` |
| `X + 0x08*i + 4` | ring `i` **entries** base ptr |

Evidence for the `+4` entries slot: fw `0x21286..0x21298`
`r1 = [r0 + i*8]; r0 = [r0 + i*8 + 4]; r3 = [r1 + 0x10]; … bl 0x1bdec` (the
caller walks entries at `X+0x08*i+4`). Ring 12 = the control ring: object
`X+0x60`, entries `X+0x64` (32-byte records).

The scan is called from fw `0x6e40` (`0x6e28`, background gate), `0x1d01a`
(RTKit event handler) and `0x230a8` (power/init). The A10 (G9P) image in this
same kernelcache has the byte-identical function at fw `0x6c86` with X base
`[[0x8e2e8]]` (only that one literal differs) — an easy cross-check for any
future A9 extraction, and proof that the stride-8 model is not G10P-specific
(the `X+0x0c + 0x10*i` description in the older A10 lab notes is a different
firmware revision, iPad7,5 21H461). None of
`cmp …, #0xd` at fw `0x55ca/0xb776/0xb85c/0xb94e/0x28e08/0x2eee4/0x2ef8c` is
this scan; those are work-type validity (with the `0x128f` bitmask),
index-remap and a 13-entry lookup-table build.

Thus `X+0x00..0x67` = 13 × {object, entries} and `X+0x68/+0x6c` (event),
`X+0x78/+0x7c` (SKU), `X+0x80/+0x84` (fw trace) are the four non-work rings.

## 4d. Driver-ready init layout (step 1 complete, 2026-11-06)

Method (all offline). `tools/prov2.py` was extended to seed `T` as well (it now
follows the fw global `0x8e424` as well as `0x8e420`); `A11-GPU-G10P-FIELDS.txt`
regenerated with a new **T** section. A parallel pass over the A10 image from
the *same kernelcache* (`tools/prov2_a10.py` on `g9p.img`) was used as a Rosetta
stone, and the driver side was read from the **AGXG10P kext** with `tools/a64.py`
(segments pulled by `tools/extract2.py`). The kext's firmware init-data builder
is at kext `0xfffffff006b703f0`; it is the authoritative list of what the driver
must write (`x19+0x228`=X, `+0x270`=P, `+0x2f8`=T, `+0x308..+0x4c0`=the rings).

### 4d.0 A10 and G10P init pages are the same table, shifted by +8

`prov2_a10.py` shows the A10 same-generation init page (fw `0x8e088`) is
byte-for-byte the G10P page (fw `0x8e158`) with every field at **-8**: A10
`+0x10`=X ↔ G10P `+0x18`; A10 `+0x14`=T ↔ G10P `+0x1c`; A10 `+0x18`=mapping
ring ↔ G10P `+0x20`; A10 `+0x84/+0x88/+0x8c`=mem-desc ↔ G10P
`+0x8c/+0x90/+0x94`. The A10 image additionally has two words at `+0x00/+0x04`
and G10P keeps `+0x00` only. This is why the G10P page is 0x98 B while the old
iPadOS A10 page was 0xa4 B: it is a different firmware branch, not a shrink.

### 4d.1 Ready flag (A: searched, best candidate found)

**There is no host `U` page on G10P.** The init page is only 0x98 B and its last
three words are the mem-desc PA/count; `INIT+0x98/+0x9c/+0xa0` are firmware
globals (64-bit atomic / `agx_background` handle / scratch). The same holds for
the A10 same-generation image. The old iPadOS `U+0x14` and `V+0x455c` have no
token in this init page.

Method used: disassembled the whole `agx_background` tail (fw `0x1cb42..0x1cd3e`)
and every post-init callee (`0x1b442, 0x1c984, 0x1c0ae, 0x1b634, 0x1c018,
0x8048, 0x16ea0, 0x1d55e, 0x1c17a, 0x3a00, 0x1cda6, 0x1d8f8`) and looked for a
store of an immediate 1 to host memory. Results:

| store | site | value | meaning | tag |
|---|---|---|---|---|
| `[INIT+0x1c] + 0xb188` | fw `0x1cc32` (cleared `0x1cba8`) | 1 | "firmware init finished" in the host context `T` | **candidate** |
| `[INIT+0x1c] + 0xb180` | fw `0x211c4`, `0x23028` | 1 | "rings initialised" (work-dispatch path) | candidate |
| `[INIT+0x1c] + 0x9170` | fw `0x1c018` only if zero | 1 | kext *presets* this to 1 too (kext `0x70bbc`) | differs |
| `fw 0x32000 + 0x000` | fw `0x1cc38` | 1 | firmware-private config (A10 analogue "shared [0x30000]=1") | fw-only |

Cross-checks:
- The A10 same-generation firmware writes the same thing at
  `[INIT+0x14] + 0xb038` (g9p `0x1a788`=0, `0x1a828`=1) — the exact structural
  twin. So `+0xb188` (G10P) / `+0xb038` (A10) was kept across the branch.
- The AGXG10P kext init builder sets `T+0xb1bc=1` and `T+0x9170=1`
  (kext `0x70acc`/`0x70bbc`) but it **never** writes or reads `+0xb188` (no
  `0xb18x` immediate anywhere in the kext). So `+0xb188` is firmware-only
  state that a driver can poll.
- **No store of 1 to `X`, to `P`, or to the remapped shared page `R+0x110000`
  happens** in the background or any callee.

**Recommendation:** the G10P driver should poll
**`*(u32 *)(T + 0xb188) == 1`** (T = fw VA passed at `init+0x1c`) after sending
the 0x81 init message, with a fallback timeout — it is the only host-memory
"1" written by the post-init task. The kext-preset gates `T+0x9170` and
`T+0xb1bc` are set *before* the message and so cannot be readiness signals.
Confirmed negative: it is **not** an `X` field and **not** `R+0x110000`.

If hardware disagrees, the remaining lead is the kext's own readiness logic,
which is **not** `waitForFWAlive` in this build (no such method): the AGXFirmware
object keeps its shared region at `obj+0x528` (label "Firmware/Driver Shared"),
and the class has `isFWAwake()`, `AGXFender::didGPUWakeUp()`,
`AGXFender::isPoweredOffWaitingOnHost()`/`isPoweredOffWaitingForKicks()` and the
`gpu-fw-early-wake-timeout-ms` property. `isFWAwake()` here is a logging stub
that returns `0xe00002c7`; the live path must be the Fender methods. Re-check
hardware-side before trusting the poll.

### 4d.2 Ring objects and entries (B)

**13 work rings, 8-byte descriptor each, at `X + 0x08*i`** (confirmed by the
unrolled scan fw `0x6d94` and by the grouping loop fw `0x2115a..0x21320`):

| i | object (consumer/producer) | entries base |
|---|---|---|
| 0 | `X+0x00` | `X+0x04` |
| 1 | `X+0x08` | `X+0x0c` |
| 2 | `X+0x10` | `X+0x14` |
| 3 | `X+0x18` | `X+0x1c` |
| 4 | `X+0x20` | `X+0x24` |
| 5 | `X+0x28` | `X+0x2c` |
| 6 | `X+0x30` | `X+0x34` |
| 7 | `X+0x38` | `X+0x3c` |
| 8 | `X+0x40` | `X+0x44` |
| 9 | `X+0x48` | `X+0x4c` |
| 10 | `X+0x50` | `X+0x54` |
| 11 | `X+0x58` | `X+0x5c` |
| 12 | `X+0x60` (control ring) | `X+0x64` |

(Work rings are 3 engines × 4 priorities; ring 12 is the control ring. The
ring-index pointers in the old A10 driver's `X+0xc+0x10*i` form do **not**
exist here.)

**Ring object** (`object`, 0x24+ bytes; the firmware only touches the first
3 words): `+0x00` consumer index (u32, wraps mod 0x100), `+0x10` synchronised
index (u32; the firmware copies the consumer here after flushing), `+0x20`
producer index (u32, mod 0x100). Confirmed by the scan (`cmp [obj],
[obj+0x20]`) and by the kext builder which does
`obj[0x00] = obj[0x10] = obj[0x20]` and zeroes `obj[0x20]`
(kext `0xfffffff006b704b0..0x70b00`).

**Entries.**
- Ring 12 (control): **32-byte** records; `+0x00` opcode (3..0x26, `tbh` table at
  fw `0x219fc`), parsed from `[X+0x64] + consumer*32` (fw `0x219ee`).
- Work rings 0..11: the record format is the A10 **20-byte** work entry
  `{+0x08 queue fw VA, +0x0c engine (0 geom / 1 frag / 2 compute), +0x10 u16
  command-ring head after the job, +0x12 u8 scheduling slot, +0x13 u8 flag}`.
  G10P was not independently proven field-by-field; note the ring-cache helper
  fw `0x1bdec` is invoked with `0x20` B/entry for **every** ring, so treat the
  entry stride as "20-byte record in a 32-byte-cleared slot" until hardware
  confirms. tag: **candidate** (format inherited from A10).
- Flush helper: fw `0x1bdec(base, stride, count=0x100, start_idx, end_idx)`
  does the D-cache maintenance the firmware needs after the host writes.

**Trace rings** (same object contract; only the offsets moved, §4c):
`X+0x68` control / `X+0x6c` records (event, 256 × 0x24), `X+0x78`/`X+0x7c`
(SKU, 512 × 0x24), `X+0x80`/`X+0x84` (fw trace, 256 × 0x3c). Consumers read
`+0x00`, producers `+0x20`, exactly as the work rings.

**Per-engine/power controls at `X+0xe0..0xf4`** (host load pointers, §4c):
`+0xe0/+0xe4/+0xe8` per-engine unit-state arrays (20/36/24-byte records),
`+0xec` power/engine struct (`[+0x38]`="GPU powered"), `+0xf0` scheduler
control, `+0xf4` firmware config block. The kext builder fills
`X+0xe0..0x104` with fw VAs (kext `0xfffffff006b70d48..0x70eac`), so these are
all driver-set.

### 4d.3 `INIT+0x20` mapping-update ring (C)

`INIT+0x20` is a **pointer** to the ring control block; the 0x81 handler stores
it to fw `0x8e154` (fw `0x1953c`). The drainer is **fw `0x1999c`** (called from
the background work loop `0x1d918`); it is the direct analogue of the A10
`0x181ee`.

```
control block (fw VA at INIT+0x20):
  +0x00  u32  fw VA of the index page
  +0x04  u32  fw VA of the 16-byte entry array
index page:
  +0x00  u8   read  index      } both wrap mod 256 (uxtb)
  +0x10  u8   write index      }
entry (16 B):
  +0x00  u32  PA lo
  +0x04  u32  PA hi
  +0x08  u32  reserved/pad
  +0x0c  u16  npages
  +0x0e  u16  flags   bit0 = present (1 map / 0 unmap),
                      bit1 = cache attr (1 -> 0x11b write-back, 0 -> 0x41b
                             inner non-cacheable)
```

Drainer logic (fw `0x1999c`): `n = (write - read) & 0xff`; for each index
`e = entries + read*16`: if `flags & 1` call `map(PA>>12, npages, attr)`
(fw `0x25b4c`) else `unmap(PA>>12, npages)` (fw `0x25bb4`); then `read++ & 0xff`
and write it back to `index_page[0]`.

This is the **same 16-byte mem-desc format** as the init descriptors, and the
A10 same-generation firmware has the identical block selected by `INIT+0x18`
(g9p `0x8e084`). The old A10 `V+0x455c/+0x4560` container is gone; on G10P the
block hangs directly off `INIT+0x20`.

### 4d.4 `P` device context (D)

`P = X[0xfc]` (131 sites). Host-provided fields the firmware reads:

| Field | Meaning | Value (from the kext) |
|---|---|---|
| `P+0x00` | GPU address window 0 | `0x1400000000` |
| `P+0x08` | GPU address window 1 | `0xffc00000` |
| `P+0x10` | code base 1 | `0x1100000000` |
| `P+0x18` | code base 2 | `0x1100000000` |
| `P+0x20` | GPU address window 4 | `0x18ffff8000` (kext: `mov x9,#0xffff8000; movk x9,#0x18,lsl#32`) |
| `P+0x640` | I/O mapping table, `0x18`-byte entries `{pa lo, pa hi, fw va, size, flags, rw}` | entry 0 = Fender, entry 3 = RGX (candidate; inherited from A10) |
| `P+0x688/+0x68c/+0x694` | entry 3 (RGX): PA lo/hi + size, mapped attr `0x21b` by the handler (`0x19568`) | |
| `P+0x8ac` | (kext writes 0) | |
| `P+0x8b8`, `P+0x8e4` | (kext writes 1) | |
| `P+0x884..` | config block copied by the handler to fw `0x32420..` | |
| `P+0x9ac/+0x9ec/+0xbec/+0xe2c/+0xe6c/+0xeac/+0xeec` | per-unit (0x40 units) fields → fw `0x324b4..0x32710` | |
| `P+0x162c/+0x1630` | GPU page-table root + root mask (→ fw `0x327e0/0x327e4`) | |

The `P+0x00..0x27` windows were read directly from the AGXG10P kext
(kext `0xfffffff006b70be8..0x70c08`: a 32-byte `stp` from `__const` `0x550`
plus `0x1100000000`×2, then `P+0x20 = 0x18ffff8000`). Note they are **not** the
old A10 values. `P+0x16c0` (A10's three "one hardware unit" words) was **not**
observed; the kext uses `P+0x8ac/+0x8b8/+0x8e4` instead, and `P+0x640`'s IO
table is processed region-by-region by fw `0x1b634` (gates on `X+0x30/0x34`,
`X+0x78/0x7c`, `X+0xc0/0xc4`, `X+0xf0/0xf4`, each mapping a `P+0x6xx` entry and
writing the resulting fw VA back into `P` and `fw 0x32000`).

### 4d.5 fw `0x32000`, the firmware-derived MMU/context config (E)

The driver never writes `0x32000`; the firmware builds it from the host:

- fw `0x15cf2` (called by the handler at `0x19552`) maps
  `PA(P+0x640/+0x644) + 0x110000`, size 0x1000 (attr `0x11b`), and
  `memcpy(fw 0x32000, mapped_va, 0xd58)` — i.e. **the host shared page
  `R+0x110000` is copied to fw `0x32000..0x32d58`** (R = `P+0x640` base).
- `0x1b634` then fills `0x32258..0x322e4` from the `P+0x6xx` IO entries and
  stores the shared-page VA at `fw 0x32d44`.
- the handler fills `0x32420..0x327b8` from `P+0x884..0x1658`, and sets
  `fw 0x3210c = 1`.
- the background finally writes `[0x32000]=1`, `[0x3200c]=0x8dbd8`,
  `[0x32000+0x7d8]=0`, `[+0x7e0]=P+0x162c`, `[+0x7e4]=P+0x1630`.

So to make the firmware's page tables correct the driver only has to fill
`P+0x162c/+0x1630` (root + mask); the rest of `0x32000` is derived. This is the
architectural break from A10, where the driver wrote `T+0x7e0` directly.

### 4d.6 Init-page field map (the 0x98 host table `build_init_page()` emits)

| off | G10P | A10 same-gen | meaning | tag |
|---|---|---|---|---|
| +0x00 | word | +0x00/+0x04 | config word (host flag) | candidate |
| +0x18 | X | +0x10 | main context (required) | confirmed |
| +0x1c | T | +0x14 | firmware context (required; ready @ +0xb188) | confirmed |
| +0x20 | map-ring control ptr | +0x18 | mapping-update ring (§4d.3) | confirmed |
| +0x24 | u16 | +0x1c | region size mapped by fw `0x1a38e` | candidate |
| +0x29/2a/2b | bytes | +0x21/22/23 | address-translation shift fields | candidate |
| +0x38 | u32 | +0x30 | translation mask | candidate |
| +0x48/49/4a/4b | bytes | +0x40..43 | shift fields | candidate |
| +0x50/54, +0x58/5c | u32 pairs | +0x48..54 | translation values | candidate |
| +0x60/64 | u32 pair | +0x58/5c | translation mask pair | candidate |
| +0x68/69/6a/6b | bytes | +0x60..63 | shift fields | candidate |
| +0x78/7c | u32 pair | +0x70/74 | translation values | candidate |
| +0x80/84 | u32 pair | +0x78/7c | translation mask pair | candidate |
| +0x8c/+0x90 | mem-desc page PA | +0x84/+0x88 | required, 4 KiB-aligned | confirmed |
| +0x94 | mem-desc count | +0x8c | | confirmed |

(The `+0x24..+0x84` fields feed the firmware's own physical-address translation
for the mem-desc/heap mapping; they are not pointers. They are part of the
"same table, +8" identity of §4d.0, so `prov2_a10.py`/the A10 branch is the
reference for their exact widths.)

## 4e. Implementation-time corrections (2026-11-06, offline)

Recorded while re-authoring `pvr_apple_layout.c/.h` for the D21 kernel tree.
The implementation deviates from §4d only where noted here; everything else
follows §4d/§4c/§4b.

### 4e.1 The ring-object initialisation addresses were wrong

§4d.2 cited "kext `0xfffffff006b704b0..0x70b00`" for the kext zeroing the
ring objects. That range is the function prologue, not the ring code. The
actual initialisation is in the same function at **file 0x23404..0x2360c**
(file offset; vaddr = 0xfffffff006b4d000 + offset):

```
0x23404..0x234ac  obj[+0x20] = 0 for all 16 objects (13 work rings at
                  +0x308..+0x4a8 stride 0x20, then the three trace objects
                  at +0x4b0/+0x4b8/+0x4c0); the +0x4b0 object also gets
                  +0x50/+0x80/+0xb0/+0xe0/+0x110 = 0
0x235bc..0x235ec  for that same object: obj[+0x30]=obj[+0x20],
                  obj[+0x60]=obj[+0x50], +0x90=+0x80, +0xc0=+0xb0, +0xf0=+0xe0
0x234b0..0x2360c  for every object: obj[+0x00] = obj[+0x10] = obj[+0x20]
```

So the host contract is: **all 16 host-created objects get consumer = sync =
producer** (equal values, 0 at boot). The driver applies this to all 16; the
extended six-slot index block (+0x50..+0x110 mirrored at +0x30..+0xf0) is
applied uniformly (which object is special is not proven — tag candidate).

Also: `a64.py` has no offset parameter — its third argument truncates the
file from byte 0, so every "copy of the builder at 0xfffffff006b70d00/
0xfffffff006b70fa0" was the same first 0x700 bytes of the file, and the
earlier "three copies of the builder" reading was an artefact. `agxg10p.asm`
(segment objdump, file offsets) is the reliable addressing.

### 4e.2 `X+0x100` and `X+0x104` are firmware-written word arrays

The firmware loads `[X+0x100]` (14 sites) and `[X+0x104]` (1 site) and uses
them as word arrays indexed by a 5-bit engine/queue id (`str sb, [r3, r4,
lsl #2]` at fw `0x4252`; `ldr r6, [r6, #0x104]` at fw `0x1ca82`). The host
must allocate both as mapped, zeroed arrays (one page each; 32 words would
do, a page is simpler and matches the other load pointers). The driver sets
them to `HEAP_STATUS_0/1` (tag candidate; the arrays' slot format is
unproven).

### 4e.3 T presets confirmed in the builder (was: "the kext presets T+0xb1bc/T+0x9170")

The AGXG10P init-data builder (kext `0xfffffff006b703f0`; file offset
`0x233f0` in the `__TEXT_EXEC` segment) writes, unconditionally:

```
T+0x04  = 7   (or 0 when its config flag bit 0x40000000 is set)
T+0x44  = 0x78  (meaning unconfirmed)
T+0x9170 = 1
T+0xb1bc = 1
T+0x08/+0x10/+0x18/+0x1c/+0x50/+0x54 = 0
```

and zeroes `P+0x8a4..+0x8ab`, `P+0x8ac`. Conditionally (flag clear = write):
`P+0x8c0 = 0xc8`; `P+0x8e4 = 1` only when a provider method (at `[provider
+0x7a0]`) returns non-null — left 0 by the driver (unproven), matching the
kext's null path. `P+0x8b8 = 1` is unconditional. `P+0x8c0`, `P+0x898`,
`P+0x8f8`, `P+0x8fc`, `P+0x95c` and `P+0x15e0` all come from
provider-private words and are left 0.

`P+0x162c` is a single opaque 64-bit handle stored directly
(`str x0, [x8, #0x162c]`), and `P+0x1630` is the same value's high half as
read by the firmware with 32-bit loads (`fw 0x1c290`: `ldr r3,[P+0x162c];
str r3,[fw 0x32000+0x7e0]; ldr r1,[P+0x1630]; str r1,[fw 0x32000+0x7e4]`).
The driver writes `wr64(P+0x162c, gpu_root)` (PA) — candidate, but the only
self-consistent reading of the kext pattern.

### 4e.4 The GPU address windows are kext `stp` constants

```
P+0x00 = 0x1400000000   P+0x08 = 0xffc00000
P+0x10 = 0x1100000000   P+0x18 = 0x1100000000
P+0x20 = 0x18ffff8000
```
(stp q0,q1 from `__const+0x640`, then `str x9, [x8,#0x20]`.) They are not the
A10 values, and there is no `P+0x16c0` on G10P.

### 4e.5 Memory map and descriptors as implemented

The 4 MiB heap is mapped whole by one 16-byte descriptor at `FW_VA_HEAP`
(`pages = 1024`, `flags = 0` — inner non-cacheable; bit1 clear selects attr
`0x41b`, confirmed in the 0x81 handler). `PVR_APPLE_FW_RUNTIME` stays
`0x8f000`; the window/init page/descriptor placements are unchanged from the
A10 design (host-chosen, not firmware-derived). All host-resident structs
are zeroed before firmware execution; the driver memsets the heap and the
window before use.

## 5. Tooling (saved in `tools/` of this directory)

- `extract2.py <kernelcache> <CFBundleName>` — kext slice + sections.
- `pdis2.py <img> <off> <size> [arm|thumb]` — ARM/Thumb disassembly.
- `xref2.py <img> <addr,...>` — Thumb movw/movt xrefs to absolute addresses.
- `prov2.py <img> [full]` — register-provenance pass; prints the INIT/X/P/T
  field map (full listing also in `A11-GPU-G10P-FIELDS.txt`). Resolves
  register-added (`add/add.w Rd,Rn,Rm[,lsl #s]`) and register-indexed
  (`ldr rD,[Rb,Ri]`) addressing — this is what yields `P+0x162c`/`P+0x1630`.
  `full` prints every site address, not just the first five.
  It now also seeds **T** via the fw global `0x8e424`, so a `T` section appears.
- `prov2_a10.py <img> [full]` — the same pass against the A10 same-generation
  image (`g9p.img`); only the three globals differ (`0x8e088`/`0x8e2e8`/
  `0x8e2ec`). Used for the "+8 shift" cross-check (§4d.0).
- `mkfields.py [prov-output]` — group a `prov2.py` run into
  `A11-GPU-G10P-FIELDS.txt` (five sections: host init page, X, P, T, INIT
  fw globals).
- `dump2.py <img> [start]` — full Thumb-2 dump (skipdata-tolerant) for grepping
  loops and immediate patterns.
- `xfield.py`, `rangimm.py` — older one-off helpers (X-field seed scan,
  immediate-range search).
- `a64.py <bin> <base> [size]` — ARM64 disassembly (kext).
- `g10p.img`, `g9p.img` — corrected images (wrapper stripped).

Regenerate the field map:
`uv run --no-project --with capstone python tools/prov2.py g10p.img | python3 tools/mkfields.py > A11-GPU-G10P-FIELDS.txt`

Reproduce the handler:
`uv run --no-project --with capstone python tools/pdis2.py tools/g10p.img 0x19318 0x630 thumb`
Re-run the provenance map:
`uv run --no-project --with capstone python tools/prov2.py tools/g10p.img`

Cross-check the A10 same-generation image (needs `g9p.img`):
`uv run --no-project --with capstone python tools/prov2_a10.py g9p.img`

Kext side: extract with
`uv run --no-project --with capstone python tools/extract2.py <kc> "AGXG10P Graphics Kernel Extension" /tmp/opencode/g10p-kext`
then `a64.py /tmp/opencode/g10p-kext-_TEXT_EXEC_text.bin 0xfffffff006b4d000`.
The firmware init-data builder is kext `0xfffffff006b703f0`; the 13-ring
setup/scan is fw `0x6d94` and fw `0x2115a..0x21320`; the mapping-ring drainer
is fw `0x1999c`.
