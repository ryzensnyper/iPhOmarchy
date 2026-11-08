# GPU (A11 / T8015) — WIP research, **not** usable yet

> **📚 The full research record now lives in [`../GPU-WIP/`](../GPU-WIP/)** —
> offline findings, the corpus/ISA work, the firmware inventory, the read-only
> device survey and the analysis scripts, with a condensed index in
> [`../GPU-WIP/README.md`](../GPU-WIP/README.md). This page is the older
> summary and is kept for the narrative; where the two disagree, `GPU-WIP/` is
> current.

> **Status: WORK-IN-PROGRESS / EXPERIMENTAL.** Nothing here boots a GPU or
> draws a frame on the D21. It is a feasibility dig only. There is **no
> mainline A11 GPU driver** — the Orchard A10 work is the template, and the
> A11 port is a multi-session bring-up that still needs most of the hard
> parts (init-data layout, runtime size, shader backend). Treat every value
> below as "to be confirmed on hardware".

## Why this jumped from "out of scope" to "plausible"

Orchard published working **A10 (T8010) GPU** support
([OrchardLinux/gpu](https://github.com/OrchardLinux/gpu)): Hyprland with all
effects at 60 fps via Zink on a Mesa Vulkan driver. That work is for the
**A10 G9P**, but it turns out the **A11 is the next generation of the same
family**.

The A11 GPU is **G10P**, not "G11P":

- D21 kernelcache (`20H392__iPhone10,2`) contains
  `com.apple.AGXFirmwareKextG10PRTBuddy` (`role = GFX`, RTBuddyService),
  `com.apple.AGXG10P`, and the accelerator class `AGXAcceleratorG10`.

Same architecture as the A10: a **Fender** power/control block, Apple's GFX
firmware on a `gfx-kf` AppleA7IOP V2 coprocessor, RTKit + AGX rings.

## What is already established (offline only, no hardware)

### Firmware

The G10P firmware lives in `AGXFirmwareKextG10PRTBuddy`'s `__TEXT.__const`
(extract it by mapping the kext's `_PrelinkExecutableLoadAddr` through the
kernelcache's `__PRELINK_TEXT` segment). The blob is `0x5d329` bytes and
starts with the same `\0Release\0` container header as the A10's G9P blob
(`0x5b320` bytes). **Apple firmware is never committed** (`.gitignore`).

### Hardware map (from the live ADT — `hardware/adt-d21-peripherals.txt` and
the full ADT capture)

| Block | A10 T8010 | **A11 T8015** |
|---|---|---|
| RGX core | `0x20100000` | **`0x04000000`** |
| Fender | `0x201d0000` | **`0x04D00000`** |
| IOP (`gfx-kf`) | `0x201d20000` | **`0x04D20000`** |
| mailbox IRQs | 189–192 | **259–262** |
| `sgx` compat | `gpu,t8010` | **`gpu,t8015`** |
| power gates | `ps_gfx` | GFX(148) + GFX-KF(123) |

`gfx-kf` node: `compatible = iop-gfx,t8015`, `role = GFX`,
`iop-version = 1`, two reg ranges (`0x04D20000`, `0x04D00000`).

### Fender register map — **identical to the A10** (proved from the kext)

Disassembling `AGXG10P`'s `__TEXT_EXEC` shows the same registers the A10
Linux driver already uses:

- **power state at Fender+`0x1000`** — write `state | 0x10`, poll bit 4
  (`str w8,[x0,#0x1000]` / `ldr w8,[x0,#0x1000]` / `tbnz w8,#4`), with a
  `mov w8,#0x11` state-1 request.
- **window range Fender+`0x200c..+0x2020`** (dummy-read by the kext),
- status at `+0x1010`.

So with the ADT Fender base `0x04D00000`, the A11 power-state register is
**`0x04D01000`**, and the A10 driver's `FENDER_POWER_STATE` / `FENDER_WINDOW`
offsets port verbatim. Only the base addresses change.

### Driver template

`OrchardLinux/linux` `drivers/gpu/drm/imagination/pvr_apple{,_layout}.c`
(A10). The A11 needs: a new `apple,t8015-gpu` match + DT node, the chip
constants swapped (`RGX_PA`, `FENDER_PA`, IOP base, mailbox), and — the hard
part — the **init-data layout re-derived from the G10P firmware/kext**.

## What still needs a lot of work (do not underestimate)

*Status as of 2026-11-08 — see `GPU-WIP/README.md` for the current set.*

1. ~~**Init-data layout showstopper.**~~ **Done offline.** The G10P init
   layout was re-derived from the G10P firmware/kext; the A10 offsets do *not*
   carry over field-for-field, and the `\0Release\0` wrapper is not part of
   the loadable image (image = `__const + 9`, size `0x5d320`). Full record:
   `GPU-WIP/kb/A11-GPU-G10P-LAYOUT.md`.
2. ~~**Runtime size / window registers.**~~ **Runtime size confirmed:**
   `getRuntimeBinSize` → `0x8f000`, same as the A10. IOP window/run register
   offsets still unconfirmed on G10P.
3. **IOP window/run registers** (`+0x08`/`+0x38`, Fender run `+0x2048`) —
   not yet confirmed on G10P.
4. **GPU performance states** — the ADT `sgx` table is zero-filled with
   `gpu-num-perf-states = 2`; a real m1n1 capture is needed for the OPP
   table the bootloader fills.
5. **A GPU driver that can bind a G10P.** The tree this device boots has
   panthor as the **Mali-only** upstream snapshot (no Apple compatible at
   all), and upstream panthor is likewise Mali-only — the Apple backend lives
   out-of-tree in the Asahi tree. So this is an out-of-tree driver build, not
   a DT-only job.
6. **Shader ISA — exact A11 length table.** The corpus framing is solved at
   the dialect level: the A11 shaders are Mesa's public AGX dialect
   (word-aligned, Mesa opcode values) plus a handful of A11 deltas
   (`stop = 0x0108`, `jmp_exec_none = 0xc020`, no L bit in the 16-bit ALU
   opcodes, `mov_imm` family opcode byte `0xc2`, `trap ≠ 0x0008`). What is
   still open is the exact length of the A11-only opcodes that match no Mesa
   signature (`0x0f00`, `0x06c2`, `0x8041`, `0x0083`, …) and the `imad` /
   `texture_load` split (6 or 12 bytes vs Mesa's 8).
7. **Device-side prerequisites** — a `gpu@` DT node (plus the GPU mailbox and
   IRQs 259–262) and the `apple/pmp-t8015.bin` PMP firmware, which the kernel
   currently cannot find (the blob has been extracted and validated offline,
   but not installed).
8. **Hardware confirmation** — the first boot must write `0x11` to
   `0x04D01000`, read back bit 4, then read `CORE_ID` at `0x04000000`.

## Reference points

- Orchard GPU project: <https://github.com/OrchardLinux/gpu> (`a10/bringup/`,
  `a10/FENDER.md`, `a10/COMPUTE.md`, `tools/a10/`).
- Kernel patches (on `OrchardLinux/linux` `origin/main`):
  `kernel/patches/drivers/gpu/0001-drm-imagination-Support-the-Apple-A10-T8010-GPU.patch`,
  `kernel/patches/devices/t8010/0010-0012` (display pipe, GPU, perf state).
- Mesa fork: <https://github.com/OrchardLinux/mesa> (`src/imagination`, G9P).
- Our extraction artifacts (Apple data, kept locally, never committed):
  G10P/G9P blobs, AGXG10P kext segments, `agxg10p.asm` — a frozen copy lives
  with the known-good snapshot.

**Bottom line:** implementable and the closest possible target (adjacent
silicon generation), the Fender/power path is proven and the firmware is in
hand, but the init-data layout, the runtime constants and the entire Mesa
shader backend remain, and none of it has run on hardware. This is a
long-term project, not a near-term milestone.
