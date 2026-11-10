# Probe — status and known-unverified items

**Scope of the probe: Stage 1 only** (RTKit HELLO from the GFX IOP).
Stage 2 (Fender + CORE_ID) and Phase 2 (init data, jobs) are not part of this.

## Phase 2.1 — PASSED on hardware (2026-11-09)

Booted the Phase 2.1 kernel (tree `5744368dec2c`, payload `1f790b08…`) on
D21: `pm_genpd/gfx/current_state` = **`on`**, `devices` = `4000000.gpu`,
device bound to `apple-t8015-gfx` with the `ps_gfx` controller as its
supplier, dmesg marker at 0.65 s, `powervr` not loaded, fb0/touch/NVMe
unchanged, domain still on at 101 s.  Evidence in `phase2.1/README.md`.

Benign boot noise: a late coldplug attempt logged
`apple_z2: version magic '7.3.0-rc1-g0c549fd6bed0' … should be
'7.3.0-rc1-orchard-apple-16k'`.  The touch module was already loaded and
working (`event1`, IRQ 71 firing); every `apple_z2.ko` on disk has the
correct vermagic.  Likely a stale artifact from the previous module tree;
recheck on the next boot.

## Phase 2.2 — boot #2 executed, resource conflict fixed (2026-11-10)

Patch `d616c1dbc383` + firmware `bd7b98e2…` went into payload `4987f034…`
(kernel, DTB and initramfs verified; build EXIT 0).  Boot #2 reached
userspace in ~15 s, but the GPU driver unwound **before any register
write**:

    apple-t8015-gfx 4000000.gpu: error -EBUSY: can't request region for resource [mem 0x04d20000-0x04d3ffff]

The `iop` window overlaps the mailbox page (`0x4d24000`), which the mailbox
device had already claimed; `devm_platform_ioremap_resource_byname()`
requests the whole region.  Fix (`485453dd66d9`): map only the first 4 KiB
with `devm_ioremap()`; the window registers are at `+0x08..+0x38`.  Same
latent bug in `pvr_apple.c`.  No crashlog, no oops; display/touch/NVMe
unaffected.  Rebuilt 2026-11-10 with the fix (payload `a0bbc549…`, kernel
`15ade92a…`, DTB/firmware unchanged, receipt verified, EXIT 0).  Boot #3
(the retry) is ready and waiting on Pongo.  Kit: `phase2.2/`.

## Phase 2.2 — boot #3 executed: hard reset, no output (2026-11-10/11)

Boot #3 ran the retry payload `a0bbc549…` (kernel `15ade92a…`).  The upload
succeeded (`RUN_EXIT=0`), the phone **reset to iOS within a second or two and
showed no text at all**.

**Why there was no text (the real trap).**  The driver probes at
`device_initcall`, and in `drivers/Makefile` `soc/` (line 46) is linked
**before** `gpu/` (line 68) — so `apple-t8015-gfx` probes *before*
`simpledrm` (also `device_initcall`, `drivers/gpu/drm/sysfb/simpledrm.c`)
has registered the framebuffer.  At 0.65 s no framebuffer exists, the VT
console cannot show anything, and every `dev_info()` of the driver is
thrown away.  A fault in the first GFX access is therefore *invisible* on
this platform unless the driver probes after `simpledrm`.

**What is now known.**  Boot #3 is the first boot that touched **any** GFX
register: in boot #2 the mailbox driver only *mapped* its page
(`apple_mbox_probe()` writes nothing; the mask/FIFO-enable writes happen in
`apple_mbox_start()`, which runs when RTKit starts).  So the order of the
first-ever GFX accesses is:

| # | access | where |
|---|---|---|
| 1 | mailbox mask `0x1111` → `IOP+0x4000`, mask clear `0x1001` → `+0x4004`, FIFO enables → `+0x4008`/`+0x4020`, `enable_irq` | `apple_mbox_start()` inside `devm_apple_rtkit_init()` |
| 2 | Fender window `+0x200c..+0x2020` (6 words) | `apple_t8015_gfx_set_window()` |
| 3 | IOP window `+0x08..+0x30` (6 words) | `apple_t8015_gfx_set_window()` |
| 4 | IOP window enable `+0x38 = 1` | `apple_t8015_gfx_set_window()` |
| 5 | run bit `Fender+0x2048` RMW bit 0 | `apple_t8015_gfx_probe()` |
| 6 | `apple_rtkit_wake()` (mailbox message, cannot reset) | `apple_t8015_gfx_probe()` |

**Boot #4 (diagnostic, next):** the driver registers at `late_initcall`
(after `simpledrm`), waits 2 s, and prints a `GFX-STAGE n/6:` line with a
1.2 s pause before each of the six steps.  The register sequence itself is
**unchanged** — only the initcall level, the delays and the log lines.
The last `GFX-STAGE` line on the phone's screen names the access that
stalled the bus.  Expected on screen: `GFX-DIAG: first IOP access in 2 s`,
then `GFX-STAGE 1/6: mailbox (RTKit) init` … `GFX-STAGE 6/6: RTKit wake`.

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
* **The IOP window overlaps the mailbox page** (`0x4d24000..0x4d24fff` sits
  inside `0x4d20000..0x4d3ffff`), and the mailbox device claims its page at
  probe.  Any GPU driver that maps `"iop"` with
  `devm_platform_ioremap_resource_byname()` fails `-EBUSY` before booting
  the firmware.  Use `devm_ioremap()` (no region claim) for the window
  page; found on boot #2 (2026-11-10).  `pvr_apple.c` still has the bug.
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
