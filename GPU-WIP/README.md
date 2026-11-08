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
- Consequently a G10P probe needs an **out-of-tree** GPU driver built against
  this kernel — either Asahi's Apple backend or our own. The Mesa side in use
  here is the PowerVR-style `src/imagination` tree (G9P), which has no Asahi
  frontend, so the A11 instruction encoding has to come from our own reverse
  engineering.

### 5. The instruction set — framing solved at the dialect level (confirmed / candidate)

The corpus (`ds.g10p` → 94 `*.g10p-o` files) is Apple's own precompiled A11
shader set. Each object is a **Mach-O object** (`0xfeedfacf`, `MH_OBJECT`,
arm64) with the AGX words in `__TEXT,__text`, plus `__GPU_METADATA`,
`__GPU_LD_MD`, `__GPU_ARCH_LD_MD`, `__GPU_STATS_MD`, `__GPU_REMARKS_MD`
sections.

Result (confirmed): the corpus is **Mesa's public AGX dialect** — word-aligned,
Mesa opcode values — with a handful of A11-specific deltas. Mesa's
`(exact, mask, length_short, length_long)` table tiles 89/94 objects at word
level, and 93/94 with the A11 `stop` override; a bit-offset sweep peaks only at
offset 0 (0.3539 hit rate vs 0.2363 random), so the stream is word-aligned,
not byte-packed.

A11 deltas:

| delta | state | note |
|---|---|---|
| `stop = 0x0108` | confirmed | Mesa's is `0x0088` |
| `jmp_exec_none = 0xc020` | confirmed | Mesa's is `0xc200` |
| 16-bit ALU opcodes carry **no L bit** | confirmed | `0x26` (fadd16), `0x36` (fma16), `0x16` (fmul16) |
| `mov_imm` family uses opcode byte **`0xc2`**, destination in bits 8‑11 | candidate | `06c2 0020`, `04c2 0024`, `02c2 0028`, `00c2 002c`; the Mesa-style `0x62` form also occurs (646 instruction starts) |
| `trap ≠ 0x0008` | candidate | `0x0008` is the A11 alignment *filler* word (runs of up to 26); A11 moved `trap` elsewhere — value unknown |

Candidate A11 length table (bytes): `wait`/`trap`/`stop` 2 · `zs_emit`,
`writeout`, `get_sr`, 16-bit `mov_imm` 4 · ALU `fadd/fmul/fma`, the compare
family, `bitop`, `device_load`, `jmp_exec_*` 6 · `bfi`, `fcmpsel`,
`device_store` 8 · **`imad` 6 or 12** (Mesa: 8) · **`texture_load` 6 or 12**
(Mesa: 8) — the last two are the open item, and framing still breaks on
A11-only opcodes that match no Mesa signature (blockers seen: `0x0f00`,
`0x06c2`, `0x8041`, `0x0083`, `0x8b8c`, `0x724a`, `0x8800`).

Negative results worth keeping (they close dead ends):

- The AGX3 encoder tables in libLLVM are a **different dialect** from the A11
  corpus: only 9.0 % of tiled instructions match an AGX3 encoder template, and
  libLLVM's AGX3 opcode space is all ≡7 mod 8 while Mesa's is not.
- `AGXCompilerCore` / `libGPUCompilerImpl` contain **no Mesa-shaped tables at
  all** (a scan of every data section for `(exact, mask, len, len)` runs found
  zero hits), even though `AGXCompilerCore` does carry a per-generation target
  list (`.agc-target-.g5p-b0.g9p-a0.g10p-b0.g11p-a0.…`). The A11 tables are
  there, but not in Mesa's shape.

### 6. What a G10P 3D probe needs (three independent prerequisites)

1. **A GPU driver** — Asahi's Apple backend (or ours), built out-of-tree for
   this kernel. Nothing in-tree can bind a G10P.
2. **A DT node** — `gpu@…` with `apple,t8015-gpu`, the ADT map above
   (RGX `0x04000000`, Fender `0x04D00000`, IOP `0x04D20000`), the GPU mailbox
   and IRQs 259–262.
3. **The PMP firmware** — `apple/pmp-t8015.bin` (extracted, validated, not yet
   installed) so GFX power transitions work.

The **native display path is much closer**: the kernel already has
`adpdrm` + `adpdrm_mipi` + `apple,summit`; it needs only a DSI controller node
and a panel node carrying the A11 panel timings. The m1n1/simplefb display
keeps working meanwhile and needs no changes.

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
