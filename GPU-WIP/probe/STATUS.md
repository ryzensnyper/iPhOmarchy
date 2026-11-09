# Probe — status and known-unverified items

**Scope of the probe: Stage 1 only** (RTKit HELLO from the GFX IOP).
Stage 2 (Fender + CORE_ID) and Phase 2 (init data, jobs) are not part of this.

## Verified against the G10P kext / this repo's analysis

| item | state |
|---|---|
| `getRuntimeBinSize = 0x8f000` | verified (LAYOUT KB §1) |
| `Fender+0x1000 = state\|0x10`, poll bit 4 | verified in kext at `0x2600` |
| Fender dummy-read window block at `+0x200c..+0x2020` | verified at kext `0x42d14..0x42d28` |
| `g10p.img` is the GFX firmware | verified (ARM32, "G10 Firmware initializing", tasks `agx_background`…`agx_sampler`) |
| GPU does not hang off a DART | verified — `sgx` has no `iommu-parent` |
| GFX IOP node / addresses | taken from the ADT: `gfx-kf` = `[0x04D20000 0x20000]`, `[0x04D00000 0x20000]`, IRQs `[260,259,262,261]` |

## Resolved (no longer a GUESS)

| item | value | how it was resolved |
|---|---|---|
| mailbox offset `A + 0x4000` | **`0x04D24000`** (IOP `+0x4000`) | 2026-11-09: A10's identical relative layout (`mbox@201d24000`), the G10P kext RE (FINDINGS §9f: MAILBOX_SET/CLR at `IOP+0x4000` / `+0xc00`), and the ADT's GFX IRQ set `[260,259,262,261]`; in-tree variant `apple,t8010-a7iop-mailbox` |
| `mbox` node location | **`0x04D24000`, size `0x1000`** | as above; the earlier `0x04D208000` guess (base + 0x8000, by analogy with PMP) is **dropped** |

## GUESS — must be zero false flags by probe time

| item | value used | how to verify |
|---|---|---|
| `A` window register stride | `+0x08/+0x10/+0x18/+0x20/+0x28/+0x30/+0x38` | A10 transplant; confirm on the bench or by RE |
| `A` window enable is `+0x38 = 1` | same | same |
| mailbox ready bits / force | `A+0x4000/+0xc00 = 0x1111`, `A+0x4004/+0xc04 = 1`, `= 0x1000`, `A+0x4020 \|= 1` | A10 sequence; if HELLO never comes up these are the first suspects |
| IOP run bit | `W + 0x2048 |= 1` (built from base+offset in the kext) | replace with the PMP-style `ctl_base` write if the ADT exposes a dedicated start register |
| timebase sync | `A + 0x80c` | confirmed as an in-use register at many sites in the G10P kext |
| firmware name on the rootfs | `apple/gfx-t8015.bin` (name is ours) | pick and document |

## Traps (verified 2026-11-09, read-only — see `kb/A11-GPU-G10P-BOOTCHAIN.md`)

* **Never give a D21 node `compatible = "apple,t8010-gpu"`.**  That string is
  in the in-tree PowerVR match table (`pvr_drv.c`), guarded by
  `CONFIG_DRM_POWERVR_APPLE=y` — which the D21 defconfig already sets — and
  the payload's `init` cold-plugs every device modalias at boot.  Such a
  node would load the full driver and boot the firmware by accident.
  `"apple,t8015-gpu"` matches nothing in-tree.
* **The mailbox driver writes at probe** (`apple_mbox_a7iop_hw` masks the
  four IRQs in `regs + 0x00/0x04`), so the `mbox` node belongs to Phase
  2.2, not 2.1.
* The payload refreshes `/usr/lib/modules/<release>` on the phone's NVMe on
  every boot; a GPU boot is therefore not storage-neutral (the kernel image
  itself stays in the RAM payload).

## Notes

* `install.sh` copies the firmware to exactly one place and records the sha256;
  it does nothing else.
* `rollback.sh` removes the module, unbinds the node, and confirms the display
  still comes up over `simplefb`.
* Stage 2 requires the Fender power-request path only
  (`Fender+0x1000 = 0x11`), plus a RGX identity read at `0x04000018`.
