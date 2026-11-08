# A11 / T8015 GPU — pre-flight for the hardware probe

*(Pre-flight is complete; nothing here was executed on hardware.)*

Status of the prerequisite work: the G10P ISA is solved and validated
(length table, field layout, branch semantics — see the ISA KB).  This file
plans the **first hardware probe**: booting the GFX IOP's RTKit firmware and,
separately, powering the RGX core.

Everything below is taken from the iPhone 8 Plus ADT capture and the firmware
images already extracted from the 20H392 kernelcache.  Nothing on the device
has been written.

## 1. What the ADT says (T8015 / iPhone 8 Plus, iPhone10,2)

### The GPU itself (`sgx`)

| property | value |
|---|---|
| compatible | `[gpu,t8015]` |
| device_type | `sgx` |
| reg | RGX `0x04000000` size `0x100000` (1 MiB) · Fender `0x04D00000` size `0x20000` |
| interrupts | `255, 256, 257, 258, 263` (parent = AIC, interrupt-parent 28) |
| clock-gates | `[148, 123]` |
| power-gates | `[148, 123]` |
| has-kf | `1` |
| CORE_ID | expected at RGX+`0x18` (`0x04000018`), CORE_REVISION at RGX+`0x20` — unverified on A11 |
| `iommu-parent` | **absent** — the GPU's DMA does *not* go through a DART (unlike `avd`, `mcu`, `jpeg`); it uses its own Rogue MMU, exactly like the A10 |

### The GFX coprocessor (`gfx-kf`) — the thing to boot

| property | value |
|---|---|
| compatible | `[iop-gfx,t8015]` |
| device_type | `gfx-kf` · `role = GFX` |
| reg | `0x04D20000` size `0x20000` · `0x04D00000` size `0x20000` |
| interrupts | `260, 259, 262, 261` (parent = AIC, 28) |
| clock-gates | `[149]` (its own PMGR id) |
| power-gates | `[149]` |
| clock-ids | `[269]` |
| firmware-name | **`GFX`** |
| subnode | `iop-gfx-nub`: `compatible = [iop-nub,rtbuddy-v2]`, `power-managed = true`, `coredump-enable = 32` |

### The power-management coprocessor (`pmp`)

| property | value |
|---|---|
| compatible | `[iop-pmp,t8015]` |
| reg | `0x232300000` `0x8000` (akf) · `0x232400000` `0x10000` (control) · `0x232500000` `0x20000` (sram) |
| interrupts | `230, 229, 232, 231` |
| firmware-name | `t8015pmp` |
| nub | `region-base = 0x232a6c000`, `region-size = 131072` |

The PMP is already *working* on this phone: the hoolock kernel carries
Nick Chan's `apple,t8015-pmp-v1` driver (`drivers/soc/apple/pmp_t8015_v1.c` +
DT node + binding).  It boots the PMP firmware from `apple/pmp-t8015.bin`.
That driver is the **template** for the GFX IOP driver.

### PMGR domains

| domain | id1 | flags |
|---|---|---|
| `GFX` | 126 | on, critical, perf |
| `GFX-SGX` | 149 | no_ps |
| `GFX-KF` | 123 | no_ps |
| `GFX-BUSY` | 150 | ps, perf_idx 19, psreg 2 |

The `sgx` node has **no power state of its own** beyond `[148, 123]`; the
`GFX` domain (126) covers the GPU and its coprocessor (both come up
together, like the A10's `GFX`, 0x7c).

## 2. Firmware inventory (extracted, **not installed**)

| image | size | what it is |
|---|---|---|
| `pmp-t8015.bin` | 126 608 B | `AppleT8015PMPFirmware`, RTKit `2062.142.1.release`, ARM32 — the PMP firmware; sha256 `2dcf73b5e13fe9c3f93731c7ef09de8e6244de9f610c34fff2981af90010cd52`; boots today |
| `g10p.img` | 381 728 B | the AGX kext's `__TEXT.__const` payload = **the GFX firmware**; ARM32, `G10 Firmware initializing`; task names `agx_background`, `agx_recovery`, `agx_interrupt`, `agx_power`, `agx_sampler`; registers `AGX_CR_USC_{VDM,PDM,CDM}_{SERV,DEBUG_STATUS}` |
| `gfx-t8015-const.bin` | 381 737 B | the same GFX firmware with a 9-byte `.Release` RTKit header still attached |
| `AGXFirmwareKextG10PRTBuddy.bin` | 384 136 B | the `AGXG10P` kext binary (source name `agxp_kext_g10p_rtbuddy.cpp`); carries `requestFirmwareBinary`, `getBootConfigOffset`, `getRuntimeBinSize`, `getFWResumeFlagOffset`, `GFX %s FW %s! (%s)`, `Error mapping firmware GART physical address PA_%llX size:%u, status:0x%X` |

Note: **no DART for the GPU** — the GFX IOP's DMA engine (and the GPU itself)
use Rogue's own MMU.

## 3. The shape of the probe

The A10's bring-up (see `orchard-gpu/a10/FIRST-LOOK.md`) reached RTKit HELLO
*before* any GPU programming.  That is the right first milestone for the A11.
Two stages, each its own boot, each revertible:

**Stage 1 — boot the GFX IOP only (no GPU programming)**
1. Install the firmware image on the rootfs as `apple/gfx-t8015.bin` (name is
   ours to choose; the nub asks for `GFX`).
2. Add the `gfx-kf@4d200000` DT node (+ `mbox` if one is required), modelled
   on the PMP node.
3. Load an `apple,t8015-gfx-iop` module modelled on `pmp_t8015_v1.c`:
   - upload the firmware (an uncached DRAM bounce buffer — the firmware is
     381 728 B, far bigger than this IOP's SRAM),
   - set the AKF remap windows (A10 equivalents: `AKF_REMAP_IOP/AP/SZ`),
   - start the CPU (`writel(1, ctl_base)` on the A10/PMP),
   - wait for RTKit HELLO v12 over the mailbox, then EPMAP / STARTEP and the
     crashlog buffer request (the A10's minimal handshake).
4. Success: `RTKit: Initializing (protocol version 12)` and the endpoints
   start and stay silent (they wait for init data).

**Stage 2 — Fender power + identity read (optional, still bounded)**
1. With the GFX IOP alive, request Fender state 1 (`Fender+0x1000 = 0x11`; on
   A11 Fender is at `0x04D00000`).
2. Read `RGX_CR_CORE_ID` (`0x04000018`) and `CORE_REVISION` (`0x04000020`).
3. Success: an ARM64-style readback with no panic and a sensible `0x??????`
   identity (the A10 read `0x011b0602` / `0x000d0a00`).

## 4. What is **not** known yet (and must be resolved offline first)

| unknown | how to resolve |
|---|---|
| Which of the two `gfx-kf` regions is akf / control / SRAM | RE `AGXG10P__TEXT_EXEC.bin` for the AKF/control mappings (the ADT gives only the two extents) |
| The mailbox offset for this IOP (PMP has it at `akf+0x8000`) | same RE pass, or the ADT if a mailbox node is added by the kext |
| The run-bit offset (A10 used `base+0x2048`) | same RE pass |
| The GFX firmware image to use (`g10p.img` vs `gfx-t8015-const.bin`) | compare headers; `g10p.img` is the stripped, verified image |
| The PMP is presumably required for Fender / power gating | booted already by the PMP driver; keep it booted |
| Fender on A11: is the state-request sequence the same as the A10's `0x11`? | RE `agxp_kext_g10p_rtbuddy.cpp` / the Fender notes in `orchard-gpu/a10/FENDER.md` |

## 5. Safety / rollback

- Nothing here touches the display path: `simplefb` stays the console.
- Booting the GFX firmware cannot program the GPU core. Stage 1 and Stage 2
  cannot leave the GPU in a broken state — a reboot restores it, because the
  firmware is not installed permanently until the probe works.
- The old `pmp` service can be stopped/unloaded; the PMP node is already in
  the kernel and known-good.
- Every command on the device is bounded (`timeout -k 5 N …`) and the device
  is returned to you after the probe.
- **Gate:** nothing on the device is written without your explicit “go”.
  Both stages are one boot each; each can be aborted by a reboot.

## 6. What Phase 2+ needs (after the probe)

- Init-data layout + the Fender state machine (from the AGX kext RE; the
  A10's notes in `orchard-gpu/a10/FENDER.md` apply as a template).
- A powervr-variant driver (or `panfrost`/`asahi`-style) — a large project.
- The disassembler we built (ISA KB) for the shader side.

## 7. Immediate offline work before the “go”

1. RE `AGXG10P__TEXT_EXEC.bin` for the IOP boot path → the missing offsets in
   §4. Time-boxed; if inconclusive, Stage 1 starts with the PMP mapping as the
   starting hypothesis and the kext RE continues in parallel.
2. Draft the `apple,t8015-gfx-iop` DT binding + node patch and the driver
   source (out-of-tree module), ready to build.
3. Prepare the firmware copy script + checksums, and the uninstall/rollback
   script.
