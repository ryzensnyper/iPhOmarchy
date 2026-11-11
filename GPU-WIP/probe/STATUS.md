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

## Phase 2.2 — boot #4 executed: the console works, the fault is still open (2026-11-11)

Tree commit `e9c4c84d0c6e` (driver only: `late_initcall` registration, 2 s
wait, `GFX-STAGE n/6:` line + 1.2 s pause before each step), rebuilt with
EXIT 0: payload `6f595e1b…` (61 096 872 B), kernel `584703e9…`, DTB
`064ce253…` and initramfs `d54f35e2…` unchanged, firmware `bd7b98e2…`
unchanged.

Two upload attempts failed **before any image byte was sent** (the failing
transfer is the 4-byte "image size" control request, before the bulk
transfer starts); PongoOS then ended its session and the phone fell back to
iOS.  **No Linux boot happened.**  A fresh PongoOS session fixed the
upload: attempt 3 succeeded (`RUN_EXIT=0`).

**Boot #4 result:** the phone booted, **the kernel log was visible on the
display for the first time** (the `late_initcall` change works: simpledrm
has registered the framebuffer by then, so the VT console is live), and the
phone reset to iOS again.  The user was not reading the screen at the
moment of the reset, so the `GFX-STAGE` line that names the faulting access
was not captured.  The next attempt must be read off the screen (or
photographed).

Useful consequence: with a live console, a bus stall now also produces the
kernel's own **soft-lockup trace** (~22 s) with the call trace of the
stuck access — on the same screen, before any hardware reset.

## Phase 2.2 — boot #5 executed: the fault is the FIRST GFX access (2026-11-11)

**Boot #5 pinned the fault.**  The user read the last line off a photograph
of the phone's screen:

```
apple-t8015-gfx 4000000.gpu: GFX-STAGE 1/6: mailbox (RTKit) init
```

The driver announces a stage *before* the access it describes and holds it
for three seconds, so that line means: **the very first access to the GFX
block hung the bus** — the mailbox driver writing `IOP+0x4000`
(`0x4d24000`): mask set `0x1111`, mask clear `0x1001`, the A2I/I2A FIFO
enables, then `enable_irq()`.  Nothing else had touched the GFX block
before it: the mailbox driver only *maps* its page at probe.

So the A11's GFX IOP block is **not accessible** while `ps_gfx` is on, even
though the PMGR reports the domain as active (Phase 2.1) and even though
the A10 does the same sequence successfully on a J71b iPad 6.

The likely reason: on the A11 the device **clock/power gates** are PMP
services, not PMGR registers.  The ADT's `arm-io` node says so:

```
function-clock_gate = 30:clkG()
function-power_gate  = 30:pwrG()
```

and the GFX nodes carry gate lists (`sgx`: `clock-gates = [148, 123]`,
`power-gates = [148, 123]`; `gfx-kf`: `clock-gates = [149]`,
`power-gates = [149]`).  Function 30 is the **PMP coprocessor**.  The
payload carries no PMP firmware (`apple/pmp-t8015.bin` is missing; the
D21 firmware recipe has only the touch and Wi-Fi blobs), so
`pmp_t8015_v1.c` fails at probe ("unable to load firmware") and the PMP
never runs — nothing can open those gates.  The display, USB and storage
work because **m1n1 opens their gates** during the boot; the GPU is never
touched by the bootloader, so its gates stay shut.

Open questions: whether the gate IDs are PMGR device IDs (m1n1's reading,
which on this ADT resolves to virtual devices and would do nothing) or
PMP gate numbers; where the PMP firmware lives in the IPSW (the ADT calls
it `t8015pmp`); and what the PMP mailbox protocol for a gate request looks
like.

## Phase 2.2 — boot #6: the payload never handed over (2026-11-11)

Boot #6 ran a diagnostic build that (a) probes the PMGR power-state
register of `ps_gfx` and (b) reads the mailbox's A2I control register
before anything is written, both to tell "the block does not answer" from
"the block answers and the write is what hurts"; it also moved the bring-up
into a delayed work item (so the payload's init starts, brings up the USB
gadget and streams the kernel log to the host before the first GFX
access).

**The phone never left PongoOS**: it sat on a white screen, the USB device
never re-enumerated as the payload's gadget, and the host's log collector
never saw a connection.  The upload itself reported success (`RUN_EXIT=0`).
So this was a hand-over failure, not a GPU fault; the build was not
exercised at all.

## Phase 2.2 — boot #7 executed: the block does not answer a READ (2026-11-11)

Boot #7 used payload `074b84e2…` (the boot #6 build, kernel `357c690c…`),
whose only change from boot #6 was a hardened `/init`: the payload stays in
the initramfs under the `gpu-diag` bootarg and streams `/proc/kmsg` over the
USB network to `172.16.42.2:6666`.

**The channel works, and it settles the question.**  The phone booted, the
gadget came up (`05ac:4144`), 15 966 bytes of kernel log reached the host,
and then the phone reset to iOS (~20 s after the gadget appeared).  The last
two lines are:

```
[   12.767642] apple-t8015-gfx 4000000.gpu: GFX-STAGE 0/7: ps_gfx power state (PMGR read)
[   14.815634] apple-t8015-gfx 4000000.gpu: GFX-STAGE 1/7: mailbox register read (IOP+0x4008)
```

Nothing follows the second line: **the access that faults is a read** of the
mailbox's A2I control register, not a write, and not an interrupt-enable.
The RGX/Fender/IOP window copies, the run bit and RTKit wake were never
reached.  Stage 0's own value never printed — that build's
`of_parse_phandle_with_args(..., NULL, -1, ...)` call failed silently, which
is fixed in the next payload (`of_parse_phandle()` plus an error print on
every bail-out path).

Corroborating lines from the same log:

```
[    0.653008] pmp-t8015-v1 232300000.pmp: Direct firmware load for apple/pmp-t8015.bin failed with error -2
[    0.653090] pmp-t8015-v1 232300000.pmp: unable to load firmware
[    0.653098] pmp-t8015-v1 232300000.pmp: probe with driver pmp-t8015-v1 failed with error -2
[   11.231913] apple-pmgr-pwrstate 232000000.power-management:power-controller@80310: sync_state() pending due to 232300000.pmp
[   11.232038] apple-pmgr-pwrstate 232000000.power-management:power-controller@80308: sync_state() pending due to 232300000.pmp
```

`@80308` / `@80310` are `ps_pmp` / `ps_pms_sram`: they stay powered only
because no driver ever claimed the PMP device.  The PMP coprocessor has
never run in any of our boots.

### What the same tree says about the gates

* No driver in this kernel consumes `clock-gates` / `power-gates` (they are
  ADT properties; `grep` over `drivers/` and `include/` finds nothing).
* The GPU node has no `clocks` property, `t8015.dtsi` has no clock
  controller, and `drivers/clk/` has only the NCO and the T8010 touch clock
  (the touch one sets a PLL divider, not a device gate).
* The PMGR power-state binding can expose a state register as a clock gate,
  so a gate that *is* a PMGR register would show up as a DT node; the only
  one near the GPU is `ps_gfx@0x80338` itself, which the genpd reports as
  `actual 0xf`.
* m1n1 only writes PMGR power states (`pmgr_adt_power_enable()`), and the
  payload's m1n1 does not call it for the GPU — the orchard patch only fills
  the OPP table.  Even if it did, the ADT's gate lists resolve to devices
  the ADT marks as having no power-state register.

So the IOP's clock is gated by something the kernel has no handle on, which
is consistent with the ADT calling the gates PMP services (`30:clkG()` /
`30:pwrG()`).

### Where the PMP firmware is

Not in the IPSW as a file — that part of the earlier hunt was right:

* top-level `Firmware/`: AOP, SEP, baseband, touch (Callan/Multitouch),
  DeviceTree/LLB/iBoot, Wi-Fi — no PMP;
* the system volume's `/usr/standalone/firmware/`: `SLAM/`,
  `SmartIOFirmwareT7000.bin`, `nfrestore/` — no PMP.

But iOS does not fetch it from the firmware store either: it is **embedded in
the kernelcache**, as the payload of the `AppleT8015PMPFirmware` kext, `0xff0`
bytes after the kext's tag string (the same layout as `AppleT8015SmartIO`).
The image is not IMG4-wrapped, which is why the `IM4P`/`pmpf` scan missed it;
it starts with an AArch64 exception vector table (`b #0x60`, then `b .`
entries) and ends right before the next `com.apple.driver.` tag:

```
image:  126608 bytes at 0x2c6c000..0x2c8ae90
sha256: 2dcf73b5e13fe9c3f93731c7ef09de8e6244de9f610c34fff2981af90010cd52
head:   180000ea feffffea feffffea …
```

The length rule is the one calibrated on the SmartIO image (which reproduces
the device's file byte-for-byte): the payload ends `0x280` bytes before the
next prelinked bundle id — here `com.apple.iokit.IOUserEthernet` at
`0x2c8b110`.  A naive "next `com.apple.driver.` tag" search lands on
`AppleUSBAudio` at `0x2c8b2d0` and overshoots by 1088 bytes of the next
kext's prelink header; that was the 127 696-byte first cut.

It is the PMP image, not just the kext: it carries `RTKit-2062.142.1.release`,
`RTKit: %s - Client: %s`, `pm_enqueue_message failed status %u`,
`Invalid AP power: %d`, `Mbox:%s (h=%p %x=%x)` and `ThIntr:%u,%u,%u,%u`, and
its 126 608 bytes fit the PMP's `0x20000`-byte SRAM window (`reg-names =
"akf", "control", "sram"`).

**The D21 and D22 kernelcaches carry the identical image** (same offset, same
hash), so the D21 build is the one to use.  `tools/kc_pmp_extract.py` writes
it out, and `probe/phase2.2/install-pmp-firmware.sh` puts it into the payload
overlay as `/lib/firmware/apple/pmp-t8015.bin`.

### Capture channel (keep it)

Host: `python3 GPU-WIP/tools/kmsg-host.py 6666 /tmp/phone-kmsg.log`, with the
host's USB NIC on `172.16.42.2/30` (NetworkManager profile `phone-gadget`).
Payload: the `gpu-diag` bootarg makes `/init` stay in the initramfs and, in
the background, retry `busybox nc -w 3 172.16.42.2 6666` fed from
`/proc/kmsg` (falling back to `dmesg` if the log is not readable).  A payload
boot is only real when the phone re-enumerates as `05ac:4144`; `RUN_EXIT=0`
alone proves nothing.

### Next probe (payload `b9151d1a…`, built, NOT booted — needs a go)

With the PMP firmware available, the next boot tests the gate theory directly
instead of guessing at registers:

* the PMP driver now has a **diagnostic boot**: under the `gpu-diag` bootarg
  it defers its bring-up to a work item at 14 s, so the payload's init has
  brought the log bridge up first, and prints `PMP-DIAG 0/4: firmware copy to
  SRAM` … `4/4: RTKit wake (waiting for HELLO)` with a second's hold each.
  Without the bootarg the driver behaves exactly as before (boot in probe).
* the GFX diagnostic work moves from 12 s to 20 s, so the PMP boots first.
* the first GFX probes are unchanged: the PMGR `0x80300` power-state bank
  dump (`ps_msr`, `ps_pmp`, `ps_pms_sram`, `ps_pcie`, `ps_ans2`, `ps_gfx`,
  `ps_isp_sys`, …; the decode is trustworthy because `ps_ans2` in the same
  bank is what the NVMe driver successfully powers), then the RGX core id /
  revision at `0x4000000+0x18` / `+0x20`, then the mailbox A2I read.

Read-outs, in order of what they would settle:

| log says | conclusion |
|---|---|
| silence after `PMP-DIAG 0/4` | the PMP block is dark too — the whole "PMP does the gating" chain is unproven, and the gate problem is not just missing firmware |
| `PMP is up` then mailbox read hangs | the PMP runs but does not open the GPU gates on its own → the AP has to send the gate request (RE the AppleT8015PMPFirmware ↔ AppleA7IOP protocol) |
| `PMP is up`, RGX core id printed, mailbox read still hangs | the GPU domain is alive but the IOP sub-block is gated on its own |
| `PMP is up` and the mailbox answers | the PMP *is* the gate owner: continue with RTKit HELLO (Phase 2.2 proper) |



| item | state |
|---|---|
| `getRuntimeBinSize = 0x8f000` | verified (LAYOUT KB §1) |
| `Fender+0x1000 = state\|0x10`, poll bit 4 | verified in kext at `0x2600` |
| Fender dummy-read window block at `+0x200c..+0x2020` | verified at kext `0x42d14..0x42d28` |
| `g10p.img` is the GFX firmware | verified (ARM32, "G10 Firmware initializing", tasks `agx_background`…`agx_sampler`) |
| GPU does not hang off a DART | verified — `sgx` has no `iommu-parent` |
| GFX IOP node / addresses | taken from the ADT: `gfx-kf` = `[0x04D20000 0x20000]`, `[0x04D00000 0x20000]`, IRQs `[260,259,262,261]` |

## Phase 2.2 — boot #8 executed: the PMP runs, the GPU block is still dark (2026-11-11)

Payload `b9151d1a…` (kernel `00b70cc7…`): the PMP firmware installed, the PMP
bring-up deferred to 14 s with staged prints, and the GFX work moved to 20 s.
The log came off the phone again (17 713 bytes) and then the phone reset.

**The PMP access works.**  Every stage printed, and RTKit came up on the
mailbox:

```
[   14.815633] pmp-t8015-v1 232300000.pmp: PMP-DIAG 0/4: firmware copy to SRAM
[   15.843159] pmp-t8015-v1 232300000.pmp: PMP-DIAG 1/4: AKF remap (SRAM at 0x0)
[   16.863660] pmp-t8015-v1 232300000.pmp: PMP-DIAG 2/4: start (control = 1)
[   17.887668] pmp-t8015-v1 232300000.pmp: PMP-DIAG 3/4: RTKit init
[   18.911961] pmp-t8015-v1 232300000.pmp: PMP-DIAG 4/4: RTKit wake (waiting for HELLO)
[   18.911989] pmp-t8015-v1 232300000.pmp: RTKit: Initializing (protocol version 12)
[   20.959635] pmp-t8015-v1 232300000.pmp: error -ETIME: Failed to wake PMP
```

So the SRAM copy, the AKF remap, the `control = 1` start and the mailbox
writes all complete — the PMP block is **not** dark, unlike the GPU.  What
fails is the handshake: no HELLO within the wake timeout.  (It also means the
PMP firmware's own code has not yet executed anything we can see, or it runs
but never answers the AP's first message.)

**The GPU block is dark as a whole, not just the IOP.**  Stage 1/8 read the
RGX core id at `0x4000000+0x18` — the log ends there and the phone reset, so
the RGX core hangs exactly like the mailbox did.  Same conclusion as boot #7,
now for the entire GPU address space.

**The PMGR `0x80300` bank, measured for the first time** (after `ps_gfx`
was powered):

```
@0x80300 = 0x0f000300  auto 0, was clk 1, was pwr 1, actual 0x0, target 0x0
@0x80308 = 0x1f0f00ff  auto 1,                 actual 0xf, target 0xf   ps_pmp
@0x80310 = 0x1f0003ff  auto 1, was clk 1, was pwr 1, actual 0xf, target 0xf   ps_pms_sram
@0x80318 = 0x1400024f  auto 1, was clk 1,       actual 0x4, target 0xf   (clock-gated, target active)
@0x80320 = 0x000000ff  auto 0,                 actual 0xf, target 0xf
@0x80328 = 0x1000030f  auto 1, was clk 1, was pwr 1, actual 0x0, target 0xf   (stuck off)
@0x80330 = 0x1400024f  auto 1, was clk 1,       actual 0x4, target 0xf
@0x80338 = 0x1f0003ff  auto 1, was clk 1, was pwr 1, actual 0xf, target 0xf   ps_gfx
@0x80350 = 0x00000300  auto 0, was clk 1, was pwr 1, actual 0x0, target 0x0
@0x80388 = 0x0f000300 … 0x80398 = 0x0f000300 … 0x803a8 = 0x0f000300   (all off)
```

`ps_gfx` is genuinely ACTIVE (target 0xf, actual 0xf) — and the `WAS_PWRGATED`
/ `WAS_CLKGATED` bits say it came out of both gates to get there.  Yet its
registers hang.  Two candidate explanations remain, and they need different
fixes:

1. **the gate is not the PS register.**  The ADT calls the device gates PMP
   services (`30:clkG()` / `30:pwrG()`), and the PMP's gate requests go over
   the "dock FIFO" / RTKit management messages, not over PMGR writes.  The
   PMP is now running, but our driver never sends a gate request — and it is
   not even at HELLO yet.
2. **the block's clock source is not configured.**  The ADT gives `sgx`
   `clock-ids = [265]` and the PMGR clock table has a `GFX` entry
   (`perf_idx 44`); nothing in Linux configures an A11 PMGR clock source for
   the GPU (the only such driver, `clk-apple-t8010-touch.c`, is touch-only
   and its register comes from the DT).

Both are testable offline before the next boot: (1) by reading
`AppleT8015PMPFirmware`'s own gate-request code out of the kernelcache — the
kext is the AP side of the protocol and is present (`pmp-clock-gating`,
`pmp-power-gating`, `pmp-dart`, `dock`-era PMGR properties in the ADT);
(2) by finding the GFX clock source register in the ADT's PMGR block and
comparing it with the touch clock's register layout.

The `-ETIME` HELLO also wants an answer first: m1n1's RTKit boot
(`src/rtkit.c`) is the only reference implementation we can read that
actually starts an A11-era IOP; compare its boot message/`AP power` handling
with `apple_rtkit_wake()`.

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
