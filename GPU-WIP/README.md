# GPU-WIP — Apple A11 / T8015 (**G10P**) GPU research

> **Status: OFFLINE RESEARCH ONLY.**
> Nothing in this area has booted a GPU, submitted a job, or drawn a frame on the
> D21. There is no working driver. Every statement below is tagged
> **confirmed** (verified from data on disk), **candidate** (consistent with the
> evidence but not proven), **negative** (a hypothesis that was tested and
> failed), or **unknown**. The one live interaction with the device so far was a
> **read-only survey** (sysfs / procfs / device-tree / dmesg reads and copy-out
> of boot artefacts) — no writes, no driver loads, no GPU enablement.

The full research record lives in [`kb/`](kb/); this file is the index and the
condensed result set.

| file | content |
|---|---|
| [`kb/A11-GPU-FINDINGS.md`](kb/A11-GPU-FINDINGS.md) | broad findings: hardware map, firmware provenance, device survey, driver landscape |
| [`kb/A11-GPU-G10P-LAYOUT.md`](kb/A11-GPU-G10P-LAYOUT.md) | driver/firmware layout: Fender, windows, init data, runtime constants |
| [`kb/A11-GPU-G10P-ISA.md`](kb/A11-GPU-G10P-ISA.md) | the AGX/A11 instruction-set work: corpus, framing, opcode deltas, length table |
| [`kb/A11-GPU-G10P-LENGTHS.json`](kb/A11-GPU-G10P-LENGTHS.json) | the solved A11 instruction-length table, machine-readable |
| [`kb/A11-GPU-G10P-FIELDS.txt`](kb/A11-GPU-G10P-FIELDS.txt) | field/site dump of the extracted G10P firmware image |
| [`tools/`](tools/) | the analysis scripts used (pure Python, no Apple data) |

## Executive summary

### 1. The chip — G10P is the A11's AGX, and the A10's G9P is its sibling (confirmed)

The D21 kernelcache carries `com.apple.AGXFirmwareKextG10PRTBuddy`
(`role = GFX`), `com.apple.AGXG10P` and the `AGXAcceleratorG10` class, so the
A11 GPU is **G10P** (not "G11P"). Same architecture family as the A10's **G9P**:
Fender power/control block, Apple's GFX firmware on a `gfx-kf` AppleA7IOP V2
coprocessor, RTKit + AGX rings.

Hardware map (from the live ADT):

| block | A10 T8010 | **A11 T8015** |
|---|---|---|
| RGX core | `0x20100000` | **`0x04000000`** |
| Fender | `0x201d0000` | **`0x04D00000`** |
| IOP (`gfx-kf`) | `0x201d20000` | **`0x04D20000`** |
| mailbox IRQs | 189–192 | **259–262** |
| GPU compat | `gpu,t8010` | **`gpu,t8015`** / `apple,t8015-gpu` |

**The Fender register map is identical to the A10** (proved by disassembling
`AGXG10P`'s `__TEXT_EXEC`): power state at Fender+`0x1000` (write `state | 0x10`,
poll bit 4, state-1 request `0x11`), window range `+0x200c..+0x2020`, status at
`+0x1010`. With the ADT base, the A11 power-state register is **`0x04D01000`**,
and the A10 driver's `FENDER_POWER_STATE` / `FENDER_WINDOW` offsets port
verbatim. Only the bases change.

### 2. Firmware — three *different* T8015 images, not versions of one another (confirmed)

This was the biggest source of confusion, and it is now settled by hash and
offset. The iOS 16.7.16 kernelcache
(`20H392__iPhone10,2/kernelcache.release.iPhone10,2_5`, 51 019 776 B) stores
each firmware image as a 0x280-byte header block (magic, lengths, tag string,
version string) followed by the raw payload; the next image's tag sits exactly
`0x280` bytes after the end of the previous payload (calibrated against the
SmartIO image, whose extracted length reproduces the device's file
byte-for-byte).

| image | where | size | what it is | on the device? |
|---|---|---|---|---|
| `com.apple.driver.AppleT8015SmartIO` | payload @ `0x2ccf000` | 616 336 B | the GPU's own runtime ("smart IO") firmware — ARM64 image, first vector `0xea00040e` | **yes** — `/lib/firmware/apple/t8015-smartio.bin`, byte-identical to our offline copy (md5 `b3a23e8a…`) |
| `com.apple.driver.AppleT8015PMPFirmware` | payload @ `0x2c6c000` | **126 608 B** | the power-management-processor firmware — ARM64 image, first vector `0xea000018` | **no** — this is the `apple/pmp-t8015.bin` the kernel asks for and cannot find; **extracted and validated** (see below) |
| AGX kext `__TEXT.__const` blob | kernelcache @ `0xbfa99f` | 381 737 B | the image the firmware-side RE was done on (`gfx-t8015-const.bin`); first vector `0xea000006` | n/a — kernel-side image, not a device file |

The SmartIO and PMP images are *not* the same build as the kext blob: SmartIO
shares 38 of 93 4 KB chunks with it, PMP 43 of 93 (shared runtime data), and
the vector-table branch targets differ.

**PMP firmware — new, validated.** `drivers/soc/apple/pmp_t8015_v1.c` does
`request_firmware()` using the DT's `firmware-name`, refuses anything larger
than the PMP SRAM, and then `memcpy_toio()`s the file verbatim into it. The
device's node `soc/pmp@232300000` (`apple,t8015-pmp-v1`) asks for
**`apple/pmp-t8015.bin`** and describes an 8 MB SRAM at `0x2000000030320000`,
so the raw IMG4 payload is exactly the right artefact (126 608 B fits easily).
It is extracted locally; it has **not** been installed (that is a write).

### 3. Live device survey (read-only) — what is actually present (confirmed)

The survey device is the **iPhone 8 Plus (Global)** (`iPhone10,2`, A11/T8015),
running `7.3.0-rc1-orchard-apple-16k` (Orchard/Arch Linux ARM), a fully
built-in kernel — `/lib/modules/<ver>` contains no modules at all.

| area | state |
|---|---|
| display (working) | simplefb/simpledrm: `card0` + `fb0` (`simpledrmdrmfb`), 1080×1920, `x2r10g10b10`, stride 4352, physical `0x8ba75c000` (8 355 840 B), fed by the m1n1/dfrmt framebuffer |
| native display | the kernel **does** contain `adpdrm` + `adpdrm_mipi` + the panel compatible **`apple,summit`** + `DRM_MIPI_DSI` — but the DTB has **no DSI controller node and no panel node**, so `disp0` cannot appear without DT work |
| GPU | **no `gpu@` node in the DTB**; the kernel image contains **no panthor / powervr / AGX driver code** (`/proc/config.gz` still says `CONFIG_DRM_POWERVR_APPLE=m`, but no code and no `.ko` ship) |
| power | PMGR exposes the **`gfx`** controller @ `0x80338` and the display domains `disp0_fe/be/gp/gp0/gp1/ppp/hilo` — as power domains only, no devices |
| iommu | `apple,t8015-dart` (`iommu@259c50000`) present |
| mailbox | only three ASC mailboxes (`232308000`, `236808000`, `257008000`); **no GPU mailbox**, and IRQs 259–262 are not registered |
| PMP | `pmp-t8015-v1` binds but its firmware is missing → `Direct firmware load … failed` → PMGR/GFX power transitions are not dependable until it is installed |
| userspace | Mesa 26.2.5 with **`asahi_dri.so`** and `asahi_drm.h` — the userspace side is ready the moment a GPU device exists |

### 4. Driver landscape — the A11 has no in-tree driver, anywhere (confirmed)

- The kernel tree this device boots from (`OrchardLinux/linux`, 7.3.0-rc1)
  contains `drivers/gpu/drm/panthor/` — but it is the **Mali-only upstream
  snapshot**: `dt_match` = {`mediatek,mt8196-mali`, `rockchip,rk3588-mali`,
  `arm,mali-valhall-csf`}, no Apple compatible, no Apple backend. A perfect DT
  node would still not bind a G10P.
- Upstream panthor is likewise the Mali driver. The *Apple* GPU driver lives
  out-of-tree in the Asahi tree; upstream currently has only the DT bindings
  (`gpu/apple,agx.yaml`), not the driver.
- **The Asahi tree was cloned and checked** (read-only, branch
  `apple-soc/drivers-7.3` plus `asahi` and `apple-soc/dt-7.3`):
  * `drivers/gpu/drm/asahi/` (branch `asahi`, written in **Rust** — which is
    why it is not upstreamed) has hardware configs for `t600x`, `t602x`,
    `t8103` (M1) and `t8112` (M2) — **no `t8015`**. Its firmware-ABI enum
    does know the value `G10P = 5`, but there is no chip support, no
    firmware path and no DT node for the A11.
  * `drivers/gpu/drm/apple/` is the A12+ **DCP display** driver; the A11's
    display controller is `disp0,t8015`, which nothing binds.
  * `arch/arm64/boot/dts/apple/t8015-common.dtsi` describes the display as
    `apple,simple-framebuffer` only and contains **no `gpu@` node**.
- **Conclusion: no A11/G10P GPU driver exists in any tree** — upstream,
  Asahi or Orchard. A G10P probe is a from-scratch driver project, not a
  DT-and-config job. The A10 G9P `OrchardLinux/gpu` work is the natural
  template, and our own G10P firmware RE already covers the init-data
  layout, runtime size `0x8f000` and the Fender path.
- The Mesa side in use here is the PowerVR-style `src/imagination` tree
  (G9P), which has no Asahi frontend, so the A11 instruction encoding has to
  come from our own reverse engineering.

### 5. The instruction set — the length table is solved (confirmed)

The corpus (`ds.g10p` → 94 `*.g10p-o` files) is Apple's own precompiled A11
shader set. Each object is a **Mach-O object** (`0xfeedfacf`, `MH_OBJECT`,
arm64) with the AGX words in `__TEXT,__text`, plus `__GPU_METADATA`,
`__GPU_LD_MD`, `__GPU_ARCH_LD_MD`, `__GPU_STATS_MD`, `__GPU_REMARKS_MD`
sections.

**Result (confirmed): G10P uses a uniform 6-byte instruction quantum.** Every
AGX instruction in the A11 corpus is exactly **6 bytes = 3 × 16-bit words**,
except `trap` (`0x0008`) and the two terminators (`0x0088`, `0x0108`) at
**2 bytes**, plus a catch-all of A11-only opcodes at **4 bytes** (L-bit clear)
and **2 bytes** (L-bit set).

This is a *different framing scheme* from Mesa's A12+ AGX, which mixes
2/4/6/8/10/12 bytes and selects between two lengths with bit 15. The opcode
*values* are Mesa-compatible; the *lengths* are not — so Mesa's table cannot be
substituted, and the earlier "the corpus is Mesa's public AGX dialect" claim
is superseded on the length half.

The opcode dictionary used is Dougall Johnson's `applegpu` table (a
data-driven descriptor table for Apple's own AGX ISA: 161 descriptors, 81
distinct low-16 signatures, each with an explicit size pair and a length-bit
position). It is a far better dictionary for this corpus than Mesa's 57
opcodes, and its `jmp_exec_none` = `0xc020` is *exactly* the value this
project had already measured independently in the corpus.

The table is published machine-readable as
[`kb/A11-GPU-G10P-LENGTHS.json`](kb/A11-GPU-G10P-LENGTHS.json) and is
re-derived by [`tools/g10p_lengths.py`](tools/g10p_lengths.py).

**And the field layout is recovered too (confirmed).** With every instruction
being exactly three 16-bit words, the layout can be measured directly instead
of guessed: frame the corpus, then for every field that `applegpu` declares,
check whether A11 uses those bits, folds them into the opcode, ignores them,
or has no room for them.

* **word 0 is G13's header verbatim** for **108 of the 110** opcode classes in
  the corpus: opcode bits 0–5 (constant), bit 6 `S`, bits 7–8 `Dt`, bits 9–14
  `D`, bit 15 `L`.  (The two exceptions have opcode bits above 5 in G13 too.)
* **words 1–2 are G13's operand fields at G13's positions, truncated at bit
  48.** Of the 817 G13 field declarations that belong to the opcodes the
  corpus uses: **555 (67.9 %) are live at the same position**, 82 are unused,
  31 are folded into the opcode, and 204 live beyond bit 48 (G13's longer
  forms have no room in A11's 3 words).
* `iadd` is the cleanest case: **all 14 G13 fields that fit are live at G13's
  positions**; only G13's `s2` (bit 52) is dropped — A11's `iadd` *is* G13's
  `iadd` layout packed into 6 bytes.  `imadd` keeps 12 fields at G13's
  positions (including the third source `C` @40) and drops the third source's
  type/extension bits.
* Consequence: a **G13 disassembler can be reused almost verbatim for G10P** —
  take `applegpu`'s descriptor table, drop every field above bit 48, and
  force the length to 6 bytes (2 for trap/stop).  That is a buildable
  specification for the `pvr_arch_g10p` disassembler the driver needs.

Reproduce with [`tools/g10p_fields.py`](tools/g10p_fields.py) (`--summary`
for the global table, `--op NAME` for one opcode).

A11 deltas:

| delta | state | note |
|---|---|---|
| `stop = 0x0108` | confirmed, 2 bytes | Mesa's is `0x0088` — and G13's `0x0088` also occurs in the corpus (109×) |
| `jmp_exec_none = 0xc020` | confirmed, 6 bytes | Mesa's is `0xc200`; **G13's `applegpu` agrees (`0xc020`)** |
| `trap = 0x0008` | confirmed, 2 bytes | G13 agrees; Mesa agrees |
| 16-bit ALU opcodes carry **no L bit** | confirmed | `0x26` (fadd16), `0x36` (fma16), `0x16` (fmul16) |
| `mov_imm` family uses opcode byte **`0xc2`**, destination in bits 8‑11 | candidate | `06c2 0020`, `04c2 0024`, `02c2 0028`, `00c2 002c`; the Mesa-style `0x62` form also occurs (646 instruction starts) |
| **`imad` = 6 bytes** (Mesa: 8) | confirmed | forced by the corpus — changing it to 12 B breaks an object |
| **`texture_load` = 6 bytes** (Mesa: 8) | confirmed | the earlier "6 or 12" candidate is withdrawn |
| `iadd`, `bfi`, `icmpsel`, `fcmpsel`, `atomic` = 6 bytes (Mesa: 8) | confirmed | same delta as `imad` |
| `wait`, `threadgroup_barrier`, `ret`, `doorbell`, `call`(0x0004) = 6 bytes (Mesa/G13: 2) | confirmed | A11 is *longer* than G13 here |
| A11-only opcodes (no G13 signature) | 4 B / 2 B | first words seen: `0x2000`, `0x0040`, `0x0200`, `0x5200`, `0x5024`, `0x8000`, `0x8100`, … — **not yet named** |

Evidence for the 6-byte quantum (five independent legs, all reproducible with
`tools/g10p_lengths.py`):

1. **Local repetition period** — where one instruction repeats, the period
   *is* its length: `imadd` → 3 words in 5172 resolved cases, `fadd16` →
   gcd 3, `trap` → 1 word in 877 cases. The global word autocorrelation peaks
   at d = 3, 6, 9 words — every peak a multiple of 3.
2. **Exact DP tiling** — with a fixed table, the tileable positions are a
   forward-reachability DP, so "this object tiles" is a *proof*. The uniform
   6-byte baseline tiles **72/94 objects and 477 051/492 190 words** exactly.
3. **Minimal-deviation repair** — only three deviations are needed to reach
   **94/94**; everything else stays at 6 bytes.
4. **Independent structural check** — the next function after a terminator must
   start on a **64-byte boundary**. With the solved framing that holds for
   **80/125 (64.0 %)** of mid-section functions, against **3.1 %** by chance.
5. **Cross-validation** — solve on half the corpus, test on the other half:
   even→odd 36/47 train → **36/47 held out**; odd→even 47/47 train → **46/47
   held out**.

This converges with the *decoder-side* analysis of Apple's own AGX3
disassembler in the iOS dyld cache, which independently established that the
length is a **pure function of the opcode** (`ISA opcode → MC opcode →
MCInstrDesc[MCopcode].Size`), that it is **not a flag bit**, and that the
instruction is **16-bit-word granular** (`size == 2 × words`). The corpus-side
table now supplies the *values* that `MCInstrDesc` would have given.

Negative results worth keeping (they close dead ends):

- Mesa's `agx_opcodes.py` lengths cannot be substituted for A11's: under
  Mesa's table the corpus tiles 0/94 objects.
- The "same-source differential" instrument is **dead**: the 32-instance
  groups are not same-code-different-constants (word counts 428→1091,
  terminator offsets differ), so cross-instance alignment at fixed offsets
  cannot work.
- The "uniform 6-byte grid" refutation was an **artefact** of assuming no
  2-byte instructions; with 2-byte trap/stop the phase shifts and the uniform
  model survives.
- The "indivisible motif" argument was Mesa-specific (`0x0000` matches Mesa's
  mask-0 `device_store`/`uniform_store`); the conclusion survives only on the
  independent period measurement.
- `AGXCompilerCore` / `libGPUCompilerImpl` contain **no Mesa-shaped tables at
  all** (a scan of every data section for `(exact, mask, len, len)` runs found
  zero hits), even though `AGXCompilerCore` does carry a per-generation target
  list (`.agc-target-.g5p-b0.g9p-a0.g10p-b0.g11p-a0.…`). The A11 tables are
  there, but not in Mesa's shape.

### 6. What a G10P 3D probe needs

Since **no A11 driver exists anywhere** (see §4), a probe needs:

1. **A G10P GPU driver** — a new kernel driver for the A11 GPU (A10 G9P
   `OrchardLinux/gpu` work as the template; our own G10P firmware RE already
   supplies the init-data layout, runtime size `0x8f000` and the Fender
   register path).
2. **A DT node** — `gpu@…` with `apple,t8015-gpu`, the ADT map above
   (RGX `0x04000000`, Fender `0x04D00000`, IOP `0x04D20000`), the GPU mailbox
   and IRQs 259–262 — plus the `gfx-kf`/IOP node and the RTBuddy firmware
   service node.
3. **The PMP firmware** — `apple/pmp-t8015.bin` (extracted, validated, not yet
   installed) so GFX power transitions work.

The **native display path needs drivers too**, not just DT: an A11 display
controller driver (`disp0,t8015`), a Synopsys DSI controller driver
(`mipi-dsim-1,synopsys`) and a `lcd,pinot` panel driver with the 1080×1920
timings (the timings live in the `display-eeprom` blob, not in the ADT node).
The m1n1/simplefb display keeps working meanwhile and needs no changes.

## Honesty rules used in this area

* **confirmed** — re-derived from data on disk, with the tool and offset given.
* **candidate** — fits the evidence, not proven.
* **negative** — hypothesis tested and refuted; kept so it is not re-tried.
* **unknown** — open, with the next concrete experiment listed.
* No hardware claims are made without a boot. The device survey was read-only.

## Artefact policy

No Apple firmware, binaries, DTBs or corpus files are committed here
(the repo `.gitignore` already excludes `*.bin`, `*.img`, `*.dtb`, `*.ipsw`).
The scripts in `tools/` only read local paths and print findings; they embed no
Apple data.
