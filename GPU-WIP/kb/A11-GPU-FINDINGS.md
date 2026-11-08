# A11 (T8015, D21) GPU — feasibility findings

Offline dig, 2026-11-06. No device access. Target: port the A10 (T8010) GPU
bring-up (OrchardLinux/gpu) to the iPhone 8 Plus.

## 1. The A11 GPU is G10P (same family as the A10's G9P)

From the D21 kernelcache (`kc/20H392__iPhone10,2/kernelcache.release.iPhone10,2_5`,
an uncompressed Mach-O arm64):

- `com.apple.AGXFirmwareKextG10PRTBuddy` (role GFX, provider RTBuddyService)
- `com.apple.AGXG10P` (the Metal/GL driver)
- `com.apple.AGXFirmwareKextRTBuddy` (the base)

The A10 is G9P. The A11 is the next generation. Both are Apple GPUs behind a
"Fender" power/control block, driven by Apple's GFX firmware on a `gfx-kf`
AppleA7IOP V2 coprocessor with an RTKit/AGX-ring protocol — identical to the
A10 architecture the Orchard driver already implements.

## 2. Firmware extraction: works, same container format

Method (like `tools/a10/tools/extract-firmware.sh`):
1. Map the kext's `_PrelinkExecutableLoadAddr` through the kernelcache's
   `__PRELINK_TEXT` segment: `off = seg_off + (load - seg_addr)`.
2. The firmware is the kext's `__TEXT.__const` section.

Result:

| | A10 G9P | A11 G10P |
|---|---|---|
| kext load addr | `0xfffffff0055e4ec0` | `0xfffffff005032040` |
| kext size | `0x5bbc5` | `0x5dc88` |
| `__const` offset / size | `0x89c` / `0x5b329` | `0x95f` / `0x5d329` |
| header (first 16 B) | `00 52 65 6c 65 61 73 65 00 06 00 00 ea fe ff ff` | **identical** |

Both start `\0Release\0<ver>` then ARM32 code (`e1a00000` NOPs). The G10P blob
is `gfx-t8015-const.bin` (0x5d329 bytes) here. Extraction is solved.

## 3. A11 GPU hardware description (live ADT `omarchy-iphone/adt/adt.txt`)

`sgx` node (`compatible = gpu,t8015`) — the RGX core:
- `reg = <0x04000000 0x100000>, <0x04D00000 0x20000>`
- `power-gates = [148, 123]`, `clock-gates = [148, 123]`, `clock-ids = [265]`
- `interrupts = [255,256,257,258,263]`, `interrupt-parent = 28`
- `has-kf = 1`, `gpu-num-perf-states = 2`, 17 empty `perf-states` entries
- `gpu-device-max-power = 5160`, `meta-sw-interrupt`, `pmp-sw-interrupt = 1`
- `AAPL,phandle = 147`

`gfx-kf` node (`compatible = iop-gfx,t8015`, `role = GFX`) — the coprocessor:
- `reg = <0x04D20000 0x20000>, <0x04D00000 0x20000>`
- `interrupts = [260,259,262,261]` (mailbox: send-empty, send-not-empty,
  recv-empty, recv-not-empty), `interrupt-parent = 28`
- `power-gates = [149]`, `clock-gates = [149]`, `clock-ids = [269]`
- `iop-version = 1`; `iop-gfx-nub { compatible = iop-nub,rtbuddy-v2; firmware-name = GFX; }`
- `AAPL,phandle = 148`

Power-domain IDs seen in the ADT power controller (`label`, `id1`):
- `GFX` id 148, `GFX-SGX` id 149, `GFX-KF` id 123, `GFX-BUSY` id 150

## 4. A10 vs A11 mapping (what the driver needs)

| Driver piece (A10) | A10 T8010 | A11 T8015 |
|---|---|---|
| RGX core | `0x20100000` (`rgx`) | `0x04000000` |
| Fender | `0x201d0000` (`fender`) | `0x04D00000` |
| IOP | `0x201d20000` (`iop`) | `0x04D20000` |
| mailbox | `0x201d24000` | within `gfx-kf` (`0x04D00000`) |
| mbox IRQs | 189,190,191,192 | 259,260,261,262 |
| GPU compat | `apple,t8010-gpu` | `apple,t8015-gpu` (ADT: `gpu,t8015`) |
| firmware | `apple/gfx-t8010.bin` | `apple/gfx-t8015.bin` |
| power domain | `ps_gfx` | `ps_gfx` (id 148) + `ps_gfx_kf` (id 149) |

## 5. Assessment

- **Solved:** firmware extraction (identical format), the coprocessor/mailbox
  model, the Fender concept, and the general driver structure all carry over.
- **To derive:** the A11 Fender base + power-state register, the init-data
  layout (firmware-build specific — must come from the G10P kext, not copied
  from T8010), the RGX CORE_ID (read at runtime), and the display pipe (the A10
  uses ADBE; the A11's pipe differs — but the D21 desktop already has an m1n1
  framebuffer, so GPU work is 3D acceleration on top).
- **Biggest unknown:** the G10P shader ISA. If it matches G9P the Mesa
  `g9p_compile` backend can be extended; if not, a new encoder is needed. The
  `metal-tt -arch applegpu_g10p` probe settles this.
- **Verdict:** a real chip bring-up but directly analogous, with the firmware
  already in hand and the hardware map extracted. The A10 driver is a usable
  template; the A9 is Orchard's own listed next chip, so the A11 would be a
  second application of the same method.

## 6. Driver side: the AGXG10P kext confirms the Fender map

Extracted the AGXG10P kext from the same kernelcache (segments scattered by
prelink: `__TEXT` @ file 0x1104a40, `__TEXT_EXEC` @ 0x2715000, `__DATA_CONST`
@ 0x1a8ec00, `__DATA` @ 0x2679900).

Strings name the register ranges the kext reads from the EDT:
`RGXRegs`, `FenderRegs`, `AICTimerRegs`, `AICSWIntRegs`, `UVDRegs`,
`TempSensorRegs (unused)` — and it errors "Unsupported number of reg ranges in
EDT (%u)" / "Fender address unknown".

**The Fender register map is identical to the A10's.** From `__TEXT_EXEC`:

- Power state at **`[fender + 0x1000]`**: `mov w8, #0x10` then `str w8,
  [x0, #0x1000]` and poll `ldr w8, [x0, #0x1000]; tbnz w8, #0x4, poll`
  (power-off, repeats at 0x2600/0xe954/0x20150); and `mov w8, #0x11; str w8,
  [x0, #0x1000]` (request state 1) at 0x205e4. Same `state | 0x10`, same
  bit-4 acknowledgement as T8010.
- Status at `+0x1010` (bit 0), plus `+0x1014`.
- Window registers dummy-read at `+0x200c..+0x2020` (function @ 0x42d04),
  exactly the A10's `FENDER_WINDOW` range.

So the A10 driver's Fender offsets (`PVR_APPLE` `FENDER_POWER_STATE 0x1000`,
`FENDER_WINDOW 0x200c`, …) can be reused verbatim. With the ADT Fender base
`0x04D00000`, the A11 power-state register is **`0x04D01000`** (write `0x11`,
expect readback bit 4 clear).

## Local artifacts (this directory)
- `gfx-t8015-const.bin` — extracted G10P firmware (`__TEXT.__const`)
- `AGXFirmwareKextG10PRTBuddy.bin` / `AGXFirmwareKextG9PRTBuddy.bin` — kext images
- `gfx-t8010-const.bin` — A10 G9P, for comparison
- `AGXG10P__TEXT.bin`, `AGXG10P__TEXT_EXEC.bin`, `AGXG10P__DATA_CONST.bin`,
  `AGXG10P__DATA.bin` — the AGXG10P kext segments
- `agxg10p.asm` — full ARM64 disassembly of the kext code
- ADT source: `omarchy-iphone/adt/adt.txt` (lines ~8745 `sgx`, ~8838 `gfx-kf`)
- A10 reference: `orchard/kernel/patches/drivers/gpu/0001`, `devices/t8010/0011`
- Research: `https://github.com/OrchardLinux/gpu` (`a10/bringup/`)

## 7. The A10 driver template and what maps to the A11

`drivers/gpu/drm/imagination/pvr_apple.c` (A10) — the registers the Linux driver
writes, all confirmed on G10P by the AGXG10P kext where noted:

| Define | Offset | G10P |
|---|---|---|
| `FENDER_POWER_STATE` | `0x1000` | **confirmed** (kext writes `state\|0x10`, polls bit 4) |
| `FENDER_WINDOW` | `0x200c` (6 fields, 4-byte stride) | **confirmed range** `0x200c..0x2020` |
| `FENDER_RUN` | `0x2048` | not seen in kext; likely same |
| `IOP_WINDOW` | `0x0008` (8-byte stride) | IOP base = `0x04D20000` |
| `IOP_WINDOW_ENABLE` | `0x0038` | likely same |

`pvr_apple_layout.c` (A10) — chip constants to replace:
- `FENDER_PA 0x201d00000` → A11 **`0x04D00000`**
- `RGX_PA 0x201000000` → A11 **`0x04000000`**
- `PVR_APPLE_FW_RUNTIME 0x8f000`, `WIN_INIT 0x98000`, `WIN_DESC 0x9c000`,
  `FW_VA_HEAP 0x100000`, `FW_VA_HEAP2 0x140000`, the X/P/T/U/Q/V context
  offsets and the init-page fields → **firmware-build specific**, must be
  re-derived from the G10P firmware (image is `0x5d329` bytes vs G9P's
  `0x5b320`; runtime is likely `0x8f000` or a little more).

The kext names its accelerator `AGXAcceleratorG10`, its Fender class
`AGXFender` (`initConfigRAMOffset`), and reads **multiple reg ranges** from the
EDT (`RGXRegs`, `FenderRegs`, `AICTimerRegs`, `AICSWIntRegs`, `UVDRegs`,
`TempSensorRegs`), erroring on "Unsupported number of reg ranges in EDT".

## 8. Live device (read-only) observations

- Kernel `7.3.0-rc1-orchard-apple-16k`, SSH up (the known-good touch payload).
- `gfx` power domain present (`pm_genpd_summary`: `gfx off-0`, 0 devices),
  i.e. **off and no GPU driver**. DT node
  `soc/power-management@232000000/power-controller@80338`, label `gfx`,
  compatible `apple,t8015-pmgr-pwrstate`.
- No GPU/sgx node in the live DT, no ADT exposed to Linux, `/proc/iomem`
  doesn't claim `0x04000000`/`0x04D00000`. The ADT is only available via
  m1n1 (the `adt.txt` we have).

## Remaining work (needs hardware / deeper RE)
1. **Init-data layout** for G10P (from the AGXG10P kext's `AGXFirmwareKext` init
   structures or the firmware); the A10 layout is firmware-build specific.
2. **IOP window/run registers** on G10P (A10: IOP `+0x08`, enable `+0x38`,
   Fender run `+0x2048`).
3. **G10P shader ISA** — `metal-tt -arch applegpu_g10p` vs the A10 G9P backend.
4. **Hardware confirmation**: write `0x11` to `0x04D01000`, read back bit 4;
   then read RGX `CORE_ID` at `0x04000000`.

## 9. Progress 2026-11-06 (offline): extraction fixed, handler found

Full detail in **`A11-GPU-G10P-LAYOUT.md`** (this directory). Headlines:

- **The `\0Release\0` wrapper is not part of the loaded image.** The firmware
  kext's `requestFirmwareBinary` returns `__const + 9`, size `0x5d320`. The real
  image (`g10p.img` here) is `gfx-t8015-const.bin[9:9+0x5d320]`; it is an A32
  vector table + reset stub + Thumb-2, load base 0. This fixes the "offsets are
  build-specific" confusion from section 7.
- **Step 2 done:** `getRuntimeBinSize` = **0x8f000**, identical to A10, so
  `PVR_APPLE_FW_RUNTIME` stays. Image 0x5d320 < 0x8f000.
- **Step 1 started:** the 0x81 init handler is at **img 0x19318**. The init page
  is copied as **0x98 bytes** to fw global **0x8e158** (A10: 0xa4 to 0x8e550).
  `+0x18`=X, `+0x1c`=T, `+0x8c/+0x90/+0x94`=mem-desc (all same as A10);
  **`+0x20` is new** (mapping-ring control pointer). U/V/A0 (`+0x98..0xa0`) are
  gone. The device context **P is `X[0xfc]`** (A10 had it at `X[0]`), and its
  ~60 host fields that the handler copies to fw `0x32000` are enumerated in the
  layout doc. `P+0x688/+0x68c/+0x694` (the mapped R region) *does* carry over.
- Tooling saved under `tools/` (`extract2.py`, `pdis2.py`, `xref2.py`, `a64.py`)
  so the rest of the layout can be walked the same way.

**The layout difference is architectural, not cosmetic.** The firmware owns a
large context (X, fields to ≥`+0x6aa5`, vs A10's ~0xe70) and a fw-internal
config at `0x32000` that it fills from P (`[0x32000+0x7e0] = [P+0x162c]`), i.e.
G10P derives its MMU/context config from P instead of the host writing `T`
directly. `pvr_apple_layout.c`'s `T` handling is therefore not reusable.

A register-provenance pass (`tools/prov2.py`, output
`A11-GPU-G10P-FIELDS.txt`) now gives concrete field maps: the **host init page
is a 0x98-byte table with ~30 fields** (`+0x00,0x18,0x1c,0x20,0x24,0x29..0x2b,
0x38,0x48..0x4b,0x50,0x54,0x58,0x5c,0x60,0x64,0x68..0x6b,0x78,0x7c,0x80,0x84,
0x8c,0x90,0x94`), `X+0xfc`=P (131 sites), an event/trace-ring block at
`X+0xe0..0xf0`, and 211 P offsets. Still open: semantic labelling of those
fields (which is the ring descriptor, ready flag, event ring, etc.), the
register-added accesses the pass misses (e.g. `P+0x162c`), the `init+0x20`
ring control, and the `0x32000` fw-config cross-check.

Still open for step 1: the X map (ring descriptors, event/trace rings, ready
flag, power-state pointer), the rest of P (GPU windows `+0x00..0x27`, engine
masks, DVFS, `+0x162c/+0x1630`), the `init+0x20` ring control, and a recursive
disassembly pass to finish the register-relative field tracking (linear
heuristics are exhausted; see the layout doc §3.5).

### 9b. Progress part 2 (same session): register/index resolution + X labels

Full detail in **`A11-GPU-G10P-LAYOUT.md` §4c** (this directory).

- **`tools/prov2.py` now resolves register-added and register-indexed
  accesses.** It handles `add/add.w Rd, Rn, Rm[, lsl #s]` (constant or
  `(kind,off)` operands) and folds a known `[Rb, Ri]` index into the effective
  offset. This resolves the previously missed MMU path: **`P+0x162c` /
  `P+0x1630`** (GPU page-table root + mask, fw `0x1c2de`) now appear. The host
  init-page field list (30 fields) and `X+0xfc` = P (131 sites) are unchanged.
  `A11-GPU-G10P-FIELDS.txt` was regenerated (same four sections): X 68 → 105
  fields, P 211 → 237; no field was lost.
- **The trace rings are at `X+0x60..+0x84`, not `X+0xdc..+0xf8`.** G10P keeps
  the A10 record formats but moved the offsets: control ring `X+0x60/+0x64`
  (32-byte entries), **event ring `X+0x68/+0x6c`** (256 × 36 B, consumer
  `+0x00`/producer `+0x20`), **SKU trace `X+0x78/+0x7c`** (512 × 36 B), **fw
  trace `X+0x80/+0x84`** (256 × 60 B). The brief's `X+0xe0..+0xf4` block is
  repurposed as per-engine unit-state pointers (`+0xe0/+0xe4/+0xe8`), the
  power/engine context pointer (`+0xec`, `[+0x38]` = "GPU powered"), a
  scheduler context (`+0xf0`), and a firmware config block (`+0xf4`, copied at
  fw `0xba58`). All six are host-set load pointers.
- **Power-state struct: `X+0x69a8`, embedded** (fw `0x1c81a` computes
  `X + 0x69a8` right after the "GPU is not powered on after power kick!"
  message). A10's `*(X+0x301)` pointer field differs.
- **Host-ready flag still open.** G10P's init page is `0x98` bytes (no host
  `U`); `INIT+0x98` is a fw-private 64-bit atomic and `INIT+0xa0` is the
  `agx_background` task handle. The host-ready signal must be an X field or the
  remapped shared page — not yet located.
- **The 13 work-ring descriptors are `X + 0x08*i` (object ptr) and
  `X + 0x08*i + 4` (entries ptr), i = 0..12** — *not* the A10 `X+0x0c + 0x10*i`
  form. The scan is the unrolled leaf fw `0x6d94` (consumer `+0x00` vs producer
  `+0x20` of each object); the local A10 `g9p.img` has the byte-identical
  function at fw `0x6c86` (only the `X` global differs), which also shows the
  old A10 `X+0x0c+0x10*i` note is a different firmware revision.

**Mesa (userspace) — added to the list 2026-11-06.** The fork
`github.com/OrchardLinux/mesa` is cloned locally at `/home/doug/mesa`
(`main` = `73a49ab`, "pvr/g9p: no SPM scratch buffer"). It already carries the
A10 G9P shader backend (`src/imagination/g9p/g9p_compile.c`, `g9p_isa.h`,
`g9p_cdm.h`, `vulkan/pvr_arch_g9p*.c`, gated by `has_apple_g9p`), and the plan
is documented in `/home/doug/gpu/a10/MESA.md` (Vulkan + Zink in the fork, not
upstream). **No G10P/A11 work exists there yet** — step 5 (G10P shader ISA)
means extending this backend for `applegpu_g10p`, once the ISA is settled.

### 9c. Step 1 finished: the driver-ready init layout (same session)

Full spec in **`A11-GPU-G10P-LAYOUT.md` §4d**; `A11-GPU-G10P-FIELDS.txt` now has
a **T** section (extended `tools/prov2.py` seeds `T` via fw `0x8e424`; the A10
same-gen counterpart is `tools/prov2_a10.py`). Headlines:

- **Init page identity.** The G10P `0x98`-byte host page and the A10
  same-generation `0x90`-byte page are the **same table shifted by +8**
  (`X` at `+0x18` vs `+0x10`, mem-desc at `+0x8c` vs `+0x84`); the old iPadOS
  `0xa4` layout is a different branch. Field map in §4d.6.
- **Ready flag (best candidate).** No host `U` on either same-gen image. The
  only host-memory "1" the post-init `agx_background` writes is
  **`[init+0x1c] + 0xb188 = 1`** (fw `0x1cc32`), the structural twin of A10's
  `[init+0x14] + 0xb038 = 1`; `fw 0x32000 = 1` is firmware-private. The
  AGXG10P kext presets `T+0xb1bc`/`T+0x9170` but never touches `+0xb188`, and
  never polls it. **No store to `X`, `P` or `R+0x110000` occurs.** Suggested
  driver poll: `*(u32*)(T+0xb188) == 1`. It is *not* `U+0x14`.
- **Rings.** 13 × 8-byte descriptors at `X+0x08*i`: `+0`=object fw VA,
  `+4`=entries fw VA. Object: consumer `+0x00`, sync `+0x10`, producer `+0x20`
  (all mod 0x100). Ring 12 = control ring, 32-byte entries, opcodes 3..0x26.
  Work entries inherit A10's 20-byte `{+8 queue, +0xc engine, +0x10 head,
  +0x12 slot, +0x13 flag}` (candidate; the ring cache-helper fw `0x1bdec` is
  called with 0x20 B/entry).
- **`INIT+0x20` mapping ring (solved).** Pointer stored to fw `0x8e154`;
  drainer fw `0x1999c`. Control `{+0 index-page fw VA, +4 entry-array fw VA}`;
  index page read@`+0x0`, write@`+0x10` (mod 256); entries 16-byte
  `{pa lo, pa hi, pad, u16 npages, u16 flags}` (flags bit0 present, bit1 cache
  attr 0x11b/0x41b). Same format as the init mem-desc.
- **P device context.** `P+0x00..0x27` windows read from the kext:
  `0x1400000000, 0xffc00000, 0x1100000000, 0x1100000000, 0x18ffff8000`.
  `P+0x640` is the `0x18`-byte IO table (entry 3=RGX mapped by the handler,
  entry 0=Fender by fw `0x15cf2`); `P+0x162c/+0x1630` = GPU page-table root/mask.
  A10's `P+0x16c0` unit masks are gone (kext uses `P+0x8ac/0x8b8/0x8e4`).
- **fw `0x32000` cross-check.** The driver never writes it: fw `0x15cf2` copies
  the host shared page `R+0x110000` there, then the handler/fw fill it from P.
  The driver only supplies `P+0x162c/+0x1630` for the page tables.
- **Kext path added.** `tools/extract2.py` + `a64.py` pull AGXG10P; its firmware
  init-data builder is kext `0xfffffff006b703f0` (fills `x19+0x228`=X,
  `+0x270`=P, `+0x2f8`=T, `+0x308..+0x4c0`=rings). Use it as the driver-side
  reference for the pvr_apple_layout rewrite.

Next (unchanged plan): rewrite `pvr_apple_layout.c/.h` for G10P from §4d.

### 9d. The G10P layout is implemented (2026-11-06, offline)

`pvr_apple_layout.c/.h` in the D21 kernel tree
(`/home/doug/projects/OrchardLinux/trees/d21-touchgood`, branch
`backup/d21-touch-pre-rebase`) are rewritten for G10P; `pvr_apple.c` is
updated to match. **Not rebuilt into an image, not booted** — compilation is
validated only.

What the code does now:

- **Init page** is 0x98 bytes with ~30 fields; `INIT+0x18`=X, `+0x1c`=T,
  `+0x20`=mapping-ring control pointer, `+0x8c/+0x90`=mem-desc PA (64-bit),
  `+0x94`=descriptor count (1). The `+0x24..+0x84` translation fields are
  zeroed and unproven (candidate tags in comments).
- `PVR_APPLE_FW_RUNTIME` stays `0x8f000`; window stays 1 MiB; `PVR_APPLE_HEAP_SIZE`
  (4 MiB) is mapped whole by **one** 16-byte descriptor at `FW_VA_HEAP`
  (pages = 1024 ≤ 0xffff), flags 0 (inner non-cacheable, as A10).
- **P is at `X+0xfc`**; X holds the 13 ring descriptors at `X+0x00..0x67`,
  the event/SKU/fw-trace rings at `X+0x68/+0x6c`, `X+0x78/+0x7c`, `X+0x80/+0x84`,
  the per-engine/power pointers at `X+0xe0..0xf4`, P at `+0xfc` and two
  firmware-written word arrays at `X+0x100`/`X+0x104` (tagged candidate).
  The embedded power-state struct lives at `X+0x69a8`.
- **T** is a zeroed 0x10000-byte region; the driver presets exactly the
  words the AGXG10P kext presets (`T+0x04=7`, `T+0x44=0x78`, `T+0x9170=1`,
  `T+0xb1bc=1`) and polls **`T+0xb188 == 1`** for readiness (candidate;
  the post-init task writes it, `fw 0x1cc32`).
- **P** carries the kext's windows (`0x1400000000`, `0xffc00000`,
  `0x1100000000`, `0x1100000000`, `0x18ffff8000`), the IO table at `P+0x640`
  (entry 0 = Fender, entry 3 = RGX; inherited/candidate assignment), the
  RGX triple at `P+0x688/+0x68c/+0x694`, `P+0x8b8=1` (kext-preset), and the
  GPU page-table root at `P+0x162c/+0x1630`, read by the firmware as two
  32-bit words. `pvr_apple_switch_vm()` writes the pair (no TLB
  invalidation exists yet on G10P — **runtime VM switches are unproven and
  must not be used**).
- **Mapping-update ring** hangs off `INIT+0x20`; control block / index page
  (read@`+0x0`, write@`+0x10`, mod 256) / 256×16 B entry array are all
  driver-allocated and zeroed. Entry format = the confirmed mem-desc format
  (bit0 present, bit1 cache attr).
- **Ring objects** (13 work + event/SKU/fw-trace) get `consumer=sync=
  producer=0` as the AGXG10P builder does, plus the kext's extended
  six-slot index block at `+0x50..+0x110` mirrored to `+0x30..+0xf0`,
  applied uniformly (candidate: which object is special is not proven).
- **Job submission is unchanged in shape but unproven on G10P**: work
  entries are the inherited A10 20-byte record in 32-byte slots
  (candidate), and all command payloads (compute/TA/3D microsequences,
  CDM arguments) are A10/G9P-inherited constants, tagged inherited in the
  code. They are not verified against the G10P instruction stream.
- `apple_fw_debug` and the SKU-ring dump were removed: the G10P
  debug-flags global is not located (tagged open).

**Validation (all offline):**

- Every X/P/T/INIT offset the code writes is present in
  `A11-GPU-G10P-FIELDS.txt` (scripted cross-check; the only exceptions are
  the kext-written P windows `P+0x00..0x27`, which have no firmware read
  site, and the `X+0x6aa6` static-assert bound).
- The heap map (48 regions) is checked by ~40 `static_assert()`s at
  compile time (ordering, sizes, no overlap, ≤ 4 MiB, u16 page count,
  power-state struct fits X).
- `make O=/out ARCH=arm64 LLVM=-19 M=drivers/gpu/drm/imagination` in the
  Orchard `orchard-hardware-kernel-toolchain` container: `pvr_apple.o` and
  `pvr_apple_layout.o` compile with no warnings; `llvm-nm` shows every
  `pvr_apple_layout_*` undefined symbol in `pvr_apple.o` resolves against
  the 20 exports of `pvr_apple_layout.o`. modpost fails only because
  `Module.symvers` is absent (no full vmlinux build); the objects are
  clean.

**Implementation-time corrections to the RE notes** (see layout doc §4e):

- The init-data builder citations (`kext 0xfffffff006b703f0…`) were right,
  but the *ring-object initialisation* happens in the same function at
  file 0x23404..0x2360c — `obj[+0x20]=0` for all 16 objects, then
  `obj[0]=obj[0x10]=obj[0x20]`; the previous note pointed at the wrong
  address range.
- `X+0x100`/`X+0x104` are **firmware-written word arrays** indexed by
  5-bit engine/queue ids (`str sb, [r3, r4, lsl #2]`, `ldr r6, [r6,#0x104]`);
  the host must allocate mapped, zeroed arrays — new heap regions
  `HEAP_STATUS_0/1` (one page each each), filled at `X+0x100/+0x104`.
- `a64.py` has no offset parameter (its 3rd arg truncates the file); the
  earlier "three copies of the builder" observation was an artefact.
  `agxg10p.asm` (segment objdump) offsets are the reliable addressing.
- T presets confirmed in the builder: `T+0x04=7` (0 if its feature flag
  `0x40000000` is set), `T+0x44=0x78` (unconfirmed meaning),
  `T+0x9170=1`, `T+0xb1bc=1`; `P+0x8e4=1` only when a provider method
  returns non-null (left 0 — unproven), `P+0x8b8=1` unconditional,
  `P+0x8c0=0xc8` only when a provider flag bit is clear (left 0),
  `P+0x162c` = an opaque 64-bit handle (driver: `gpu_root` PA;
  `P+0x1630` = its high word, read by the firmware with 32-bit loads).

**Still not done:** the GPU has not been booted; the command payloads are
unverified; the ready flag is hardware-unproven; the MMU invalidation
protocol is unknown; the `t8015-gpu` DT node does not exist; the
`apple,t8015-gpu` match is deliberately not added.

### 9e. AppleA7IOP (G10P) power/window registers confirmed (2026-11-06, offline)

Task 1 from the handoff, done against the **AppleA7IOP** kext from the same
kernelcache (`com.apple.AppleA7IOP`, load `0xfffffff004e20fc0`,
`__TEXT_EXEC` disassembly kept as `AppleA7IOP.asm` in this directory; the
`AGXG10P`/`AGXFirmwareKextRTBuddy` kexts contain no window code — the
Fender/IOP map lives in AppleA7IOP, as it did in kext17's `AppleA7IOPV2*`
for iOS 10/17). Three byte-identical copies of the same functions exist in
the kext's `__TEXT_EXEC` (V4GFX path around `0x7565fc..0x756cb8`, a second
copy around `0x75aeb0..0x75b010`, a third around `0x7594c4..0x759558`), so
each claim below is triple-sourced.

**Confirmed on G10P (iOS 16.7.16, 20H392):**

| Item | G10P | Notes |
|---|---|---|
| Fender `+0x1000` | `state\|0x10` write, poll bit 4 | unchanged from A10 (`0x20150`, `0x205e8`, `0x7567c4`-like power paths; also dummy-read at AGXG10P `0x42d04`) |
| Fender `+0x1010` | status bits written via csel (bit 0 if arg＝＝0, bit 1 if arg＝＝1, all-clear if arg＝＝2) + dummy read | same role as A10 |
| Fender `+0x1014` | masked write (`&= 7`) + dummy read | new-ish; A10 had no known use |
| Fender window `+0x200c..+0x2020` (4-byte stride) | **written**: `+0x200c`/`+0x2010` = lo/hi32 of the physical base (external 64-bit helper `0x75dd20`, identity unresolved), `+0x2014`/`+0x2018` = lo/hi32 of the IOP address (0 for GFX), `+0x201c` = `len & ~0xfff` (via vfunc `+0xb0` on the descriptor), `+0x2020` = 0 | the A10 layout verbatim; the AGXG10P kext only dummy-reads this range (function `0x42d04`) |
| IOP window `+0x08..+0x30` (8-byte stride), enable `+0x38 = 1` | same six words at 8-byte stride, enable written last | `0x756788..0x7567ac`, `0x759520..0x759548`, `0x75afac..0x75afc4`-like paths |
| Fender `+0x2048` (`FENDER_RUN`) | **exists and is used**: `w9 = (w9 & ~1) \| (arg & 1)` — read-modify-write preserving the other bits; GFX-specific override (like A10's `AppleA7IOPV2GFX` `_run`), no chain to a V2 `+0x44` path | `0x756cfc` and `0x75b004`. **The A10 driver's `FENDER_RUN` usage is valid on G10P as-is.** |
| IOP copy gating | the IOP-window writes run only if a descriptor check passes (`0x754558`: compares vfunc `+0x98` vs vfunc `+0xb0` on the memory descriptor, `cset eq`) — presumably single-segment/contiguity; on failure the code takes an error path (`0x7567c0`) | Fender copy is unconditional |
| Mailbox | unchanged (`+0x4000`/`+0x4004`/`+0x4008`/`+0x4020`/`+0x4038`; "IDLE_STATUS" dump at `0x40f20`; GFX config restore loop writes 0x100 words at `+0x8130+`) | not re-verified field-by-field |

**Field-order note for `pvr_apple_set_window()`:** the driver's six words
`{win lo, win hi, 0, 0, PVR_APPLE_WINDOW_SIZE, 0}` map exactly onto
`{+0x200c, +0x2010, +0x2014, +0x2018, +0x201c, +0x2020}` (and the IOP twins),
i.e. `iopAddr = 0`, `len = PVR_APPLE_WINDOW_SIZE` — the same
`_mapFirmware(iopAddr = 0, md)` call the A10 path makes. No driver change
needed for G10P; `PVR_APPLE_WINDOW_SIZE` (1 MiB) is still an inherited
choice, not something G10P-verified.

**Not resolved here (still open):** the identity of the external 64-bit
helper at `0x75dd20` (likely the memory-descriptor physical-address
getter; cross-kext call, outside `__TEXT_EXEC`); what the `+0x1010`/`+0x1014`
bits mean; whether the IOP copy is required at all for GFX (iOS writes both,
A10 needed both); the `+0x44` V2 run path on G10P (untested, unused by GFX).

**Driver impact:** `pvr_apple.c` comment updated (`FENDER_RUN`/IOP
comments); no functional change. Hardware validation (write `0x11` to
`0x04D01000`, poll bit 4; then RGX CORE_ID) is still gated on the user's
explicit go — one boot per go.

### 9f. Mailbox & init registers on G10P (2026-11-06, offline)

Task: verify the G10P GFX mailbox/init sequence against the A10 one
(FENDER.md §2, §5) using the AppleA7IOP kext. All steps present, same
semantics; the kext's own register-dump format string matches A10 verbatim
("IDLE_STATUS / MAILBOX_SET / MAILBOX_CLR / INBOX_CTRL / OUTBOX_CTRL",
function `0x756624`, reads `+0x4040, +0x4000, +0x4004, +0x4008, +0x4020` —
identical order to the A10 dump). Source strings (assert messages) name the
functions: `AppleA7IOPV2::_getInboxEmpty()` (ln 87),
`AppleA7IOPV2::_getOutboxEmpty()` (ln 87), `_isSingleRange(md)` (ln 76),
`AppleA7IOPV2GFX::initialize()` (ln 24, "_agxRegisterMap && _agxMappedRegs").
Triple-copied like the window code.

| Step (A10, FENDER.md §2/§4.4) | G10P (function → effect) | site |
|---|---|---|
| mask setup: `+0x4000 = 0x1111`, `+0xc00 = 0x1111` | `0x756530`: `0x1111` → `IOP+0x4000` and `+0xc00` (MAILBOX_SET pair, mask all four IRQs: bits 0/4/8/12) | `0x756530` |
| unmask: `+0x4004 = 1`, `+0xc04 = 1` | `0x756548(arg)`: if `arg != 0`, writes `1` → `IOP+0x4004` and `+0xc04` (MAILBOX_CLR pair); if `arg == 0`, writes `1` → SET pair | `0x756548` |
| `+0x4004 = 0x1000`, `+0xc04 = 0x1000` | `0x7565a4`/`0x7565a8`: after logging `_getOutboxEmpty() @ ...cpp:87`, writes `0x1000` → same pair selected by `w1` | `0x7565a4` |
| `+0x4020 \|= 1` (OUTBOX enable) | `0x7565d8`: `OUTBOX_CTRL \|= (arg & 1)` | `0x7565d8` |
| inbox/outbox empty poll: bit 17 of 0x4008/0x4020 | `0x7564dc` = `_getInboxEmpty` (INBOX_CTRL `0x4008`, asserts `!(reg & 0xc0000)`, returns bit 17 via `ubfx #0x11,#1`); `0x75650c` = same without assert, returns bit 16 (`ubfx #0x10,#1`); `0x756578` = `_getOutboxEmpty` (OUTBOX_CTRL `0x4020`, same assert/bit 17) — on error bits set (0xc0000) it logs and falls into `0x7565a4` (write `0x1000` → MAILBOX_CLR pair) | `0x7564dc`, `0x75650c`, `0x756578` |
| `+0xc004 = 0x11`, `+0xc024 = 1` | identical | `0x756830` |
| timebase sync: `+0x80c &= ~2`, timebase lo/hi, `+0x80c \|= 2` | identical, via vfunc `0x640` regread + `0x75ddf8` (CNTVCT read): copy 1 → `+0x810`/`+0x818`, copy 2 → `+0xc030`/`+0xc038` (the A10 pair) | `0x755dc4`, `0x756850` |
| GFX run: `W+0x2048 \|= 1` (override, not the V2 `+0x44` path) | identical: `W+0x2048` read-modify-write bit 0 | `0x756cfc`, `0x75b004` |
| `GFX config restore`: read 256 regs from `+0x8130` into stack buffer, compare, then zero 64 B scratch and set `[this+0x195] = 1` | present in the ASC/GFX init path (string `"_agxRegisterMap && _agxMappedRegs"`, `AppleA7IOPV2GFX.cpp:24`); purpose unverified (restore from iBoot or config verify — unknown) | `0x75944c`..`0x7594c4` |
| New: GFX-specific bit | `0x7567c8`: reg `0x4044` `& 0xffffffef`, then `\|= (arg ? 0x10 : 0)` — bit 4; no known A10 counterpart | `0x7567c8` |

**Mapping to the Linux side.** The in-tree `apple-mailbox` driver already
implements the A7IOP mailbox variant
(`apple,t8010-a7iop-mailbox`, `apple_mbox_a7iop_hw`): mask SET `+0x00` /
CLEAR `+0x04` (relative to a mailbox base at **IOP+0x4000**),
A2I_CONTROL `+0x08` (enable BIT(0)), A2I_SEND `+0x10`,
I2A_CONTROL `+0x20`, I2A_RECV `+0x38`; interrupts at bits 0/4/8/12
(mask all = `0x1111`) — i.e. exactly this G10P register block. The G10P
GFX mailbox is the same hardware described in the ADT (gfx-kf interrupts
259–262, `iop-version = 1`). **No new mailbox variant is needed**; a DT
node can reuse `apple,t8010-a7iop-mailbox` (or add
`apple,t8015-a7iop-mailbox` purely for documentation). The GFX-specific
`+0xc00` mirror pair is initialized by iOS but is not used by Linux
(the Linux driver talks to IOP+0x4000-based registers only); do not touch
it. The boot-order bits (M1..M3, OUTBOX enable) are already handled by
the Linux mailbox/RTKit path on A10 — the A10 boot worked with them, and
nothing in the G10P dump suggests a divergence. FENDER_RUN (+0x2048) and
the window registers are the only pieces the GPU driver itself programmed
on A10, and both are confirmed present on G10P.

**Not resolved:** what `+0x4044` bit 4 gates; whether the `+0xc00` mirror
pair matters at all on G10P; why there are two timebase destination pairs
(`+0x810/+0x818` and `+0xc030/+0xc038`); the `0x8130`-restore semantics
(config verify vs iBoot handoff); `+0x4040` (IDLE_STATUS) bit meanings.

Driver change: none. Mailbox programming stays with `apple-mailbox`
(+ `apple-rtkit` for the RTKit protocol); `pvr_apple.c` only programs the
Fender window/run/power state and the RTKit shmem.

### 9g. ISA probe breakthrough: `ds.g10p` is an applegpu_g10p Mach-O archive (2026-11-06, offline)

Task 2 update. The OS DMG contains `AGXMetalA11.bundle/ds.g10p` — an
"LPPM"-container **archive of 94 Apple GPU Mach-O objects** (MH_OBJECT,
`cputype 0x01000013`, `cpusubtype 0x22`, sections `__TEXT,__text` +
`__GPU_*/__compute`). They are Apple's driver-internal G10P program suite
(`agc.main[.constant_program[.cfg]]`, `agc.eot`, `agc.background`,
`agc.clearvertex`, `agc.passthrough_vertex`,
`agc.tile_dispatch_vertex_point`) — i.e. **~983 KiB of applegpu_g10p
machine code from Apple's own compiler, obtained offline**, extracted to
`ds-g10p/` (see `MANIFEST.txt`) and documented in `A11-GPU-G10P-ISA.md`.

Mechanically verified over all 94: 16-bit LE words; the **bit-8
continuation claim made here on 2026-11-06 is wrong and was corrected on
2026-11-07** — under it the last word of every kernel (`0x0108`, bit 8 set)
cannot terminate an instruction, so all 94 streams end in a forced cut. The
current candidate flag bit is 0; `0x8000` is *not* an end marker as stated
(it is unaligned and 4,986×). G9P's opcode space (prologue `0x1181`,
exec-mask `0x21c8/0x46d1/0x46d2`, ALU `0x3199`, load/store `0x2312`,
move-imm `0x0198` + `0x0154 0x0038` companion) is absent → **G10P is a
re-encoded, non-compatible ISA in the same 16-bit-word family**, not a Mesa
`g9p` extension candidate. Encoding tables must be derived from these
samples (+ ideally `metal-tt` on macOS for validation). Mesa remains
untouched; `A11-GPU-G10P-ISA.md` has the full record, the corrected
statistics, the tagged open items and the extraction.

Not verified: the full ISA decode (next step), the `ds.g10p` content-id
hash algorithm (not SHA2-family), whether these kernels are executed
in-place by the driver (they are not firmware images — no relation to the
`gfx-t8015.bin` image or its 0x81 RTKit path).

### 9h. The AGX2/AGX3 backend, disassembled (2026-11-07, offline)

The actual Apple compiler that produced `ds.g10p` was located inside the
iOS dyld shared cache and read: the **AGX2/AGX3 LLVM backend lives in
subcache `.19`** of `/tmp/opencode/dsc/20H392__iPhone10,2_5/`
(`dyld_shared_cache_arm64.19`, base `0x1bc6a8000`); its AGX3 string table
(1 654 strings: `AGX3 Assembly Printer`, all `fixup_agx3_*` names, the
`G10UnitF16/F32/MAD/MOV/SMTP/Issue/IssueControl` unit names, `.il4 .il8
.il16 .il32 .il64`) is at file `0x026d5000`-`0x026e1400` and its code at
file `0x00511000`-`0x0057f000`.

**Load-bearing result: the AGX3 instruction encoding is byte-packed with
dense bit fields and has no per-word continuation flag.**  The fixup writers
patch instruction bytes one bit at a time (`ldrb`/`orr`/`strb`); the branch
fixup at vaddr `0x1bcc03014` puts a 48-bit value at **raw bit offsets
22..69** of the instruction (byte 2 bit 6 .. byte 8 bit 5), which is only
consistent if all 16 bits of every word are payload.  G9P's "15 payload bits
per word" layout would put that field one bit higher.

Consequences for the G10P framing work:

- "which bit means another word follows" is probably the **wrong question**
  for G10P — length is carried by the opcode.
- `fixup_agx3_ldimm_imm_0_l0m31o50` (32-bit immediate at raw bits 50..81)
  and `fixup_agx3_b_offset_0_l0m47o22` (48-bit branch offset at raw bits
  22..69) prove AGX3 encodes **6- and 5-word** instructions.  That breaks
  the "`.il64` => max 4 words" argument that made **bit 0** the preferred
  continuation flag, so bit 0 is now only the best *fitting* candidate, not
  a supported one.
- An opcode decode table exists (words `0x103`..`0x1622` valid, table at
  file `0x1c74b78`), but it sits in a code region shared with AGX2, so it
  is not yet proven to be the G10P one.
- The corpus itself is 16-bit aligned (all 94 `__text` sections have even
  length), so a repacking step exists between the byte-packed AGX3 encoding
  and `__text`; that step is where a flag *could* live and has not been
  found yet.
- **A graded same-source differential test** (`tools/g10p-struct/g10p-samesrc.py`)
  measures how well a framing reproduces the structure of the corpus'
  32x-specialised programs: the best candidate (bit 13, or bit 8 with
  `0x0108` special) reaches only 0.79 mean length-sequence agreement and bit
  0 only 0.745, while the worst bit reaches 0.45.  No single-bit framing
  comes close to 1.0, which independently supports "G10P instruction length
  is not set by a flag bit".
- An AGX3 per-opcode descriptor table was found (32 768 entries at vaddr
  `0x1be327a44`); its high bits are flags, **not** an instruction size (no
  `lsr #11` of the entry exists in the encoder - an earlier "high bits =
  byte length" reading was checked and discarded).  This table is where the
  G10P opcode -> length map must live; it is not decoded yet.

Also completed this session: a **framing-independent** structural analysis
of the whole corpus (`tools/g10p-struct/` in the scratch area; report +
SUMMARY).  It reproduces every figure quoted in `A11-GPU-G10P-ISA.md`'s
Framing-correction section and adds: all 94 sections are even-sized;
`0x0108` is a *function* terminator (219× = 94 section ends + 125 mid-section,
113 of those followed by `0x0008`/`0x0000` filler, **80 of the 125** put the
next function on a 64-byte boundary); `0x8000` is flat mod 64 (4 986×) and is
not an end marker; `0x0008` is the filler word (runs of up to 26); the
dominant motifs are `02de 0000 0040` and `0026 0000 4040`; and the 32
same-source instances of each of the two `.constant_program` programs are
the differential material.

Full record, tools and caveats: `A11-GPU-G10P-ISA.md` §"AGX3 backend
reverse-engineering" and `tools/agx3-re/`.

## Device survey (2026-11-08, read-only, live iPhone 8 Plus / A11)

Access: USB CDC-NCM (`172.16.42.1`) + SSH (`root`, key `~/.ssh/id_hoolock`);
a CDC-ACM console is also exposed at `/dev/ttyACM0`.  **No writes were made
to the device** (reads only: sysfs, procfs, device-tree, dmesg, and copy-out
of `/boot`/`/lib/firmware` files to the host).

| item | finding |
|---|---|
| device | `Apple iPhone 8 Plus (Global)`, DT compatible `apple,d21`,`apple,t8015`, model `apple,d21apple,t8015` ✓ |
| kernel | `7.3.0-rc1-orchard-apple-16k` (`7.3.0-rc1-g2bde906a7ae3`), Arch Linux ARM, built 2026-10-22 by `orchard@builder`; **fully built-in — `/lib/modules/<ver>` contains no modules** |
| display (working) | simplefb/simpledrm: `card0` + `fb0` (`simpledrmdrmfb`), 1080×1920, format `x2r10g10b10`, stride 4352, physical `0x8ba75c000` (8 355 840 B); source = the m1n1/dfrmt framebuffer (`chosen/framebuffer@8ba75c000`, `reserved-memory/flash@8ba758000`) ✓ |
| native display | the kernel **does** contain `adpdrm` + `adpdrm_mipi` + the panel compatible **`apple,summit`** + `DRM_MIPI_DSI` ✓, but the DTB has **no DSI controller node and no panel node** → `disp0` cannot appear without DT work |
| GPU | **no `gpu@` node in the DTB**, and the kernel image contains **no panthor / powervr / AGX driver strings** → there is no GPU driver at all in this build (`/proc/config.gz` still says `CONFIG_DRM_POWERVR_APPLE=m`, but no code or `.ko` ships) |
| power | PMGR (`power-management@232000000`) exposes the controller **`gfx` @ 0x80338** and the display domains `disp0_fe/be/gp/gp0/gp1/ppp/hilo` ✓ — as *power domains only*, no devices |
| iommu | `apple,t8015-dart` (`iommu@259c50000`) ✓ present |
| mailbox | only three ASC mailboxes (`232308000`, `236808000`, `257008000`); **no GPU mailbox**, and the KB's GPU IRQs 259-262 are not registered |
| PMP | `pmp-t8015-v1` binds, but its firmware **`apple/pmp-t8015.bin` is missing** → dmesg `Direct firmware load … failed … unable to load firmware` → PMGR state changes (incl. powering GFX) are not dependable.  **The blob has now been extracted offline from the iOS kernelcache** (see "T8015 firmware inventory" below) — it only needs to be installed on the device |
| userspace | Mesa 26.2.5 with **`asahi_dri.so`** ✓ and `/usr/include/drm/asahi_drm.h` → the userspace side is ready the moment a panthor device exists |
| firmware files | `/lib/firmware/apple/`: `dfrmtfw-d21-c1f5e-{3,4}.bin` (display firmware, magic `Z2FW`), `t8015-smartio.bin` (616 336 B, ARM64 vector table), `z2-*.bin` |
| our offline artifact | the device's `t8015-smartio.bin` is **byte-identical** to `/home/doug/a11-fw/out/t8015-smartio.bin` (md5 `b3a23e8a…`), which was extracted from the *same* iOS 16.7 kernelcache → the device runs exactly the iOS build we already have ✓.  It is a **different image** from the AGX-kext-embedded `gfx-t8015` blob we analysed (`g10p.img`): different vector-table branch target, only 38 of 93 4 KB chunks shared |

Pulled to the host (read-only copy-out): `/tmp/opencode/device/` —
`t8015-d21.dtb` (+ `.dts`; both boot entries are byte-identical,
md5 `fdd59e55ce8797e20861654f710f90ae`), `linux.gz`/`linux.bin`
(decompressed kernel), `t8015-smartio.bin`, `dfrmtfw-d21-c1f5e-4.bin`.

### What this means for the bring-up (confirmed)

1. **The 3D probe is blocked on kernel/DT work, not on ISA work.**  Needed:
   a panthor build for this kernel, a `gpu@` node (`apple,t8015-gpu`) with the
   ADT map we already have (RGX `0x04000000`, Fender `0x04D00000`, IOP
   `0x04D20000`, mailbox + IRQs 259-262), the `apple/pmp-t8015.bin` PMP
   firmware, and the GPU firmware under the name the driver expects.
2. **Native `disp0`** additionally needs a DSI controller node and an
   `apple,summit` panel node carrying the A11 panel timings (from the ADT);
   the display *power* domains are already in the DTB, and the kernel side
   (`adpdrm`, `adpdrm_mipi`, `apple,summit`, `DRM_MIPI_DSI`) is already
   built in.
3. Until then the **m1n1/simplefb display stays as the working path** — no
   changes required, which matches the "read-only, no edits" constraint.

No further read-only device work is productive; the next step needs write
access to the kernel/DT and therefore explicit approval.

## T8015 firmware inventory (offline, 2026-11-08)

The iOS 16.7 A11 firmware carries **three distinct** T8015-related firmware
images.  They are easy to confuse; they are not versions of each other.

| image | where | size | what it is | on device? |
|---|---|---|---|---|
| `com.apple.driver.AppleT8015SmartIO` | kernelcache payload @ `0x2ccf000` | 616 336 B | the GPU's own runtime ("smart IO") firmware — ARM64 image, first vector `0xea00040e` | **yes** — `/lib/firmware/apple/t8015-smartio.bin`, byte-identical to `/home/doug/a11-fw/out/t8015-smartio.bin` (md5 `b3a23e8af8c7d0d58d4bbed6770e792b`) |
| `com.apple.driver.AppleT8015PMPFirmware` | kernelcache payload @ `0x2c6c000` | **126 608 B** | the power-management-processor firmware — ARM64 image, first vector `0xea000018`, no identifying strings | **no** ✗ → this is the `apple/pmp-t8015.bin` the device's `pmp-t8015-v1` driver asks for |
| AGX kext `__TEXT.__const` blob | kernelcache @ `0xbfa99f` | 381 737 B (`g10p.img` = 381 728 B, wrapper stripped) | the image our ISA-decoder RE was done on (`gfx-t8015-const.bin`) — first vector `0xea000006` | n/a (kernel-side image, not a device file) |

The SmartIO and PMP images are *different* from the kext blob: SmartIO shares
38 of 93 4 KB chunks with it, PMP 43 of 93 (shared runtime data), and their
vector-table branch targets differ (`0xea00040e` / `0xea000018` vs
`0xea000006`).

### PMP firmware extraction (reproducible)

The A11 kernelcache (`/home/doug/a11-fw/kc/20H392__iPhone10,2/kernelcache.release.iPhone10,2_5`,
51 019 776 B) stores each firmware image as a 0x280-byte header block
(magic, lengths, tag string, version string) immediately followed by the raw
payload.  The **next** image's tag sits exactly `0x280` bytes after the end
of the previous payload — calibrated on the SmartIO image, whose extracted
length reproduces the device's file byte-for-byte ✓.

```sh
# -> /home/doug/a11-fw/out/pmp-t8015.bin
#    126 608 B   sha256 2dcf73b5e13fe9c3f93731c7ef09de8e6244de9f610c34fff2981af90010cd52
#    md5    9737473b4846681dc3f292b62ba6df03
#    payload = kernelcache[0x2c6c000 : 0x2c8ae90]   (end = next tag 0x2c8b110 - 0x280)
```

Tools: `/tmp/opencode/kc_fwscan.py` (payload location), `kc_tags.py` (tag
inventory), `kc_pmp.py` (PMP region + embedded Mach-O search), `kc_macho.py`
(section-level compare against the local const blob).

### The extracted PMP image matches what the driver wants (confirmed)

`drivers/soc/apple/pmp_t8015_v1.c` in the Orchard tree:
`request_firmware(&fw, pmp->fw_name, …)` → refuses `fw->size >
resource_size(pmp->sram)` → `memcpy_toio(pmp->sram_base, fw->data,
fw->size)`.  The firmware name comes from the DT (`firmware-name`), and the
device's node `soc/pmp@232300000` (`apple,t8015-pmp-v1`) says
**`apple/pmp-t8015.bin`** with three ranges — SRAM at
`0x2000000030320000`, size **8 MB** ✓.  So the raw IMG4 payload is copied
verbatim and 126 608 B fits comfortably ✓ — the extracted file is the right
artefact, it only has to be installed at `/lib/firmware/apple/pmp-t8015.bin`
(a write → needs the write phase).

Other strings worth remembering from that kernelcache: `t8015pmp`,
`AppleT8015PMPFirmware`, `%s: Found firmware %s for %s` (the AGX kext's
firmware lookup), `agxp_kext_g10p_rtbuddy.cpp`, and the AGX debug knobs
`iop-pmp`, `mcache-pmp`, `iop-gfx`, `gfx-handoff-base`, `gfx-shared-region-base`,
`pmp-dart`, `pmp-assert-energy`, … — i.e. the G10P AGX kext talks to the PMP
coprocessor directly.

## Driver landscape for a G10P 3D probe (2026-11-08, confirmed by inspection)

- The device's kernel tree is `OrchardLinux/linux` (`/home/doug/linux`,
  7.3.0-rc1, `origin/main`).  Its `drivers/gpu/drm/panthor/` is the
  **Mali-only upstream snapshot**: `dt_match` =
  {`mediatek,mt8196-mali`, `rockchip,rk3588-mali`, `arm,mali-valhall-csf`} —
  **no Apple compatible at all**, no Apple backend, no `apple,agx` support.
  So the running kernel has no way to bind a G10P, even with a perfect DT
  node.
- Upstream (mainline) panthor is likewise the Mali driver; the *Apple*
  GPU driver (the `apple` backend / DCP work) lives out-of-tree in the
  Asahi tree and is still held back from upstreaming (its DT bindings
  `Documentation/devicetree/bindings/gpu/apple,agx.yaml` are upstream, the
  driver itself is not).  Consequently a G10P probe needs the Asahi
  driver (or the user's own) **built out-of-tree against this kernel**.
- The host's `/home/doug/mesa` is the user's own PowerVR-style tree
  (`src/imagination/{g9p,csbgen,pco,pdsc,ds,common,vulkan,…}`, latest commit
  "pvr/g9p: no SPM scratch buffer") — it has **no Asahi frontend**, i.e. the
  A11/G10P instruction encoding must come from our own reverse engineering
  (the corpus work), not from Mesa's Asahi driver.  This confirms the ISA
  tables are the critical path for the G10P driver, while the *kernel*
  side needs the Asahi driver.

### Consequences for the plan

1. The 3D probe has **three** independent prerequisites, all of them
   currently missing on the device: (a) a GPU driver (Asahi's Apple
   backend, built out-of-tree), (b) a `gpu@` DT node, (c) the
   `apple/pmp-t8015.bin` firmware (now extracted ✓).
2. The native-display path (`disp0`) is *much* closer: the kernel already
   contains `adpdrm` + `adpdrm_mipi` + `apple,summit`; it only needs a DSI
   controller node and a panel node with the A11 timings.

## The A11 has no GPU driver anywhere — checked in the Asahi tree (2026-11-08, confirmed)

The Asahi kernel tree was cloned read-only (`/home/doug/asahi-linux`, branch
`apple-soc/drivers-7.3`, plus `asahi` and `apple-soc/dt-7.3` fetched
shallowly).  Result:

| artefact | what it supports | A11 / G10P? |
|---|---|---|
| `drivers/gpu/drm/panthor/` (in `apple-soc/drivers-7.3` **and** in the Orchard tree) | the **Mali** driver only — `dt_match` = mt8196 / rk3588 / mali-valhall-csf | **no** |
| `drivers/gpu/drm/asahi/` (branch `asahi`, written in **Rust**, which is why it is not upstreamed) | hardware configs `hw/t600x.rs`, `hw/t602x.rs`, `hw/t8103.rs` (M1), `hw/t8112.rs` (M2) | **no** — no `t8015` |
| `drivers/gpu/drm/apple/` (branch `asahi`) | the **DCP display** driver (A12+ `apple,h7-display-pipe` family) | **no** — the A11's display controller is `disp0,t8015` |
| `arch/arm64/boot/dts/apple/t8015-common.dtsi` (`apple-soc/dt-7.3`) | display = `apple,simple-framebuffer` only; **no `gpu@` node at all** | n/a |

The Asahi driver's firmware-ABI enum even lists `G10P = 5` (`GpuCore` in
`drivers/gpu/drm/asahi/hw/mod.rs`) — i.e. the *value* is known to the driver
family, but there is **no chip support, no firmware path and no DT node** for
`t8015`.

### What this means (confirmed)

* A G10P 3D probe is **not** a DT-and-config job on top of an existing
  driver — no kernel driver for the A11 exists in any tree, upstream or
  otherwise.  The A11 GPU port is a from-scratch driver project (the A10 G9P
  `OrchardLinux/gpu` work is the natural template; our own G10P firmware RE
  already covers the init-data layout, runtime size `0x8f000` and the Fender
  path).
* The **native display** path is likewise not "DT only": it needs an A11
  display-controller driver (`disp0,t8015`), a Synopsys DSI controller driver
  (`mipi-dsim-1,synopsys`) and a `lcd,pinot` panel driver with the 1080×1920
  timings — none of which exist in any tree today.  The m1n1/simplefb display
  remains the working path and is not at risk.
* The ISA work (corpus framing, A11 deltas, exact lengths) is therefore not
  blocked by anybody else: it is on the critical path for *any* G10P driver,
  and it is the one piece where our own RE is ahead of the public state.

## ADT node data for the GPU and the display (read-only, 2026-11-08)

Read from `/home/doug/omarchy-iphone/adt/adt.txt` (iOS ADT capture, read-only
with explicit approval).  These are the properties a Linux DT node would have
to reproduce.

**GPU (`sgx`, `compatible = [gpu,t8015]`)**

| property | value |
|---|---|
| `reg` | `0x04000000` size `0x00100000` (RGX core), `0x04D00000` size `0x00020000` (Fender) |
| `clock-ids` | `[265]` |
| `power-gates` | `[148, 123]` (GFX, GFX-KF) |
| `has-kf` | `1` |
| `metal-standard` / `opengl-standard` | `256` / `768` |
| `perf-states` | 20 entries, **all `freq = 0, volt = 0`** — the bootloader fills them at runtime ✓ (so the ADT alone cannot give the OPP table) |

**GPU coprocessor (`gfx-kf`, phandle 148, `device_type = gfx-kf`, `role = GFX`)**

| property | value |
|---|---|
| `reg` | `0x04D20000` size `0x00020000` (IOP), `0x04D00000` size `0x00020000` (Fender) |
| `interrupts` | `[260, 259, 262, 261]` — the GPU mailbox IRQs (the set 259–262 ✓) |
| `clock-ids` / `clock-gates` | `[269]` / `[149]` |
| `iop-version` | `1` |
| `power-gates` | `[149]` |

**GPU firmware service (`iop-gfx-nub`, phandle 149)** — `compatible =
[iop-nub,rtbuddy-v2]`, `firmware-name = GFX`, `no-firmware-service`,
`power-managed = true` → this is the RTBuddy path that serves the GFX
firmware (the `AGXFirmwareKextG10PRTBuddy` role).

**Display (`disp0`, `compatible = [disp0,t8015]`, `device_type =
display-subsystem`)**

| property | value |
|---|---|
| `reg` | `0x18000000` size `0x002A6000`; `0x18708000` size `0x1000`; `0x320B8000` size `0x1000` |
| `interrupts` | `[220, 226, 217, 218, 219, 221, 216, 227]` |
| `clock-ids` / `clock-gates` | `[317, 315]` / `[254, 118, 116, 115]` |
| `power-gates` | `[254]` |
| `iommu-parent` | `127` |

**DSI (`mipi-dsim`, `compatible = [mipi-dsim-1,synopsys]`, `device_type =
mipi-dsim`)** — `reg 0x18400000` size `0x00100000`, `interrupts = [225]`,
`clock-ids = [273]`, `clock-gates = [113]`, `power-gates = [113]`,
`mipi-version = 5`, `agile-line-count = 9`, and a child
**`lcd { compatible = [lcd,pinot] }`** — the iPhone 8 Plus panel ("pinot"),
with its timings in the `display-eeprom` blob rather than in the node.

### Correction: the native display path needs *drivers*, not just a DT node

The A11's panel is a **DSI panel** driven by `disp0` + `mipi-dsim`
(Synopsys DSI), not by the GPU.  The kernel we surveyed has:

* `adpdrm` — binds **`apple,h7-display-pipe`** (A12+/M1), *not* `disp0,t8015` ✗
* `panel-summit` — binds `apple,summit` but is a **60×2008** panel (some other
  Apple device), *not* the 8 Plus's 1080×1920 ✗
* no driver for `disp0,t8015` ✗, no driver for `mipi-dsim-1,synopsys` ✗, no
  panel driver for `lcd,pinot` ✗

So `disp0` on this device needs: an A11 display-controller driver, a Synopsys
DSI controller driver, and a `pinot` panel driver with the 1080×1920 timings
(readable from the `display-eeprom` blob) — plus the DT nodes.  The
m1n1/simplefb path stays the working display.

