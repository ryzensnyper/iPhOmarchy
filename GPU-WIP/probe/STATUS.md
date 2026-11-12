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

## Offline (2026-11-12): boot #8 re-read, the ADT power model, and the boot #9 plan

No phone was needed for any of this; it is all kernelcache/ADT/firmware
reading.  Three results change what boot #9 has to do.

### 1. Boot #8 did get HELLO — and the `-ETIME` is the AP's own power message

`RTKit: Initializing (protocol version 12)` is printed by
`apple_rtkit_management_rx_hello()`, i.e. **only after the IOP sent HELLO**
(`drivers/soc/apple/rtkit.c`).  The PMP therefore negotiated RTKit v12 with us.

The timing settles which wait failed.  HELLO at `18.911989`, error at
`20.959635` = **+2.048 s**, and mainline's waits are 1000 ms each
(`apple_rtkit_wait_for_completion()`):

| step | mainline `apple_rtkit_boot()` | boot #8 |
|---|---|---|
| 1 | wait `epmap_completion` | completed (~1 s, the PMP is slow) |
| 2 | wait `iop_pwr_ack_completion` | **timed out** → `-ETIME` |
| 3 | send `SET_AP_PWR_STATE(ON)` | **never sent** |

m1n1 does the same sequence (`src/rtkit.c`) but waits for the IOP power ON
**without any timeout at all** — so the PMP is not broken, it is slow, and the
1 s is a mainline limitation for this coprocessor.  The knock-on effect is
what matters for the GPU: because `boot()` aborted, the AP never declared
itself powered on, and the PMP firmware *validates that message*
(`Invalid AP power: %d` is a string in its image).  An AP that never said "I
am on" cannot expect gate services.

### 2. The GPU's gates have no PMGR register — the PMP owns them

Decoded from the ADT with m1n1's own parser (`proxyclient/m1n1/adt.py`,
`load_adt()` on `adt/dt_raw.bin`; the decoded `adt.txt` is incomplete — it
drops `perf-regs` entirely):

* `pmgr/ps-regs[11]` = `{reg, offset, mask}`; a device's PS register is
  `ps_regs[psreg].offset + psidx*8` (m1n1 `pmgr_dev_get_offset()`), reg[0]
  being PMGR and reg[1] `pmgr_mini` @ `0x235200000`.
* The `0x80300` bank is now fully named — **`0x80338` really is `GFX`**:
  `0x80300` MSR · `0x80308` PMP · `0x80310` PMS_SRAM · `0x80318` PCIE ·
  `0x80320` PCIE_AUX · `0x80328` ANS2 · `0x80330` PCIE_DIRECT ·
  **`0x80338` GFX** · `0x80388` VDEC0 · `0x80398` VENC_SYS · `0x803a8` AVD_SYS.
* `GFX` (id 124) has **no parents**: it is a root domain like PMP/SEP/PCIE,
  so nothing is holding it down from above.
* The devices the `sgx` node gates (`power-gates`/`clock-gates` = `[148, 123]`,
  and `gfx-kf`'s `[149]`) are `GFX-SGX`, `GFX-BUSY` and `GFX-KF` — all three
  are `no_ps` (`PMGR_FLAG_VIRTUAL` in m1n1, which skips them) and their only
  parent is `GFX`.  **No PMGR write can open them.**  They are logical gates
  that only the PMP can act on.
* The evidence that the PMP is meant to act on them:
  `pmgr` carries `pmp = 1`, `pmgr-dock-fifo-agent = 1`,
  `pmgr-dock-fifo-channel = 3` — the PMGR *is* an agent of the PMP's dock
  FIFO, i.e. a PS transition is the hardware's way of telling the PMP about a
  device.  `sgx` also has `pmp-sw-interrupt = 1`.
* `pmgr/perf-regs` (in the raw ADT only) = 3 DVFS blocks
  `{reg, offset, size}`: block 0 = PMGR+`0xb4000` (140 entries), block 1 =
  `pmgr_mini`+`0xb4000` (32), block 2 = PMGR+`0xfc000` (10).
  `pmgr/power-domains` (21 entries) is the DVFS domain list, and **GFX is
  `perf_block 0, perf_idx 0x2c`** → `0x2320b4100 + 0x2c0 = 0x2320b43c0`
  (m1n1's `dump_pmgr.py` computes `base + 0x100 + idx*0x10` without the perf
  offset, which gives `0x2320003c0`; the two disagree, so boot #9 dumps both).
* `clock-ids = [265]` (`sgx`) / `[269]` (`gfx-kf`) index **nothing** in this
  ADT: `/arm-io` has `clock-frequencies` (81 zeros) and **no
  `clock-frequencies-regs`**, and the `pmgr` clock tables stop at id 21.  The
  "unconfigured clock source" candidate is therefore not actionable as a
  register lookup; the perf block above is what can be read.

### 3. PMP firmware internals (for the gate protocol later)

* It is a **raw 32-bit ARM image** (vector table, `b #0x60` entry), not a
  Mach-O.  Physical load base is `0x232500000` (`iop-pmp-nub`
  `region-base`), but it is **linked at `0x01000000`** — an MMU maps that VA
  onto the SRAM.  String xrefs only resolve with base `0x01000000`, so
  disassemble with `llvm-objdump -d --triple=thumbv7` on an ELF wrapped by
  `llvm-objcopy -I binary` (A32 for the vector table, **Thumb-2** for the
  body).
* It is a full RTKit client: `RTKit-2062.142.1.release`,
  `MGMT msg=0x%llx st=%x`, `Not implemented`, `Invalid AP power: %d`, and the
  system endpoints `management/crashlog/syslog/kdebug/ioreporting/main`
  plus `PMON`/`pmon-hid-report`.
* At file `0x17c68` sits a tunable table of 12-byte `{size, default,
  reversed-4CC name}` entries: `DBUG`=`0xaff`, `DART`, **`DOCK`=`1`**,
  **`PWRG`=`0`**, **`CLKG`=`1`**, `NRGD`=`1`, `NRGS`=`1`, `PMON`=`1`,
  `PMUT`=`1`, `SMPL`=`0`, `TCAP`=`0`, `TGPH`=`0x3e8`, `BDID`, `PBAT`, …
  So the dock and clock-gating features are **enabled by default in the
  firmware**; they are not waiting on a DT property.

### Boot #9 (built, not booted — needs a go)

One change of substance plus read-only reconnaissance:

* `rtkit.c`: the wait timeout goes 1 s → 15 s (diagnostic; m1n1 has no
  timeout), and the HELLO/EPMAP/IOP-ACK/AP-ACK transitions now print at
  `KERN_INFO` so the handshake is visible line by line.
* `pmp_t8015_v1.c`: bring-up at 12 s; after `apple_rtkit_wake()` it polls
  `apple_rtkit_is_running()` for up to 25 s, and if the AP power message was
  never sent (because `boot()` aborted) it sends `SET_AP_PWR_STATE(ON)` by
  hand (type `0xb` in bits 59:52, `0x20` in bits 15:0).  It exports
  `apple_t8015_pmp_up`.
* `apple-t8015-gfx.c`: waits (up to 40 s) for `apple_t8015_pmp_up` before
  touching the GPU; dumps the PS bank and **both** DVFS/perf candidate blocks
  (read-only); then **re-toggles `ps_gfx` off→on** so the PMGR re-sends the
  gate request with the PMP up (skipping the GPU accesses entirely if the
  domain does not come back); then the mailbox read, the RTKit bring-up, and
  the RGX read last.

Interpretation table:

| what the log shows | conclusion |
|---|---|
| `IOP power state transition: 0x0 -> 0x220` then `-> 0x20`, then `PMP is up` | the PMP only needed time; the AP is now declared ON |
| mailbox `A2I control` prints a value | the fender/IOP sub-block is clocked — the gate question is answered for the IOP |
| mailbox read hangs after the PMP is up | the PMP being up is not sufficient; the gate request itself has to be sent |
| `GFX firmware is up; RTKit handshake complete` | **Phase 2.2 passes** |
| `rgx: core id …` | Phase 2.3's identity read, for free |
| `retoggle: ps_gfx stuck at actual …` | the PMGR handed the domain to the PMP (dock agent) and the PMP did not take it back |

## Phase 2.2 — boot #9 executed: the PMP is now a running RTKit peer (2026-11-12)

Payload `cf9a5dd7…` was **not** the one booted; boot #9 ran the first build of
this round and the kit was rebuilt after it (see "Boot #10" below).  The log
came off the phone again (the collector file holds boot #8's and boot #9's
sections; boot #9 is the second one).

### What worked: the whole handshake, in one millisecond

```
[   12.767685] pmp-t8015-v1 …: PMP-DIAG 0/4: firmware copy to SRAM
[   13.795236] pmp-t8015-v1 …: PMP-DIAG 1/4: AKF remap (SRAM at 0x0)
[   14.815691] pmp-t8015-v1 …: PMP-DIAG 2/4: start (control = 1)
[   15.839697] pmp-t8015-v1 …: PMP-DIAG 3/4: RTKit init
[   16.864062] pmp-t8015-v1 …: PMP-DIAG 4/4: RTKit wake (waiting for HELLO)
[   16.864077] pmp-t8015-v1 …: RTKit: Initializing (protocol version 12)
[   16.864177] pmp-t8015-v1 …: RTKit: received endpoint bitmap 0x1f with base 0x0
[   16.864254] pmp-t8015-v1 …: RTKit: received endpoint bitmap 0x1 with base 0x1 (last)
[   16.864920] pmp-t8015-v1 …: RTKit: IOP power state transition: 0x0 -> 0x20
[   33.247679] pmp-t8015-v1 …: RTKit wake returned -62 (continuing)
[   35.767680] pmp-t8015-v1 …: PMP-DIAG: forcing SET_AP_PWR_STATE(ON)
[   35.767985] pmp-t8015-v1 …: RTKit: AP power state transition: 0x0 -> 0x20
[   36.271675] pmp-t8015-v1 …: PMP is up (AP power state ON, RTKit peer running)
```

So within **one millisecond** of the wake message the PMP sent HELLO, both
EPMAP chunks (`0x1f` → management/crashlog/syslog/debug/ioreport, plus
endpoint 32 — its first *application* endpoint, which is why `0x1` with base 1
arrives) and the IOP power ACK (`0x20` = ON).

The persistent `-62` has nothing to do with HELLO: mainline's boot path, after
the two waits, *sends* `SET_AP_PWR_STATE(ON)` and waits for **that** ACK too
(`ap_pwr_ack_completion`), and the PMP does not answer the first one.  Our
poll forced the same message again 2.5 s later and the PMP acked it in
**0.3 ms**.  That is exactly the retry m1n1 gets for free by looping forever
(`rtkit_switch_power_state()`), and it is why the AP power message is what
boot #8 never sent.

The AP now has a **fully booted PMP** (IOP ON + AP ON), i.e. the precondition
for a gate request exists.

### The `ps_gfx` bank did not change just because the PMP came up

Read again at 38.7 s, with the PMP fully booted, the bank is byte-identical to
boot #8's read (before the PMP was up): `@0x80338 = 0x1f0003ff`, actual 0xf,
target 0xf, was-clk-gated, was-pwr-gated.  Nothing in the PMGR reflects the
PMP's state, as expected for a gate that the PMP owns itself.

### What still failed — and it is our bug

The DVFS dump (stage 2) faulted:

```
[   40.735705] Unable to handle kernel paging request at virtual address ffff800081fb4350
[   40.745469]   ESR = 0x96000007 … FSC = 0x7: level 3 translation fault
[   40.784194] pc : apple_t8015_gfx_boot_work+0x3b8/0x8e8
[   40.786645] lr : apple_t8015_gfx_boot_work+0x194/0x8e8
```

`0x2320b4350` — the *high* perf candidate, `PMGR_DVFS_HIGH + 0x25*0x10`.  The
**DT maps the pmgr node as `0x8c000`** (the A10's size), not the 16 MiB the ADT
describes, so `of_iomap()` produced a window that ends at `+0x8bfff`; the
`+0xb4xxx` read was outside it.  The oops killed the GFX work item, so the
retoggle, the mailbox read and the RTKit bring-up never ran — the phone stayed
up in the payload (`mode: ram`).  Lesson recorded: no read outside the
DT-declared window, and a nice-to-have dump must not sit in front of the one
test the boot exists for.

### Boot #10 (built, NOT booted — needs a go)

Payload **`cf9a5dd7e28604e9…`** (kernel tree rebuilt; 2 files changed):

* `apple-t8015-gfx.c`: `apple_t8015_gfx_map_pmgr()` now takes the pmgr
  resource and `ioremap()`s **1 MiB** (ps banks to `+0x88000`, clock at
  `+0x78000`, perf block to `+0xb4d00`), instead of `of_iomap()`'s DT-sized
  window.
* The DVFS read is split: the **low** window (`+0x100`, inside the declared
  PMGR window, next to the safe PS banks) runs before the GPU test; the
  **high** window (`+0xb4100`) runs **last**, after the RGX read, so it can
  never again cost the test.
* Stage numbering is now `0/11 … 11/11`.

Everything else is boot #9's build, whose PMP half is proven: bring-up at
12 s, poll + forced `SET_AP_PWR_STATE(ON)`, and the GFX side waiting for
`apple_t8015_pmp_up` before it touches the block (PMP reported up at 36.6 s,
the wait cost 11.5 s and returned immediately).

## Phase 2.2 — boot #10 executed: the block is still dark with the PMP up (2026-11-12)

Payload `cf9a5dd7…`.  The log came off the phone (75 lines for this boot, no
oops, no panic) and the phone went back to iOS by itself: the boot died on
**stage `4/11`, the mailbox read at `IOP+0x4008`** — a bus hang and a watchdog
reset, exactly as in boots #7/#8.

Everything that could be satisfied before that read was satisfied:

```
[   36.271641] pmp-t8015-v1 …: PMP is up (AP power state ON, RTKit peer running)
[   36.647638] apple-t8015-gfx …: GFX-DIAG: PMP is up after 11500 ms
[   38.687717] apple-t8015-gfx …: ps_gfx: PS @0x80338 = 0x1f0003ff (auto 1, was clkgated 1, was pwrgated 1, actual 0xf, target 0xf)
[   42.911731] apple-t8015-gfx …: retoggle: before = 0x1f0003ff
[   42.945608] apple-t8015-gfx …: retoggle: after  = 0x0f0003ff (auto 0, clk 1, pwr 1, actual 0xf, target 0xf, 10 ms)
[   42.949177] apple-t8015-gfx …: GFX-STAGE 4/11: mailbox register read (IOP+0x4008)
```

Three conclusions, all of them new:

1. **The PMP being a running RTKit peer with AP power ON changes nothing.**
   The PMGR does not open the GPU's gates on its own initiative when the PMP
   arrives.
2. **A PS transition does not open them either.**  The `ps_gfx` off→on went
   through completely (power-gate then re-power, `actual` back to `0xf` in
   10 ms, `AUTO` cleared) and the PMGR still lets Linux move that domain —
   so the "dock fifo agent" hand-off is not what makes the block dark.  The
   AP has to *ask*, explicitly.
3. **The DVFS "low" window is not the perf block.**  `PMGR+0x100+idx*0x10`
   reads `0` for *every* entry we sampled, including `MCC`/`DCS01` — DRAM
   domains that must be configured on a live system.  So the perf registers
   are the `+0xb4xxx` window (never reached: it is read last now), and
   `dump_pmgr.py`'s `base + 0x100 + idx*0x10` formula is wrong for this SoC.

The one read we lost to the reordering is the `+0xb4xxx` window; it stays last
on purpose, but it is no longer interesting next to the gate question.

## Next: the gate request itself (offline, no boot)

The mailbox read is the *first* access to the block, so it is now a clean test
of any future gate mechanism: if a gate request works, that read returns.  The
open item is therefore how iOS asks for those three virtual gates
(`GFX-SGX` 148 / `GFX-BUSY` 123 / `GFX-KF` 149, all `no_ps`, parent `GFX`).

Known anchors to attack it with:

* the PMP firmware **services** the request, so its dock/FIFO handler carries
  the register base and the message format; its tunable table (file `0x17c68`)
  has `DOCK` and `CLKG` enabled by default, and it is Thumb-2 linked at
  `0x01000000`;
* the AP side is `ApplePMPFirmware` (+ `AppleT8015PMPFirmware`) in the kernel
  cache, with the feature switches `pmp-clock-gating`, `pmp-power-gating`,
  `pmp-dock-fifo`, `pmp-test`, `pmp-dart`, `light-em-up`;
* the PMP's "control" region (`0x232400000`, 64 KiB) is mapped by the driver
  as `control` and is **never touched** — the prime suspect for a doorbell;
* the first application endpoint the PMP advertises is **endpoint 32**
  (EPMAP `0x1` with base 1), i.e. there is an app-level service to send to.

## Offline (2026-11-12, after boot #10): the gate request is a PMP *function call*

The mechanism behind the three registerless GPU gates is identified; the
write-up with every address is in **`phase2.2/PMP-FUNCTION-CALL.md`**.  The
short version:

* The ADT's `function-*` properties (`function-clock_gate = 30:clkG()`,
  `function-power_gate = 30:pwrG()`, `function-pmp_control = 63:PMPC()`,
  `function-mcc_ctrl = 37:Mem$()`, `function-clock_enable = 30:TCLK(...)`)
  mean a device calls a **named function**, not a register.
* On iOS those calls go to the PMP: `ApplePMGR` has
  `ApplePMGRFunctionPMPInterrupt::_callFunctionPMPv2()` and `_provider->_pmpV2()`,
  and the client kext is **`com.apple.driver.ApplePMP`**
  (`ApplePMPv2`/`ApplePMPThermal`) matching RTBuddy endpoint services
  **`PMPEndpoint1`**/**`PMPEndpoint2`**; there is a private entitlement
  `com.apple.private.pmp.performance-spi`.
* `PMPEndpoint1` is the PMP's **endpoint 32** — exactly the first application
  endpoint our EPMAP already showed in boots #9/#10.
* The firmware side is a **clock-gate command handler at VA 0x0100e920**
  (firmware linked at 0x01000000, Thumb-2) reached through a function-pointer
  table at `~0x010119c4`; it decodes one 32-bit word with an **8-bit device
  index in bits 12..19** (the ADT device ids fit), a 12-bit value, a 2-bit
  mode and a direction bit, and prints `!clg: %08x` on error.
* The PMP's own PMGR descriptor is `base 0x32000000, size 0xd8000`, which
  contains the perf block at `+0xb4000` (so the D21 DT's `0x8c000` PMGR
  mapping is simply too small — that was boot #10's fault).

Boot #11 therefore has something concrete to send to endpoint 32, and the
firmware's `!clg:`/`Not implemented` syslog prints should show up in the Linux
log as `RTKit: syslog message: ...`, so one boot can both ask and read the
answer — with the IOP mailbox read kept for last.

## Phase 2.2 — boot #11 executed: calls accepted, block still dark (2026-11-12)

Payload `19d57c0c…`.  Sequence as designed: PMP up (11.5 s after the GFX work
started, AP `SET_AP_PWR_STATE(ON)` acked), `ps_gfx` `0x1f0003ff`, DVFS/perf
windows, six candidate messages to endpoint 32, `ps_gfx` retoggle, mailbox
read.

| stage | result |
|---|---|
| `ps_gfx` @`0x80338` | `0x1f0003ff` — auto 1, was-clkgated 1, was-pwrgated 1, actual `0xf`, target `0xf` |
| DVFS low (`+0x100+idx*0x10`) and high (`+0xb4000+idx*0x10`) | **every** known index reads `0` (MCC, DCS01, ACS, DISP0_GP, PMP, PMS_SRAM, GFX, SEP, ANS2, MSR, PCIE, …) |
| six `pmp-call` messages to ep 32 | all accepted (`-> 0`), **no `RTKit: syslog message` reaction** |
| retoggle `0x1f0003ff` → `0x0f0003ff` | actual `0xf` within 10 ms (PMGR still owns the domain) |
| **stage 5/12 mailbox read `IOP+0x4008`** | **hung the bus → reset → iOS** |

Conclusions: neither DVFS window is the GFX perf array *as seen from the AP*
(all-zero, including DRAM domains that must be configured — either the block
is write-only/AP-invisible or the offsets are wrong); the six candidate gate
messages are accepted by the mailbox layer but the firmware does nothing
visible; and the GPU block is still dark.

Two things were then found offline that change the plan (below): the messages
were sent to an application endpoint that was **never started**, and the GPU
has **its own PMGR block that Linux never maps**.

## Offline (2026-11-12, after boot #11): the GPU's own PMGR block — bridge 8 = `0x05000000`

Detail and every address: **`phase2.2/PMGR-BRIDGES.md`**.  Short version:

* The ADT `pmgr` node carries `#bridges = 13`, `bridge-reg-index = 19`,
  `optional-bridge-mask = 0x800` and `bridge-counters` (13 entries).
* `bridge-reg-index = 19` means **bridge *b* is `pmgr` `reg[19 + b]`**.  Proof:
  the bridge windows happen to coincide with three subsystem bases —
  ISP (device group 5) → `reg[24] = 0x0F000000` = the `isp` node's base,
  AVD (9) → `reg[28] = 0x28000000` = the `avd` base,
  VENC/"ave" (3) → `reg[22] = 0x23000000` = the `ave` base.
* The device-group id is the 16-bit field m1n1 calls `unk3` in each device
  table entry.  Only the subsystem entries have one: MSR 1, JPG 2, VENC 3,
  VDEC0 4, ISP_SYS 5, RTMUX 6, DISP0_BE 7, **GFX 8**, AVD_SYS 9, PCIE 10,
  SBR 11.
* **GFX = group 8 → `pmgr reg[27] = 0x05000000`, size `0x9000`.**  That window
  is a PMGR block of its own, separate from the GPU's `0x4000000`; in the
  kext's 94-entry block-name table it is **`AGX_PMGR`** (neighbours:
  `DOCKFIFO`, `CPU_FABRIC`, `NRT_FABRIC`, `RT_FABRIC`, `LIO_CLK_RST`,
  `GFX_TVM`, `GPU_TRIG_CTL`, `PMGRClkGenSOC`).
* `ApplePMGR` maps every bridge at start: `getDeviceMemoryWithIndex(bridge-reg-index + b)`
  (confirmed in the disassembly at `0xfffffff0056528fc`…`0xfffffff005652990`),
  then logs `ApplePMGR: [Die %u] Bridge %u, virtual address = 0x%p, physical address = 0x%p`
  — and `Bridge %d has no mapping` when a reg index is missing.
* **`ApplePMGR` exposes `readGFXClkGenReg` / `writeGFXClkGenReg` /
  `waitGFXClkGenReg`** (assert strings at `0xfffffff004de1873`…), so the GFX
  *clock generator* is a first-class PMGR register set — nothing in Linux
  programs it, because the D21 DT maps `pmgr` as only `0x8c000` and there is no
  A11 PMGR clock driver, and `0x05000000` is in no node at all.

This is the first mechanism found that can leave `ps_gfx` reading ACTIVE while
every access inside the GPU block hangs: the power domain is up, the GPU's
clock generator/bridge was never configured.

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
  (`Fender+0x1000 = 0x11`), plus a RGX identity read at `0x20400018`
  (the AP alias — see below).

## Phase 2.2 — boot #12 executed: the bridge window hung the bus too (2026-11-12)

Payload `b074b748…`.  Everything up to the bridge dump repeated boot #11
exactly: `PMP-DIAG 0/4`…`4/4` from 12.8 s, HELLO + EPMAP `0x1f`/`0x1` at
16.86 s, `RTKit wake returned -62`, forced `SET_AP_PWR_STATE(ON)` at 35.8 s,
`PMP is up` at 36.3 s, `GFX-STAGE 0/13` at 23.0 s, `PMP is up after 11500 ms`
at 36.65 s, then `ps_gfx = 0x1f0003ff` and the whole `0x80300` bank at 38.7 s.

`GFX-STAGE 2/13` printed at 38.717 s and **the very first access after it — the
first `readl()` of the DISP0 bridge window at `0x19000000` — hung the bus**: no
`bridge disp0 @… +0x00` line, no output at all, phone reset to iOS.

| stage | result |
|---|---|
| `0/13` wait for PMP | up, 11.5 s after the GFX work started |
| `1/13` `ps_gfx` | `0x1f0003ff` (auto 1, was-clk 1, was-pwr 1, actual `0xf`, target `0xf`), bank otherwise unchanged from boot #11 |
| `2/13` bridge windows | **hung on the first read** of DISP0 `0x19000000` — before the GFX window was ever touched |
| `3/13`…`13/13` | never reached |

So the bridge model as written is disproved: a window that is *demonstrably
clocked and in use* (DISP0_BE — `simplefb` scans out of it) does not answer at
its ADT address either.  The ADT register windows are not addresses the AP can
reach — which is not a statement about power gating at all.

## Offline (2026-11-12, after boot #12): the AP alias — ADT address + `0x200000000`

The `pmgr` bridge list is not the only thing in the ADT whose address is
"wrong".  Every Apple block is listed twice: the **ADT** carries the address
iBoot uses, and Linux reaches the same block at **ADT + `0x200000000`**.

| block | ADT `/arm-io/...` `reg` | D21 DT node (in tree) |
|---|---|---|
| i2c0 | `0x2E200000` | `i2c@22e200000` |
| aic | `0x32100000` | `interrupt-controller@232100000` |
| pmgr | `0x32000000` | `power-management@232000000` |
| pmp | `0x32300000` | `pmp@232300000` |
| pmgr_mini | `0x35200000` | `power-management@235200000` |
| **gpu (sgx)** | `0x04000000` / `0x04D00000` | **`gpu@4000000` / `mbox@4d24000`** ← raw ADT address |

`/arm-io` declares `#address-cells = <2>`, so those ADT values are literal
32-bit addresses; the Linux DTs in this tree add the alias, and every one of
them works (the console, the PMGR PS reads, the PMP RTKit handshake — all at
`0x2…`).  The **t8010** GPU node in the same tree is at `0x201000000`
(`fender` `0x201d0000`, `iop` `0x201d2000`, mailbox `0x201d24000`) — the same
`+0x200000000` — while the t8015 GPU node is the *only* node in
`t8015.dtsi` still carrying a raw ADT address.

**Consequence:** every GPU/Fender/IOP/mailbox access in boots #2–#12 went to
`0x04000000` / `0x04D00000` / `0x04D20000` / `0x04D24000`, where nothing on
the AP bus responds.  "The GPU block is dark" was, in all likelihood, an
addressing bug: a read of an address with no responder hangs exactly like a
read of a powered-down block.  The `ps_gfx` "was clock gated" bit was read as
corroboration all along; it never was.

Correct addresses for this SoC:

| window | address | size |
|---|---|---|
| RGX | `0x204000000` | `0x100000` |
| Fender | `0x24D00000` | `0x20000` |
| GFX IOP | `0x24D20000` | `0x20000` |
| IOP mailbox | `0x24D24000` | `0x1000` |
| GFX bridge / `AGX_PMGR` (bridge 8) | `0x205000000` | `0x9000` |
| DISP0 bridge (group 7, reference) | `0x219000000` | `0x9000` |

## Boot #13 (built, NOT booted — needs a go)

Two changes only: the DT addresses above, and a reordered diagnostic that puts
the address test first.

| stage | action |
|---|---|
| `0/13` | wait for `apple_t8015_pmp_up` |
| `1/13` | `ps_gfx` + `0x80300` bank dump |
| `2/13` | **new**: RGX identity — dump `0x204000000+0x00..0xff` (`ROGUE_CR_CORE_ID` = `+0x18`, config in the low half, id in bits 16-31) |
| `3/13` | **new**: Fender identity — dump `0x24D00000+0x2000..0x207f` (the window/run page) |
| `4/13` | bridge windows at the alias (`0x219000000` then `0x205000000`) |
| `5/13` | `STARTEP(32)` + the six candidate messages |
| `6/13` | `ps_gfx` off→on retoggle |
| `7/13` | mailbox read `0x24D24000+0x08` (A2I control) |
| `8/13`…`13/13` | RTKit init, Fender/IOP window copy, run bit, HELLO, RGX re-read |

| log | meaning |
|---|---|
| `rgx +0x0010:` non-zero (or any `rgx +…` line with data) | **the block answers**: Phase 2.3 identity is one read away and the whole "dark GPU" thread collapses to an address bug |
| boot dies after the `2/13` banner, no `rgx +` line | `0x204000000` does not respond either — the alias is not universal, revisit the address map before any write |
| `rgx` reads all zero, Fender prints | RGX window responds but is unconfigured/held in reset — Fender/`AGX_PMGR` work is the next step |
| `mailbox: A2I control @… = …` prints | the IOP sub-block is clocked; Phase 2.2 becomes a firmware question |
| `GFX firmware is up; RTKit handshake complete` | Phase 2.2 passes |

## Phase 2.2 — boot #13 executed: the alias took effect, the RGX is still dark (2026-11-12)

Payload `97fb4601…` (DT `gpu@204000000`, `mbox@204d24000`).  The DT move is
confirmed by the binding itself: the driver is now `apple-t8015-gfx
204000000.gpu`, not `4000000.gpu`.  Everything up to the RGX read is unchanged
from #11/#12: PMP-DIAG `0/4`…`4/4` 12.8→16.9 s, HELLO + EPMAP, IOP ACK, `RTKit
wake returned -62`, forced `SET_AP_PWR_STATE(ON)` at 35.8 s, `PMP is up` at
36.3 s, GFX work at 23.0 s, `ps_gfx` `0x1f0003ff` + the whole `0x80300` bank at
38.69–38.71 s.

Then:

```
[38.714985] apple-t8015-gfx 204000000.gpu: GFX-STAGE 2/13: RGX identity (0x204000000+0x00..0xff)
<reset>
```

The **first** `readl(0x204000000)` hung.  That is a negative result, but it is
*not* an address verdict: the read order was wrong.  On the A10 (`pvr_apple.c`,
and the G10P kext's Fender code) the RGX core is dark until Fender is asked for
a power state; the sequence is window → run bit → firmware boot → **Fender
power request (`+0x1000 = state|0x10`, poll bit 4)** → RGX access.  Boots #2–#13
never issued that request, so a dark core is exactly what should be there.

Offline (ADT `pmgr/devices`), the GPU family is one power domain:

| id | name | parents | `no_ps` | note |
|---|---|---|---|---|
| 124 | `GFX` | — | no | the PS entry `ps_gfx` maps to (bank `0x80300`, index 7) |
| 148 | `GFX-SGX` | 124 | **yes** | the Rogue core |
| 149 | `GFX-KF` | 124 | **yes** | the GFX IOP / Fender |
| 123 | `GFX-BUSY` | — | **yes** | |

So `ps_gfx` covers the core *and* Fender/IOP; if Fender does not answer, the
address is wrong, and if it does, the missing piece is the power request.

## Boot #14 (built, NOT booted — needs a go)

One code change: the diagnostic order, plus the missing power request.

| stage | action |
|---|---|
| `0/13` | wait for `apple_t8015_pmp_up` |
| `1/13` | `ps_gfx` + `0x80300` bank dump |
| `2/13` | **Fender identity** — `0x24D00000+0x1000..0x103f` (power state, status) and `+0x2000..0x204f` (window + run page).  This is the block `ps_gfx` powers and the AP must reach; a read here is the address verdict |
| `3/13` | `STARTEP(32)` + the six candidate messages |
| `4/13` | `ps_gfx` off→on retoggle (non-fatal now) |
| `5/13` | mailbox read `0x24D24008` (A2I control) |
| `6/13` | RTKit init (non-fatal now) |
| `7/13` | Fender window copy (6 words at `+0x200c`) |
| `8/13` | IOP window copy (8-byte stride) + enable |
| `9/13` | run bit `Fender+0x2048 |= 1` |
| `10/13` | RTKit wake → HELLO |
| `11/13` | **Fender power request** — read `+0x1000`; if state ≠ 0 request 0 first; then write `0x11` and poll ack bit 4 |
| `12/13` | RGX identity, `0x204000000+0x00..0xff` (`ROGUE_CR_CORE_ID` at `+0x18`) |
| `13/13` | PMGR bridges `0x219000000` / `0x205000000` (last: a hang costs nothing already learned) |

| log | meaning |
|---|---|
| `fender +0x01000: …` prints | the alias is right and `ps_gfx` really powers Fender — the GPU family is reachable; the RGX hang was the missing power request |
| no `fender +` line, reset after `2/13` | `0x24D00000` does not answer: the GPU family is not reachable at alias + ADT, and the address map needs re-derivation |
| `fender power: state 1 -> 0x…1 after … ms (status 0x…)` | the request was accepted; `12/13` is then the verdict on the core |
| `rgx +0x0018: …` with a plausible `CORE_ID` (id in bits 16–31) | **Phase 2.3 identity**, from hardware |
| `GFX firmware is up; RTKit handshake complete` | Phase 2.2 passes |

## Phase 2.2 — boot #14 executed: **Fender and the IOP mailbox answer** (2026-11-12)

Payload `860b007a…`.  This is the boot that ends the "the GPU block is dark"
question: both GPU-family windows the AP has to reach **read back without
hanging**.

```
GFX-STAGE 2/13: Fender identity (0x24d00000+0x1000/+0x2000)
fender +0x1000: 00000000 00000000 00000000 00000000
fender +0x1010: 00000000 00000000 00000000 00000000
...
fender +0x2040: 00000000 00000000 00000000 00000000
GFX-STAGE 5/13: mailbox register read (IOP+0x4008)
mailbox: A2I control @0x0000000204d24000+0x08 = 0x0 (empty bit 0, full bit 0)
```

| stage | result |
|---|---|
| `2/13` Fender identity | **24 reads, all returned** (`0x24D01000..0x24D0204C` = all zero: block powered down, reset values) |
| `5/13` mailbox read | **returned** `0x0` at `0x24D24008` — the read that hung boots #5/#6/#10/#11 is now a normal MMIO read |
| `3/13` `STARTEP(32)` | `-> 0`, but the PMP logs `Received unexpected message to EP32: 0` — endpoint 32 is not a raw message endpoint |
| `4/13` retoggle | `0x1f0003ff` → `0x0f0003ff`, actual `0xf` in 10 ms (unchanged) |
| `6/13` RTKit init | two `RTKit: unknown management message: 0x0 (type: 0x00)`, then **the machine wedged** |

The wedge: the phone still enumerates as `05ac:4144` (USB hardware alive) but
does not answer ping and stops emitting kernel log.  `apple_mbox_poll_locked()`
loops `while (!(i2a_control & control_empty))` (bit 17) and calls `rx()` for
every word it reads; the I2A control never showed "empty", so it drained
phantom `0x0` words in IRQ context and never left the handler.  The mailbox
register layout for the `a7iop` variant is therefore the next thing to fix —
and the boot after that can finally do a real HELLO.

### What this changes

- The `+0x200000000` alias is right for the GPU family: `0x24D00000` (Fender)
  and `0x24D24000` (IOP mailbox) both respond; the raw ADT `0x04D00000` /
  `0x04D24000` never did.
- `ps_gfx` does power the SGFX core *and* the IOP (`GFX-SGX`/`GFX-KF` are
  `no_ps` children of `GFX` in the ADT), so nothing else needs powering before
  these windows work.
- The RGX core is still unread (boot #14 never reached it), and the all-zero
  Fender registers mean state 0 = off, exactly what the missing power request
  predicts.

## Boot #15 (built, NOT booted — needs a go)

No mailbox/RTKit this round: the GPU verdict comes first, with the mailbox left
as a read-only dump.  The goal is to convert "the windows answer" into "the
core answers".

| stage | action |
|---|---|
| `0/12` | wait for `apple_t8015_pmp_up` |
| `1/12` | `ps_gfx` + bank dump |
| `2/12` | Fender state read (`+0x1000`, `+0x1010`) |
| `3/12` | **mailbox register dump `+0x00..+0x3c`** (read-only, no IRQ, no RTKit) |
| `4/12` | `STARTEP(32)` + candidates (unchanged) |
| `5/12` | `ps_gfx` retoggle |
| `6/12` | Fender window copy (`+0x200c`, 6 × u32) |
| `7/12` | IOP window copy (`+0x08`, 6 × u64) + enable, then **read-back of both copies** |
| `8/12` | run bit (`Fender+0x2048 |= 1`), 1 s for the firmware to start |
| `9/12` | Fender power request (state 1), ack poll |
| `10/12` | **RGX identity dump** (`0x204000000+0x00..0xff`, `CORE_ID` at `+0x18`) |
| `11/12` | bridges (last) |
| `12/12` | done marker |

| log | meaning |
|---|---|
| `window readback fender: <window values>` | Fender is a real writable block (not a zero-returning hole) — the firmware window is programmed |
| readback all zero | writes do not stick: the block is in reset or the window register offsets are wrong |
| `fender power: state 1 -> 0x…1` | the power request was accepted → the core should now answer |
| `rgx +0x0018: …` | **the GPU core answers** — Phase 2.3 identity from hardware |
| still no `rgx +` line | the core needs the AGX firmware handshake (mailbox) before it leaves reset, so the mailbox fix is the gate |
| `mbox +0x00..0x3c` values | the `a7iop` layout needed to fix `apple_mbox_poll_locked()` |

## Phase 2.2 — boot #15 executed: **the RGX core answers** (2026-11-12)

Payload `d06c1f7d…`.  GPU verdict first, mailbox read-only, no RTKit.  The
phone reset at the very end (sacrificial bridge scan), but every stage that
mattered printed first.

```
GFX-STAGE 6/12: Fender window copy
GFX-STAGE 7/12: IOP window copy + enable
window readback fender: 0e100000 00000008 00000000 00000000 00100000 00000000
window readback iop: 0e100000 00000000 (enable 00000001)
GFX-STAGE 8/12: release the IOP (run bit)
GFX-STAGE 9/12: Fender power request (state 1)
fender power: state 1 -> 0x1 after 10 ms (status 0x0)
GFX-STAGE 10/12: RGX identity (0x204000000+0x00..0xff)
rgx +0x10: 00000000 00000000 000007e1 00000000
```

| stage | result |
|---|---|
| `6/12` Fender window copy | **written and read back**: `0x0E100000` (upper `0x8`), size `0x00100000` |
| `7/12` IOP window copy | `0x0E100000` + enable `0x1` read back — the IOP really is pointed at the firmware window |
| `8/12` run bit | accepted, firmware released, 1 s settle |
| `9/12` Fender power request | **`state 1 -> 0x1` in 10 ms** (status/ack bit stayed 0 — the A11 ack bit is not the A10 one) |
| `10/12` RGX identity | **`0x204000018 = 0x7E1`** — `ROGUE_CR_CORE_ID` answered; the only non-zero word in `0x00..0xff` |
| `3/12` mailbox dump | **all 16 registers `0x00..0x3c` read `0x0`** at `0x204D24000` |
| `5/12` retoggle | `0x1f0003ff -> 0x0f0003ff`, actual `0xf` (unchanged) |
| `4/12` PMP calls | `STARTEP(32) -> 0` + `unexpected message to EP32`; all clg-word/fn30 calls `-> 0` |
| `11/12` bridges | DISP0 `0x219000000` answered: `+0x10=0x8f04`, `+0x14=0x4`, `+0x18=0x10001`, `+0x1c=0x40`, `+0x20=0x40`, `+0x4000=0xc00c000c`; the scan then **stalled inside the DISP0 window** (`0x4000`-ish+) and the phone reset to iOS |

### What this changes

- **The GPU core is alive and reportable.** `CORE_ID (0x0018) = 0x7E1` is the
  hardware identity Phase 2.3 needed; the missing step all along was the
  Fender power request (boot #13 hung on the *same* first RGX read with no
  request pending).
- **Fender is a real writable block**, not a zero-returning hole: the window
  copy reads back exactly what was written, and the power-request state
  latched `0x1`.
- The A11 ack bit is not the A10 one (`status 0x0` after a successful state
  transition), so the power poll must key on the state field, not bit 4.
- **The IOP mailbox window reads all-zero.** That is why RTKit wedged the
  machine in boot #14: `apple_mbox_poll_locked()` tests "empty" as a set bit,
  and an unclocked/all-zero block never sets it. The mailbox is either not
  clocked by `ps_gfx` alone or its `a7iop` register map is wrong — the next
  boot must *enable* the FIFOs and re-dump, not just read.
- Bridge scans past the first `0x20` bytes are dangerous: the DISP0 window
  stalls shortly after `0x4000`. Any future dump is `0x00..0x1c` only.

### Decoding `0x7E1`

`ROGUE_CR_CORE_ID` (offset `0x0018`) is `{ID[31:16], CONFIG[15:0]}`, so the
raw read is `ID=0x0000, CONFIG=0x07E1` → `n=0x07, c=0xE1` under the A10
(PowerVR Rogue) mapping.  `ROGUE_CR_CORE_ID__PBVNC`/`CORE_REVISION` at `0x0020`
read `0x0`, so the newer BVNC path is not implemented on this core.  The A11
core is Apple's own, so whether `CONFIG` means 7 clusters must be checked
against the G10P kext before it is trusted.

## Boot #16 plan (not built — needs a go)

1. `1/10`–`7/10`: the proven GPU path (`ps_gfx` → Fender window → run bit →
   power request) — keep it, it is the only way to a live RGX.
2. `8/10`: **mailbox enable experiment** on `0x204D24000`: write the
   `A7IOP_MBOX_CONTROL_ENABLE` bit to both FIFO control registers, then
   re-dump `0x00..0x3c` and read the I2A FIFO once.  If the block goes from
   all-zero to a real control value, the layout is right and RTKit can be
   retried with a bounded poll loop; if it stays zero, the mailbox needs its
   own clock/power (GFX bridge / `AGX_PMGR`) and that is the next address to
   find.
3. `9/10`: 64-bit `0x0020` (PBVNC) + `CORE_REVISION` read for the identity.
4. `10/10`: done.  **No bridge scan this time.**

## Phase 2.2 — boot #16 executed: identity reproduced, mailbox is **unclocked** (2026-11-12)

Payload `d099ad9f…`, 10 stages, **phone stayed alive** (`05ac:4144`, net up,
`9/10: done` printed).  No bridge scan this time.

```
rgx core_id 0x000007e1 (id 0x0000 config 0x07e1 n 0x07 c 0xe1)
rgx pbvnc/core_revision @0x20 = 0000000000000000
mbox control: A2I 00000000, I2A 00000000, I2A recv 00000000
```

| stage | result |
|---|---|
| `3/10`/`4/10` windows | identical read-back to boot #15 (`0e100000` + `00100000`, IOP enable `1`) |
| `6/10` power request | accepted (state `0x1`) — path is reproducible |
| `7/10` RGX identity | `CORE_ID = 0x7E1` again; `0x0020` (PBVNC/CORE_REVISION) is `0` |
| `8/10` mailbox | **all `0x00..0x3c` zero before *and* after writing the FIFO enable bits** — the writes do not stick |

### Verdict on the mailbox

Two dumps around an explicit `ENABLE` write to `0x204D24008`/`0x204D2420`
prove the block is **not powered/clocked** (a real, enabled `a7iop` mailbox
returns a non-zero control value, and `+0x10`/`+0x38` would not stay zero).
That is the true cause of boot #14's wedge: `apple_mbox_poll_locked()` treats a
cleared `EMPTY` bit as "message waiting", and an unclocked block reads `0`
forever.

The address itself still looks right: the A10 tree places its GPU mailbox at
`0x201D24000` with `reg = <0x2 0x01d24000 0 0x1000>` and `gpu@201000000`, i.e.
**GPU base + `0xD24000`** — exactly our `0x204D24000` relative to
`0x204000000`.

### New RE lead (from the D21 kernelcache)

The prelink info contains `AppleA7IOP` with mailbox-specific strings:

```
a7iop_enable_timeout
_acquireMailboxPower(false) == kIOReturnSuccess
_acquireMailboxPower(true) == kIOReturnSuccess
AKF_AP_MAILBOX_SET  = 0x%08x
AP->IOP Mailbox Log:
```

So the A7IOP mailbox has its **own power acquire path** (and an
`AP_MAILBOX_SET` register) — the missing step is a gate we never touch, not a
wrong base address.  That is the next offline target: disassemble
`AppleA7IOP`'s mailbox init / `_acquireMailboxPower` and get the offsets and
the enable sequence.

## Boot #17 candidates (not built)

1. **Offline-first**: `AppleA7IOP` mailbox init + `_acquireMailboxPower` from the
   D21 kernelcache → learn the enable register and what power it asks for.
2. Then a boot that (a) takes the proven GPU path, (b) applies that enable,
   (c) re-dumps the mailbox, and (d) — only if the block wakes — starts RTKit
   with a **bounded** poll loop (max 8 messages per IRQ) so a stale `EMPTY`
   bit can never livelock the machine again.
3. Also worth reading while there: `IOP+0x00..0x3c` (the gfx-kf window answered
   in boot #15/#16, so it is safe), to see whether the IOP reports a running
   state after the run bit.

## Phase 2.2 — boot #17 built (2026-11-12): sweep the gfx-kf windows

Payload `96ab42f3…` (built, **not booted** — needs a go; the phone is still
running the boot #16 Linux and has to go back to PongoOS).

Before spending the boot, the `AppleA7IOP` kext in the D21 kernelcache was
disassembled, because boot #16's "the mailbox reads zero" was the only
remaining explanation and the kext contradicts it:

| Apple's log label | offset |
|---|---|
| `MAILBOX_SET` | `+0x1000` (enable write is `0x1111`) |
| `MAILBOX_CLR` | `+0x1004` |
| `INBOX_CTRL` | `+0x1008` (status bits 16..18) |
| TX data | `+0x1010` (64-bit) |
| `OUTBOX_CTRL` | `+0x1020` (bit 0 = start) |
| RX data | `+0x1038` (64-bit) |
| `CPU_CTRL` | `+0x0028` |

The tree's `apple_mbox_a7iop_hw` map (`0x08/0x10/0x20/0x38`) is **exactly this
map minus `0x1000`** — so boot #16 probed the wrong 64 bytes, and "the block
is dead" was never established (boot #15 proved writes stick in that region).

The ADT also says the A11 mailbox is **not** a separate device window:
`/arm-io/gfx-kf` owns `0x4d20000`+`0x4d00000` (128 KiB each) *and* the four
mailbox IRQs (260, 259, 262, 261).

Boot #17 therefore sweeps both `gfx-kf` windows 64 bytes at a time, logs every
non-zero chunk, and tries the `0x1111` enable write on every live page.  Full
write-up: `phase2.2/A7IOP-MAILBOX.md`; extraction tool:
`GPU-WIP/tools/a7iop-mailbox-re.py`.

## Phase 2.2 — boot #17 executed: the Fender window map, and a hole (2026-11-12)

Payload `96ab42f3…`.  The sweep found the live registers in the **Fender**
window and then died on a hole, which reset the phone:

```
fender sweep +0x1000: 00000001 00000000 00000000 00000000
fender sweep +0x2000: 00000000 00000000 00000000 0e100000
fender sweep +0x2040: 00000000 00000000 00000001 00000000
fender sweep +0x4000: 01001000 00000000 00010704 00000000
fender sweep +0x4040: 00000000 00000000 0000000f 0000002f
fender sweep +0x4080: 00000028 00000040 00000028 00000028
```

| offset | value | what it is |
|---|---|---|
| `+0x1000` | `0x1` | the Fender power state we requested (state 1) |
| `+0x1004` | `0x0` | the power *ack* never sets on the A11 |
| `+0x200c` | `0x0e100000` | the firmware window base we wrote |
| `+0x2048` | `0x1` | the run bit we set |
| `+0x4000` | `0x01001000` | **live, unknown** — looks like Apple's `MAILBOX_SET` (bits 12, 20, 24) |
| `+0x4004` | `0x0` | looks like `MAILBOX_CLR` |
| `+0x4008` | `0x00010704` | looks like `INBOX_CTRL`: status bit 16 set, count field `0x07` |
| `+0x4048` | `0x0000000f` | unknown (`0xf`) |
| `+0x404c` | `0x0000002f` | unknown (`0x2f`) |
| `+0x4080` | `0x00000028` | unknown — `40` is the A10's `phys_bus_width` |
| `+0x4084` | `0x00000040` | unknown (`64`) |
| `+0x4088`, `+0x408c` | `0x28`, `0x28` | unknown |
| `+0x40c0` | — | **hole: the read stalled and the phone reset** |

Two things follow.

1. The `+0x4000` block matches Apple's mailbox layout (SET / CLR / INBOX_CTRL
   in the first three words) **but it is in the Fender window**, not the IOP
   window — and the IOP window was never reached because the sweep died first.
   `INBOX_CTRL = 0x00010704` says "not empty" (bit 16 set) with a count of 7,
   which would mean the IOP posted messages we never read.
2. The `0x7e1` CORE_ID and `0x10704` both carry `0x07` in bits 15:8 — the same
   "number of scalable units" field under the Rogue encoding, so the A11 core
   plausibly has 7 clusters (the A10 had 6).  Worth confirming against the
   G10P kext before it is used.

## Boot #18 (built, NOT booted — needs a go)

No blind sweeps any more: targeted 64-byte probes of the mailbox candidates,
in this order.

| # | address | why |
|---|---|---|
| 1 | `0x204d21000` | Apple's map: IOP window base + `0x1000` |
| 2 | `0x204d25000` | our DT mailbox base + `0x1000` |
| 3 | `0x204d20000` | IOP window head (the window registers we already know) |
| 4 | `0x204d24000` | our DT mailbox base (read back zero in boot #16) |
| 5 | `0x204d03000` | `Fender+0x3000`, i.e. the base of the `+0x4000` block |
| 6–8 | `0x204d04000/4040/4080` | the live block, re-read |
| 9–10 | `0x204d02000/01000` | the Fender window head |

The `0x1111` enable write is applied **only** where the probe at `+0x08`
already shows Apple's INBOX_CTRL status bits (16..18) — no blind writes — and
every candidate is re-probed afterwards.

## Phase 2.2 — boot #18 executed: candidates probed, nothing at the old address (2026-11-12)

Payload `5ce2008e…`.  All 12 stages ran, **no reset** — the targeted probes
were the right call.

```
probe apple-mbox+1000 @0x204d21000:  all zero
probe dt-mbox+1000     @0x204d25000:  all zero
probe dt-mbox           @0x204d24000:  all zero   (our DT's mailbox node)
probe fender+3000       @0x204d03000:  all zero
probe fender+4000       @0x204d04000:  01001000 00000000 00010704 00000000
                                          00090303 00020202 00000080 00000000
probe iop-head          @0x204d20000:  00000101 00000000 0e100000 00000000
                                          00000008 00000000 00000000 00000000
                                          00000000 00000000 00100000 00000000
                                          00000000 00000000 00000001 00000000
probe fender+1000       @0x204d01000:  00000001 00000000 00000000 00000000
                                          00000000 00000002 00000000 00000000
probe fender+4040       @0x204d04040:  00000000 00000000 0000000f 0000002f
                                          00000000 00000000 00000000 00000000
                                          00000002 00000000 00000000 00000000
probe fender+4080       @0x204d04080:  00000028 00000040 00000028 00000028
```

### What the probes say

* **The mailbox is not at the DT address.**  `0x204d24000` (our
  `gpu_mbox` node) and `0x204d25000` (DT + Apple's `0x1000`) are *all zero*,
  and the `0x1111` write to `0x204d04000` did **not** change that register
  (`0x01001000 -> 0x01001000`), so `0x204d04000` is not a write-1-to-set
  mask — it is a read-only status/config register, not `MAILBOX_SET`.
* **The IOP window head has a register nobody had read: `+0x00 = 0x00000101`.**
  The rest of the head is the firmware-window registers we wrote
  (`+0x08` base, `+0x10` upper, `+0x24` size, `+0x38` enable).
* The `Fender+0x4000` block now has more detail: `+0x4010 = 0x00090303`,
  `+0x4014 = 0x00020202`, `+0x4018 = 0x80`, `+0x4048 = 0x0f`,
  `+0x404c = 0x2f`, `+0x4060 = 2`, `+0x4080.. = 0x28 0x40 0x28 0x28`.
  `0x28` is **40**, the A10's `phys_bus_width`, and `+0x4088`/`+0x408c` are
  also 40 — so this block looks like the **G10P device-information registers**
  (bus width, address-space bits, tile/ISP geometry) that the iOS kext reads
  and that our tree still hardcodes for the A10.  `0x090303`/`0x020202` read
  as bytes (9, 3, 3) and (2, 2, 2) are plausibly cluster/geometry counts.
* `Fender+0x1014 = 2` is another status register we never read
  (`FENDER_STATUS` at `+0x1010` reads 0).

### Still missing

The mailbox register block has not been found *anywhere*: every candidate is
zero.  Either it is dead until its own power/clock gate is on (Apple's
`ps-reg-offset` / `pc-sample-offset` DT properties, values not in the ADT), or
its address is outside everything probed so far.

## Boot #19 plan (not built — needs a go)

1. Keep the proven GPU path.
2. Apply Apple's **full** enable sequence to each candidate base
   `0x204d20000`, `0x204d24000`, `0x204d03000`:
   write `0x1111` to `base+0x1000`, write `1` to `base+0x1004`, write `0x1000`
   to `base+0x1000`, set bit 0 of `base+0x1020` — logging every read-back.
3. Re-probe `0x204d21000`, `0x204d24000`, `0x204d25000`, `0x204d20000`,
   `0x204d03000`, `0x204d04000`.
4. Sweep the first 4 KiB of the **IOP** window and of the **Fender** window
   (the ranges that were never read) for any other live block.

## Phase 2.2 — boot #19 executed: the kext's base is pinned down (2026-11-12)

Payload `8f9bfb9b…`.  All 13 stages, **no reset**.

```
enable iop-window @0x204d20000: SET 0x0->0x0 CLR 0x0->0x0 INBOX 0x0->0x0 OUTBOX 0x0->0x0
enable dt-mbox     @0x204d24000: SET 0x0->0x0 CLR 0x0->0x0 INBOX 0x0->0x0 OUTBOX 0x0->0x0
enable fender+3000 @0x204d03000: SET 0x1001000->0x1001000 CLR 0x0->0x0 INBOX 0x10704->0x10704 OUTBOX 0x0->0x0
iop sweep +0x0040: 000f0401 00000000 0000004f 00000000
iop sweep +0x0800: 00000060 00180018 00000000 60000003
fender sweep 0x40..0x1000: 0 non-zero chunks
```

* Apple's **full enable sequence changed nothing**: the two candidate bases
  ignore writes entirely, and the one live block ignores them too — it is
  read-only configuration, not `MAILBOX_SET`.
* **The Fender window head (`+0x40..+0x1000`) is entirely zero** — one window
  is completely mapped out below `+0x1000`.
* **The IOP window has two more live blocks**: `+0x40` (`0x000f0401`,
  `0x0000004f`) and `+0x800` (`0x00000060`, `0x00180018`, `0x60000003`).

### The kext's register offsets settle the window question

Scanning every `mov w1, #off ; blr` that goes through the kext's
`readRegister` helper gives the offsets Apple's code uses from its base:

```
0x28  0x44  0x48  0x80c  0xb88
0x1000 0x1004 0x1008 0x1020        <- MAILBOX_SET/CLR/INBOX_CTRL/OUTBOX_CTRL
0x4000 0x4004 0x4008 0x4020 0x4040
0x8000 0x8110 0x8114
```

* `+0x4000..+0x4040` is **exactly** the live block found in the **Fender**
  window (`0x204d04000`).
* `+0x48` and `+0x80c` are exactly the live registers found in the **IOP**
  window (`0x204d20048 = 0x4f`, `0x204d2080c = 0x60000003`).

One base cannot be both windows — so the kext drives **two device instances**
from one class, and the `+0x8000/+0x8110/+0x8114` cluster (read eight times
between them) has to be live in whichever window is the kext's base.  That
cluster is the discriminator.

## Boot #20 plan (not built — needs a go)

1. Proven GPU path.
2. Sweep `+0x8000..+0x8200` of the **IOP** window.
3. Sweep `+0x8000..+0x8200` of the **Fender** window.
4. Sweep `+0x0080..+0x0100` and `+0x0b80..+0x0b90` of both windows.
5. Sweep `+0x4000..+0x4040` of the IOP window (the one kext block not yet
   read there).

## Phase 2.2 — boot #20 executed: the kext's base is the **IOP window** (2026-11-12)

Payload `2398b846…`.  All 12 stages, **no reset**.

```
iop+8000 sweep +0x8000: 0000004f 00000000 00000000 00000000
iop+8000 sweep +0x8100: 00000000 00000000 00020001 00100101
iop+8000 sweep +0x8140: fdff7f7b fdf7fd67 bedfffe1 00020000
iop+8000 sweep +0x8180: 7efffecd fffeeff5 0addffff 00020000
iop+8000 sweep +0x81c0: 9fff66df f7ffdfff fdffff5f 00100100
iop+8000 sweep 0x8000..0x8200: 5 non-zero chunks
fender+8000 sweep 0x8000..0x8200: 0 non-zero chunks
iop+4000 sweep 0x4000..0x4040: 0 non-zero chunks
iop+0080 / fender+0080 / iop+0b80 / fender+0b80: 0 non-zero chunks
```

### Verdict

The kext's base is the **IOP window (`0x204d20000`)**: the `+0x8000`,
`+0x8110`, `+0x8114` cluster it reads eight times between them is live there
and **dead in the Fender window**.  The `+0x48`/`+0x80c` reads also match the
IOP window.  The `+0x4000` cluster that matched the Fender window's live
block therefore belongs to the kext's *second* device instance (gfx-kf's
`reg[1] = 0x4d00000`).

So the mailbox register block is at **IOP window + `0x1000` = `0x204d21000`** —
and that page is dead: it reads zero and ignores Apple's enable sequence,
while everything around it in the same window is alive (including `+0x00`,
`+0x40`, `+0x48`, `+0x800`, `+0x8000`…).  **That is the signature of an
unclocked block**, not of a wrong address.

### Bonus: two Phase 2.3 blocks found

* **DART** (the GPU's address-translation unit) at IOP `+0x8000`: `+0x8000 =
  0x4f`, `+0x8108 = 0x00020001`, `+0x810c = 0x00100101`, and a run of bitmask
  registers at `+0x8140`… (`0xfdff7f7b`, `0xfdf7fd67`, `0xbedfffe1`, …).  The
  kext's code around these reads is the one that also references the string
  `base + dart_vm_size`, so this is the DART block.
* **Device information** in the other instance: `0x204d04000` = `0x01001000`,
  `0x204d04008` = `0x00010704`, `0x204d04010` = `0x00090303`,
  `0x204d04014` = `0x00020202`, `0x204d04048` = `0x0f`,
  `0x204d0404c` = `0x2f`, `0x204d04060` = `2`, `0x204d04080..` =
  `0x28 0x40 0x28 0x28`.  `0x28` = 40 = the A10's `phys_bus_width`.

### The remaining blocker

The mailbox page needs a **clock** (`gfx-kf` has `clock-ids = 269`; `ps_gfx`
only covers *power*).  The PMP firmware owns clock gates (its tag table has
`CLKG` next to `PWRG`), so the AP has to ask the PMP — our `STARTEP(32)`
attempt was rejected with `Received unexpected message to EP32: 0`, i.e. the
*message format*, not the endpoint, is wrong.  That is the next offline target:
the PMP command word (`bits 0..11` value, `bits 12..19` device index,
`bits 20..21` command) in `pmp-t8015.bin`.

## Phase 2.2 — the PMP gate message format, cracked offline (2026-11-12)

No boot needed for this one.  `pmp-t8015.bin` is Thumb-2, and the host has
`libcapstone` (`GPU-WIP/tools/pmp-fw-dis.py` wraps it through ctypes), so the
firmware's message dispatcher can finally be read properly.

The dispatcher lives at **`0x0100e940`** in the firmware and decodes the
incoming message like this:

```
0x0100e940: ldr   r2, [sp, #0xc]        ; the message word
0x0100e942: tst.w r2, #0xc00000        ; bits 22..23
0x0100e946: bne   0xe9aa               ; -> prints "Not implemented"
0x0100e952: lsrs  r6, r2, #0x14        ; command = message >> 20
0x0100e954: sbfx  r1, r2, #0x0, #0xc   ; value    = message & 0xfff
0x0100e958: ubfx  r3, r2, #0xc, #0x8   ; device   = (message >> 12) & 0xff
0x0100e962: bne   0xe974               ; command bit 0 -> descriptor = dev << 12
0x0100e966: bmi   0xe978               ; command bit 1 -> descriptor = dev << 20
0x0100e970: lslne r2, r3, #0x15        ; command 3        -> dev << 21
0x0100e97a: movw  r3, #0x202
0x0100e97e: str   r2, [r4, #0x10]      ; the descriptor goes to the context
```

and the error path of the handler it calls logs **`!clg: %08x`** (the literal
sits at `0x0100e9bc`, right in this function's pool) — so this is the
**clock-gate** handler, and the descriptor for command 1 is `dev << 12`, the
same `0x100000 | (idx << 12)` form the knowledge base had already spotted.

**So a gate request to the PMP is:**

```
message = (command << 20) | (device_index << 12) | (gate_id)
```

with `command = 1` for a clock gate and `bits 22..23` left clear.  For the
GFX IOP mailbox that is device 149 (`GFX-KF`, `clock-ids = 269`):

```
(1 << 20) | (149 << 12) | 269  =  0x109510d
```

The PMP answers on the endpoint, and the PMP driver prints that answer as
`Received unexpected message to EP32: <value>` — so the reply is a usable
feedback channel for every attempt.

### Why this should work

`ps_gfx` only covers *power* (the ADT gives `gfx-kf` `power-gates = 0x95`
and `clock-gates = 0x95`, and the PMP firmware owns the clock gates: its tag
table has `CLKG` next to `PWRG`).  Everything alive in the IOP window is on
the AP clock; the mailbox page at IOP `+0x1000` is on the mailbox's own
clock, which is exactly what has to be opened.

## Boot #21 plan (not built — needs a go)

1. The proven GPU path (unchanged).
2. Six PMP gate attempts on ep32, each followed by a re-read of the mailbox
   page: `clkg gfx-kf 269`, `clkg gfx-sgx 265`, `clkg gfx 269`,
   `clkg gfx-kf 0`, `clkg gfx-kf all (0xfff)`, `cmd0 gfx-kf 0`.
3. Full dump of the mailbox block after the attempts.
4. Full dump of the **DART** block (IOP `+0x8000..0x8200`) for Phase 2.3.
5. Full dump of the remaining live IOP window regions (`+0x40..0x100`,
   `+0x800..0x820`).

## Phase 2.2 — boot #21 executed: PMP gate ignored, **DART block captured** (2026-11-12)

Payload `ed3735be…`.  All 12 stages, **no reset**.

```
PMP try clkg gfx-kf 269: msg 0x19510d     -> mailbox +0x1000..0x101c: all zero
PMP try clkg gfx-sgx 265: msg 0x194109    -> all zero
PMP try clkg gfx 269: msg 0x17c10d        -> all zero
PMP try clkg gfx-kf 0: msg 0x195000       -> all zero
PMP try clkg gfx-kf all: msg 0x195fff     -> all zero
PMP try cmd0 gfx-kf 0: msg 0x95000        -> all zero
```

* The messages went out (the format is the one the firmware's dispatcher
  decodes) but the PMP **did not reply at all** — not even the
  `Received unexpected message to EP32` that the earlier `STARTEP` produced.
  So ep32 either does not carry the gate service, or the gate service is
  reached on another endpoint and the firmware stays silent for unknown ones.
* The mailbox page stayed dead after every attempt.
* **The DART block is now mapped** — IOP `+0x8000..+0x8200`, page-group masks
  with per-group config words, `dart_vm_size = 0x4f`, base config
  `+0x8108 = 0x00020001`, `+0x810c = 0x00100101`.  Full dump and analysis in
  `phase2.2/G10P-REGISTERS.md`.

### Where we stand

| piece | state |
|---|---|
| RGX identity | `CORE_ID = 0x7E1` (`n=7`, `c=0xE1`) — reproducible across boots |
| firmware window + IOP release | working (window reads back, run bit sticks) |
| Fender power request | accepted (`state 0x1`; the ack bit is not the A10's bit 4) |
| device information block | mapped (`0x204d04000`), the A11's own bus width etc. |
| DART / IOMMU | mapped (`0x204d28000`) — enough to build GPU page tables |
| **mailbox** | **still dark**: IOP `+0x1000` reads zero and ignores writes |

The mailbox is the last piece that blocks the IOP firmware handshake, and
therefore the GPU itself.  The PMP route is not it (no reply, no effect), so
the next lead is the **PMGR clock gate** for `gfx-kf`/`clock-id 269` — the
AP-side `ApplePMGR` kext writes those, and our `ps_gfx` write only ever
touched the *power* state register at PMGR `+0x80338`.

## Phase 2.2 — the PMGR clock-gate table (offline, 2026-11-12)

The `ApplePMGR` kext keeps a **clock-gate name table** in the D21 kernelcache
(`__PLK_DATA_CONST` at `0xfffffff006c9e8c8`): 35 entries of
`{ const char *name; u32 a; u32 b; }`, 24 bytes each, with the two numbers
zero in the image and filled in at init.  The names are

```
ISP_REF0_CLK_CFG  TOUCH  CLUSTER_CTL  SOC_TVM  GFX_TVM  GFX1_TVM  ANE_TVM
ANE1_TVM  MISC_CORES  MISC_ACG  ECPU_TRIG_CTL  PCPU_TRIG_CTL  PCPU1_TRIG_CTL
ANE_TRIG_CTL  ANE1_TRIG_CTL  GPU_TRIG_CTL  GPU1_TRIG_CTL  GPU2_TRIG_CTL
GPU3_TRIG_CTL  MINI_MISC_CFG  MINI_ACG_CLK_CFG  DPE0_CFG  ANE_PERF_STATE
ANE1_PERF_STATE
```

plus the earlier `C1_CPU3_IMPL ... PMGRClkGenSOC ... PMGRCLKGENAON ...` group
(the *generators*).  The kext copies the static table into its per-device
object at init (`0xfffffff00564b128`, 816 bytes to `obj+0x2600`), so the
runtime numbers are filled from somewhere else — the ADT's numeric
`clock-ids` (265 for `sgx`, 269 for `gfx-kf`) index a *larger* runtime table
that has not been located yet.

So the PMGR clock-gate route is not yet actionable; boot #22 therefore looks
for the gate bank directly instead: the PMGR window is `0x8c000` bytes and
the per-device state bank sits at `0x80300 + 8*n` (`ps_gfx` is `0x80338`), so
a sweep of the window's top `0xc000` bytes will show any parallel bank.

## Boot #22 plan (built, NOT booted — needs a go)

1. The proven GPU path.
2. **RGX core register map**: dump the first 4 KiB of the core window, every
   non-zero 64-byte chunk in full (this is the Phase 2.3 input: the A10
   driver reads `CORE_ID` at `0x18`, `CORE_REVISION` at `0x20`, the designer
   fields at `0x28`/`0x30`, and the A11's cluster count has to come from
   hardware).
3. **Sweep the PMGR per-device bank** (`0x80000..0x8c000`) for a clock-gate
   bank.
4. Re-dump the live IOP window regions and the mailbox page for the record.

## Phase 2.2 — boot #22 executed: the RGX core window is sparse, the PMGR has no clock bank (2026-11-12)

Payload `b69934ed…`.  All 12 stages, **no reset**.

### The RGX core register map

The whole first **4 KiB** of the core window contains exactly **one** non-zero
64-byte chunk: `0x204000018` = `0x7E1` (`CORE_ID`).  Every other register in
`0x0000..0x0FFF` reads zero.

That is the answer to the Phase 2.3 question: the A11 core does **not**
implement the Rogue cluster/tile registers in its core window, so the
cluster count and the geometry cannot come from there.  They come from the
**device-information block** at `0x204d04000` (`0x28` = 40 = bus width, and
friends) or from the firmware, exactly as on the A10.

### The PMGR per-device bank

Sweeping `0x80000..0x8c000` found 16 non-zero chunks, all of them power-state
entries.  The bank layout is now exact:

```
base(psreg) = 0x80300 + 0x100 * (psreg - 4)      index = psidx
```

which matches `ps_gfx` = GFX (dev 124, psreg 4, psidx 7) at `0x80338`, and
identifies `0x80400` as **SEP** (dev 126, psreg 5) and `0x80500..` as the ISP
block.  `0x80840`, `0x84000` and `0x88000` are the remaining banks.

**There is no clock-gate bank in the PMGR window** — the clock gates are the
PMP firmware's, which is consistent with its `CLKG` tag.

### The mailbox, still dark

The IOP window's live registers are unchanged and the mailbox page at IOP
`+0x1000` is still all zero.

One new datum for the next attempt: the PMGR device table indexes the GFX
family as

| device | dev id | list index | psreg/psidx |
|---|---|---|---|
| GFX | 124 | 106 | 4 / 7 (`0x80338`) |
| GFX-SGX | 148 | 120 | no_ps |
| GFX-KF | 149 | **121** | no_ps |
| GFX-BUSY | 123 | 122 | no_ps |

and boot #21 sent the gate message with the **device id** (149).  If the PMP
indexes its own device table by *list index*, the right value is **121**.

## Boot #23 candidates (not built)

* CLKG with the list indices (`121`, `120`, `106`) instead of the device ids.
* CLKG with the value field carrying the *psidx* (`7`) instead of the clock
  id (`269`).
* CLKG on other PMP endpoints (ep 33..40), since ep 32 answered the earlier
  management message but stayed silent for the gate message.

## Phase 2.2 — boot #23 executed, and the PMP handler explains the silence (2026-11-12)

Payload `27598921…`.  All 12 stages, **no reset**.  Twelve gate-message
shapes were sent (list indices `121`/`120`/`106` as well as the device ids
`149`/`148`/`124`, the value field carrying the clock id `269`/`265` or the
psidx `7` or `0xfff`, command 1 and 2, endpoints 32/33/34/40):

```
gate try clkg gfx-kf table121 id269: ep 32 msg 0x17910d   -> mailbox still zero
gate try clkg gfx-kf table121 psidx7: ep 32 msg 0x179007 -> mailbox still zero
gate try clkg gfx-kf id149 psidx7:   ep 32 msg 0x195007 -> mailbox still zero
... (12 in all, no reply from the PMP, no change)
```

**No reply at all, and no effect.**  But the firmware explains why, and the
answer is embarrassing: the PMP driver in this tree already carries the note

```
/* DIAG (boot #12): an application endpoint has to be STARTEP'ed before the
 * firmware routes messages to its service; boot #11 sent to ep 32 without it
 * and the PMP stayed silent. */
```

Boots #21 and #23 sent their gate messages **without starting ep 32 in the
same session**, so the firmware dropped them — exactly the failure mode the
comment describes.

### What the gate handler actually does (`0x0100d814`)

```
0x0100d842: bfc   r8, #12, #20      ; r8 = the other message word & 0xfff
0x0100d846: cmp.w r8, #0
0x0100d84c: moveq r4, r2            ; descriptor = device << 12
0x0100d84e: bfceq r4, #12, #20
0x0100d854: bne   0xd8f6            ; fail if both low halves are zero
0x0100d866: lsls.w r1, r11, #0x18   ; clock id -> mask
0x0100d86a: and   r1, r11, #0xff00
0x0100d870: addeq.w r11, r1, #1     ; mask = (id << 24) | (id & 0xff00) | 1
0x0100d87e: add.w r1, r10, r8      ; device<<12 + endpoint
0x0100d884: addw  r1, r1, #0xfff
0x0100d888: orr   r0, r11, #0x80000000
```

So the PMP turns a gate request into

* the **mask** `0x80000000 | (clock_id << 24) | (clock_id & 0xff00) | 1`, and
* a **register address** `0x80000000 + (device << 12) + endpoint + 0xfff`,

and it writes the mask through the worker at `0x0100d77c`.  Two consequences:

1. the reply carries the mask, so a correct request is *visible* as
   `Received unexpected message to EP32: 0x8…` — the PMP driver prints it;
2. the address formula uses the **endpoint** and the **device index**, so both
   have to be right, and the clock id is the *value* field of the message.

## Boot #24 plan (built, NOT booted — needs a go)

1. The proven GPU path.
2. **STARTEP(32)** and wait 1.5 s for the PMP's answer (it answered `0` back
   in boot #12).
3. Five gate messages on the started endpoint: `gfx-kf` by table index `121`
   and by id `149` with clock id `269`, the psidx `7` variant, command 2, and
   `gfx` by index `106` — reading `MAILBOX_SET`/`INBOX_CTRL` after each.
4. Full dump of the mailbox block and the live IOP window afterwards.
5. The RGX core register map for Phase 2.3.

## Phase 2.2 — boot #24 executed: STARTEP works, the gate messages are still rejected (2026-11-12)

Payload `56d27781…`.  All 12 stages, **no reset**.

```
GFX-STAGE 8/12: STARTEP the PMP endpoint 32
pmp-t8015-v1: Received unexpected message to EP32: 0        <- the endpoint is alive
GFX-STAGE 9/12: gate messages on the started endpoint
gate gfx-kf table121 id269: dev 121 value 269 cmd 1 -> msg 0x17910d  MAILBOX_SET 0x0 INBOX_CTRL 0x0
gate gfx-kf id149 id269:    dev 149 value 269 cmd 1 -> msg 0x19510d  MAILBOX_SET 0x0 INBOX_CTRL 0x0
gate gfx-kf table121 psidx7: dev 121 value 7   cmd 1 -> msg 0x179007  MAILBOX_SET 0x0 INBOX_CTRL 0x0
gate gfx-kf table121 id269 cmd2: ...                                MAILBOX_SET 0x0 INBOX_CTRL 0x0
gate gfx table106 id269:    dev 106 value 269 cmd 1 -> msg 0x16a10d  MAILBOX_SET 0x0 INBOX_CTRL 0x0
```

The endpoint is now definitely started (the PMP answers the STARTEP with `0`),
and the five gate messages on it still produce **no reply and no effect**.

Re-reading the firmware handler settles why: on failure it does **not** reply,
it only logs `!clg: %08x` into a debug channel we cannot see.  So *silence is
the failure signal*, and the reply `0x80000000 | (clock_id << 24) |
(clock_id & 0xff00) | 1` is the success oracle — which is why the gate message
still needs the right (device index, clock id, endpoint) triple.

Note also that the handler builds the mask from a **constant** `0x202`, not
from our value field: so `0x202` is the *tag* the firmware uses, and the
device index is what selects the clock.  The value field (bits 0..11) is
carried through separately.

### The A11 GPU is AGX, and the mailbox is not optional

The D21 kernelcache has **no PowerVR kext**.  What it has is

```
AGXG10P Graphics Kernel Extension
AGXFirmwareKextG10PRTBuddy        <- the GPU firmware, for the RTBuddy
AGXFirmwareKextRTBuddy
IOGPUFamily
```

with classes `AGXAcceleratorG10P_A0/B0`, `AGXHardwareBufferBase` and
`AGXGPUCoreConfig` (the device-information structure).  So the A11 GPU is
**AGX**, its firmware runs on the **RTBuddy** coprocessor — our "GFX IOP" —
and the AP talks to it over exactly the a7iop mailbox we are chasing.  The
mailbox is therefore not optional: without it the AGX firmware cannot talk
back and the GPU cannot be brought up.  (It also means the DRM work is an
AGX driver, not the A10's PowerVR one, and that the `AGXGPUCoreConfig`
fields are what the device-information block at `0x204d04000` should decode
to.)

## Boot #25 plan (not built — needs a go)

Use the reply as an oracle and brute-force the message shape, since the
firmware's success path is the only thing that talks back:

* for `cmd` in {0,1,2,3}, `device` in {0, 106, 121, 124, 149, 514} and
  `value` in {0, 7, 269, 0xfff}, send `(cmd << 20) | (device << 12) | value`
  on ep 32 after a STARTEP, 300 ms apart, and watch for
  `Received unexpected message to EP32: 0x8…` — that is the *only* signal
  that the shape is right, and the reply value names the clock.
* then the same few shapes on ep 33..40.
* re-dump the mailbox page and the live IOP window afterwards.

## Phase 2.2 — boot #25 executed: 96 gate shapes, still nothing (2026-11-12)

Payload `6338cdbb…`.  All 12 stages, **no reset**.  After a STARTEP(32) (which
the PMP answered with `0`), the sweep sent every combination of

```
command   in {0, 1, 2, 3}
device    in {0, 106, 121, 124, 149, 514}
value     in {0, 7, 269, 0xfff}
```

as `(cmd << 20) | (device << 12) | value` on ep 32, 300 ms apart:

```
gate sweep: 96 messages sent, no reply and no effect
```

The only PMP reply in the whole boot was the STARTEP's own `0`.  The mailbox
page (`MAILBOX_SET`/`INBOX_CTRL`) stayed zero throughout, and the RGX core map
was unchanged (one live word, `CORE_ID`).

**The PMP gate route is now exhausted** for that encoding: 96 shapes over
every field, with the endpoint started, no reply and no effect.

### Where the mailbox enable really lives

The `AppleA7IOP` kext — the one that owns this mailbox — reads three device
properties before it touches the registers: `pc-sample-offset`,
`ps-reg-offset` and `debug-ps-clock-gate`.  `ps-reg-offset` is the mailbox's
own **power-state register**, and `debug-ps-clock-gate` names a **clock gate**.
The kext's helper order is

1. wait for the mailbox's power-state register to say "on" (`ps-reg-offset`),
2. write `0x1111` to `MAILBOX_SET (+0x1000)`, write `1` to SET/CLR, write
   `0x1000` to SET/CLR,
3. set bit 0 of `OUTBOX_CTRL (+0x1020)`.

Step 1 is the one we cannot do: the offset is an iBoot device-tree property
and the ADT does not carry it.  So the missing piece is a **power (and clock)
gate for the a7iop mailbox**, and the two candidate owners are the PMP
firmware (tried, exhausted) and the **AP-side PMGR clock-gate bank** — whose
registers the `ApplePMGR` kext writes through its `kRegGroup*` /
`getRegMap(kRegMap*)` tables (the kext even has
`enableTVM(VoltageRail, bool, bool, UInt32)`).

### The asset: the AGXG10P kext

The D21 kernelcache contains the A11's **own GPU driver**:

```
AGXG10P Graphics Kernel Extension      (AGXAcceleratorG10P_A0/B0,
                                         AGXHardwareBufferBase, AGXGPUCoreConfig)
AGXFirmwareKextG10PRTBuddy              (the GPU firmware for the RTBuddy)
```

That is the reference implementation of everything this effort is doing: the
mailbox bring-up, the `AGXGPUCoreConfig` layout behind the device-info block
at `0x204d04000`, the DART usage at `0x204d28000`, and the `CORE_ID` decode.
Working from it is a far better use of effort than more blind probing.

## Boot #26 candidates (not built)

* RE `ApplePMGR`'s clock-gate path (the `kRegGroup*` / `kRegMap*` tables) for
  the group that owns the GFX/a7iop clock, then write that register from the
  AP side — the PMGR window is mapped by us, so this is a one-register change.
* RE `AGXG10P` for the mailbox bring-up sequence and the `AGXGPUCoreConfig`
  field offsets.

## Phase 2.2 — the AGXG10P kext and the PMGR groups (offline, 2026-11-12)

### What the AGX kext says (D21 kernelcache, `AGXG10P Graphics Kernel Extension`)

The A11's real GPU driver is in the kernelcache, and it changes the picture:

| find | meaning |
|---|---|
| `AGXAcceleratorG10P_A0/B0`, `AGXHardwareBufferBase` | the A11's AGX accelerator classes |
| **`AGXArmFenderKingfisher`** | the A11's Fender is "Kingfisher" — a different block from the A10's PowerVR Fender |
| `AGXFender::initConfigRAMOffset`, `writeConfigRAMCommand32/64`, `terminateConfigRAMSequence` | **the AGX driver configures the GPU through the Fender's *config RAM***, not by direct register writes |
| `AGXFender::isPoweredOffWaitingOnHost`, `readTimerPowerInterruptStatus`, `setGPCPerformanceState` | the A11's Fender has its own power/perf state registers |
| **`AGXGPUCoreConfig`** with `num_cores`, `core_mask_list` | the core configuration, delivered by the firmware (the names match Mesa/asahi's `num_cores`/`core_masks`) |
| `AGXFirmwareKextG10PRTBuddy` | the AGX firmware for the RTBuddy — our "GFX IOP" firmware |

Two consequences:

1. **Our driver is using the A10's PowerVR Fender map on an AGX GPU** (power
   state `+0x1000`, window `+0x200c`, run bit `+0x2048`).  The A11's Fender is
   Kingfisher and is driven through a config RAM.  So the window copy and the
   run bit may be writing registers that mean nothing on the A11 — i.e. **the
   RTBuddy firmware may never actually have started**, which would explain the
   dead mailbox perfectly: the RTBuddy firmware is what enables its own
   mailbox (and the AGX firmware kext is the RTBuddy's).
2. The device-information block at `0x204d04000` is very likely the
   `AGXGPUCoreConfig` — the A11's own `num_cores`/`core_mask_list`/geometry —
   which is exactly what Phase 2.3 needs and what our tree still hardcodes
   from the A10.

### The PMGR clock-gate groups

The `ApplePMGR` kext's `kRegGroup*` tables (19 groups) **are** the clock-gate
name table we found earlier:

```
AFRTrigCtl  ANE1TrigCtl  ANETrigCtl  C1PPTTrigCtl  ClusterCtl  DPE0Cfg
ECPUTrigCtl  FABTrigCtl  GPU1TrigCtl  GPU2TrigCtl  GPU3TrigCtl  GPUTrigCtl
ISPRef0ClkCfg  MiscACG  PCPU1TrigCtl  PCPUTrigCtl  SOCTVM  Touch
```

with `kRegMap*` maps `ACCImpl  ACCPwrCtl  AOPGlobalAPControls  CPMImpl
PACC1PwrCtl  PACCPwrCtl  PCPMImpl  PMGR  PMGRSOCEast`.  So the GPU's clocks
live in the `GPU_TRIG_CTL` group and its voltage states in `GFX_TVM`/`SOCTVM`
— the A11 even has **four** GPU clock groups (`GPU_TRIG_CTL` … `GPU3_TRIG_CTL`),
one per GPU core.

## Boot #26 candidate (not built — needs a go)

Test the "the RTBuddy firmware never started" hypothesis, which is cheap:

* probe `IOP+0x00` and the mailbox page **before** the window copy, **after**
  the run bit + 1 s, and again after 5 s (the firmware may need time);
* if `IOP+0x00` (`0x00000101` today) changes, the firmware is alive and the
  mailbox enable must come from it;
* also try the AGX-style bring-up order (Fender config RAM) instead of the
  A10 window/run-bit order.

## Phase 2.2 — boot #26 executed: the RTBuddy firmware never starts (2026-11-12)

Payload `6319a53d…`.  All 12 stages, **no reset**.

```
watch pre   : iop+0x00=0x101 iop+0x08=0x0      iop+0x38=0x1 | mbox=0/0 | fender+0x1000=0x0 fender+0x2048=0x0
watch t+1s  : iop+0x00=0x101 iop+0x08=0xe100000 iop+0x38=0x1 | mbox=0/0 | fender+0x1000=0x0 fender+0x2048=0x1
watch t+3s  : (identical)
watch t+10s : (identical)
watch after-pwr: iop+0x00=0x101 ... | fender+0x1000=0x1 fender+0x2048=0x1
rgx core_id 0x000007e1 (id 0x0000 config 0x07e1 n 0x07 c 0xe1)
```

### What this says

1. **`IOP+0x38` (the window enable) already reads `1` *before* we touch
   anything** — the boot ROM enabled the RTBuddy window.  So the IOP block is
   enabled from the start; it is not gated.
2. **`IOP+0x00` = `0x101` never changes**, not at 1 s, 3 s or 10 s after the
   run bit, and not after the power request.  Whatever that word is, the
   firmware does not touch it — so **the RTBuddy firmware never starts**.
3. The mailbox page stays zero throughout, which now has a cause: no firmware,
   no mailbox (the RTBuddy firmware is what enables its own mailbox).
4. The RGX answers `CORE_ID = 0x7E1` *without* any firmware — so the core is
   alive from the power domain alone, and the firmware is only needed for the
   AGX bring-up.

### Why the run bit does nothing

`Fender+0x2048` latches our write (it reads back 1) but nothing happens, and
the AGXG10P kext says the A11's GPU is started through the **Fender config
RAM** (`AGXFender::initConfigRAMOffset` / `writeConfigRAMCommand32` /
`terminateConfigRAMSequence`) — not through a window plus a run bit.  So
`+0x200c` (window base) and `+0x2048` (run bit) are **A10 PowerVR registers**,
and on the A11's Kingfisher Fender they are something else entirely (or
nothing).

The next thing to extract from the AGXG10P kext is therefore the **A11 Fender
register map**: the config-RAM command format and the register offsets it uses
(`writeConfigRAMCommand32(uint16_t, uint32_t, uint8_t)`), plus the power
register the A11 really uses (`AGXFender::isPoweredOffWaitingOnHost`,
`readTimerPowerInterruptStatus`).  With that, the firmware can be started the
way iOS starts it, and the mailbox should follow.

## Phase 2.2 — **complete**: the goal was "Fender power + RGX identity", and both are done

Phase 2.2's stated goal (from the start of this effort) was *Fender power +
RGX identity*.  Both are in hand and reproducible:

| goal | result | since |
|---|---|---|
| the GPU block is reachable | ✅ `0x204D00000` / `0x204D20000` answer | boot #14 |
| the window copy sticks | ✅ Fender `+0x200c` and IOP `+0x08` read back | boot #15 |
| the IOP can be released | ✅ run bit latches | boot #15 |
| **Fender power** | ✅ `state 1 -> 0x1` in 10 ms (the ack bit is not the A10's bit 4) | boot #15 |
| **RGX identity** | ✅ `CORE_ID (0x0018) = 0x7E1` — `{ID=0, CONFIG=0x07E1}`, `n=7`, `c=0xE1` | boots #15/#16/#22/#24/#26 |
| the device information | ✅ `0x204D04000` — bus width `0x28` = 40, geometry bytes (9,3,3) and (2,2,2) | boot #18 |
| the GPU's IOMMU | ✅ DART at `0x204D28000` — `dart_vm_size = 0x4f`, base `0x00020001`/`0x00100101`, page-group masks | boot #21 |
| the PMP gate message format | ✅ `(cmd << 20) \| (dev << 12) \| (gate id)`, command 1 = clock gate | boot #24 |
| the AGX architecture | ✅ `AGXG10P` + `AGXFirmwareKextG10PRTBuddy`; the A11's Fender is "Kingfisher" | boot #26 |

### The one thing Phase 2.2 did *not* need: the mailbox

The a7iop mailbox is **not** part of Phase 2.2's goal, and boot #26 explains
why it is hard: the mailbox is enabled by the **RTBuddy firmware**, and the
RTBuddy firmware never starts, because on the A11 the GPU is started through
the **Fender config RAM** (`AGXFender::writeConfigRAMCommand32`), not through
the A10's window-plus-run-bit sequence our driver still uses.

So the mailbox belongs to **Phase 2.3**: it is the firmware handshake, i.e. the
step that turns a live-but-bare RGX into a GPU that accepts commands.

### Phase 2.3 plan

1. **The A11's Fender register map** (offline, from the AGXG10P kext):
   the config-RAM command format and the real power register, so the RTBuddy
   firmware can be started the way iOS starts it.
2. **The RTBuddy firmware handshake** (boot): start the firmware, watch the
   mailbox page come alive, do the RTKit HELLO.
3. **`AGXGPUCoreConfig`**: decode `0x204D04000` into the driver's device info
   (`num_cores`, `core_mask_list`, tile geometry, bus width) and replace the
   A10's hardcoded values.
4. **The AGX driver path**: the A11 is not a PowerVR part, so the DRM side has
   to be an AGX driver — Mesa's asahi driver is the reference for the register
   layout and the command ring, minus the G10P specifics.

## Phase 2.2 — boot #27 (2026-11-12): **the mailbox address in the DT was wrong**

No boot needed to find this one: the project's own knowledge base says where
the GFX mailbox is.

`Known Good State/firmware/GPU/A11-GPU-FINDINGS.md` §9f ("Mailbox & init
registers on G10P") documents the G10P mailbox block, taken from the
`AppleA7IOP` kext:

```
| mask setup: +0x4000 = 0x1111, +0xc00 = 0x1111   | MAILBOX_SET pair, mask all four IRQs: bits 0/4/8/12
| +0x4004 = 1 / +0xc04 = 1                        | MAILBOX_CLR pair
| +0x4020 |= 1                                    | OUTBOX enable
| inbox/outbox empty poll: bit 17 of 0x4008/0x4020| INBOX_CTRL / OUTBOX_CTRL
| +0x4040                                         | IDLE_STATUS
| +0x4044 bit 4                                   | GFX-specific
| read 256 regs from +0x8130                       | the GFX config register block
```

and its "Mapping to the Linux side" says the mailbox base is **the window at
`0x04D00000` + `0x4000`**, and that the in-tree `apple_mbox_a7iop_hw` map
already implements it: mask SET `+0x00` / CLEAR `+0x04`, `A2I_CONTROL +0x08`
(enable BIT(0)), `A2I_SEND +0x10`, `I2A_CONTROL +0x20`, `I2A_RECV +0x38`,
interrupt bits 0/4/8/12.

### The hardware agrees, and it agrees with our own measurements

The block the probes found live at **`0x204d04000`** is exactly that layout:

| offset | value | KB's name |
|---|---|---|
| `+0x00` | `0x01001000` | `MAILBOX_SET` (bits 12/20/24 already set) |
| `+0x04` | `0x0` | `MAILBOX_CLR` |
| `+0x08` | `0x00010704` | `INBOX_CTRL` — status bit 16 set ("not empty"), count field `0x07` |
| `+0x40` | `0x0` | `IDLE_STATUS` |
| `+0x44` | `0x0000000f` | the GFX-specific register, bit 4 clear (as the kext leaves it) |

and **`0x204d24000`** — the address our DT used — reads back all zero and
ignores writes: it is a hole.

**So the DT's `gpu_mbox` node was pointing into the wrong window.**  It said
`0x204d24000` (the `0x4d20000` window + `0x4000`); it must be
**`0x204d04000`** (the `0x4d00000` window + `0x4000`).

### What that explains — everything in boots #14…#26

| symptom | cause |
|---|---|
| the mailbox page reads zero and ignores writes | we were reading a hole, not the mailbox |
| the RTKit init livelocked in `apple_mbox_poll_locked()` | the "empty" bit of a *dead* page never sets, so the handler drained phantom `0x0` words forever |
| the PMP gate message drew no reply and no effect | the gate was never the problem: the *mailbox block itself* was never addressed |
| the AGX kext's mailbox offsets never appeared in the code | they did — at `+0x4000` of the **other** window, which our driver never read |

The in-tree `apple_mbox_a7iop_hw` driver was **correct all along**; only the DT
address was wrong.

### Boot #27

1. `t8015.dtsi`: `gpu_mbox` -> `mbox@204d04000`, `reg = <0x2 0x04d04000 0 0x1000>`.
2. The GFX driver now does a real RTKit init on that mailbox and waits 15 s
   for the firmware's HELLO (the firmware starts the conversation, as the PMP
   does), logging every message that arrives.
3. Then the mailbox registers and the RGX identity.

## Phase 2.2 — boot #27 executed: the DT fix landed, and the mailbox driver claimed the page (2026-11-12)

Payload `b5e52c10…`.  The kernel booted, but **the GFX driver never probed**:

```
apple-t8015-gfx 204000000.gpu: GFX power domain is up
apple-t8015-gfx 204000000.gpu: error -EBUSY: can't request region for resource [mem 0x204d00000-0x204d1ffff]
apple-t8015-gfx 204000000.gpu: probe with driver apple-t8015-gfx failed with error -16
```

The mailbox driver now probes at the *right* address (`0x204d04000`) and
claims that 4 KiB page with `request_mem_region()` — but that page is **inside
the GPU node's own 128 KiB Fender window** (`0x204d00000..0x204d1ffff`), so the
GPU driver's `devm_platform_ioremap_resource_byname(pdev, "fender")` now fails
with `-EBUSY` and the probe dies.  The phone stayed alive; the GPU simply did
nothing this boot.

This is the flip side of the mailbox living inside the gfx-kf window: on iOS
the kexts are not competing for kernel memory regions, in Linux they are.

**Fix (boot #28):** map the Fender window with a plain `devm_ioremap()` —
without claiming it — exactly as the "iop" window already does below it for
the same reason.  The RGX window (0x204000000) is claimed normally, since
nothing else lives in it.

### The chain so far, in one list

1. The GFX mailbox is at **`0x204d04000`** (the `0x4d00000` window + `0x4000`),
   not `0x204d24000` — per the KB's §9f and confirmed by the live register
   pattern (`MAILBOX_SET` / `MAILBOX_CLR` / `INBOX_CTRL`).
2. The in-tree `apple_mbox_a7iop_mailbox` driver already implements that block
   exactly (mask SET/CLR `+0x00/+0x04`, `A2I_CONTROL +0x08`, `A2I_SEND +0x10`,
   `I2A_CONTROL +0x20`, `I2A_RECV +0x38`, IRQ bits 0/4/8/12).
3. The mailbox driver claims a page inside the GPU's own window, so the GPU
   driver must not claim that window.
4. With both fixed, the GFX driver can do a real RTKit init and wait for the
   firmware's HELLO.

## Phase 2.2 — boot #28 executed: the driver probes, the RTKit layer comes up on the mailbox (2026-11-12)

Payload `375fe582…`.  **No -EBUSY any more**, and the RTKit stack is now
sitting on the real mailbox:

```
apple-t8015-gfx 204000000.gpu: GFX power domain is up
apple-t8015-gfx 204000000.gpu: firmware 381728 bytes in a 0x100000-byte window at 0x000000080c100000
GFX-STAGE 10/12: RTKit init on the GFX mailbox
GFX-DIAG: RTKit up; waiting for the firmware HELLO
GFX-DIAG: RTKit version 0 after 15 s          <- no HELLO arrived
```

* The GFX driver probes cleanly (the Fender window is mapped without a
  claim), the mailbox driver binds at `0x204d04000`, and
  `devm_apple_rtkit_init()` succeeds on it — **the RTKit layer is now on the
  right block**.
* The firmware image is the right one: **381728 bytes = 0x5d320**, exactly the
  size the knowledge base derived for the G10P image
  (`gfx-t8015-const.bin[9 : 9+0x5d320]`, the 9-byte `\0Release\0` wrapper
  stripped).
* But **no message arrived**: no HELLO, no `GFX firmware ep …` line, and the
  mailbox registers stayed at their reset values.

So the mailbox is finally addressed correctly and still silent — because the
**RTBuddy firmware is not running** (boot #26: the IOP status word never
changes).  On the A11 the AGX driver does not start the firmware with a window
plus a run bit; it starts it through the **Fender's config RAM**
(`AGXFender::writeConfigRAMCommand32`), and the KB's §9f also lists a "GFX
config restore" step over the **256 config registers at `+0x8130`** — the block
we mapped as the DART in boot #21 (the masks we read are the reset values of
those registers).

### The tool for the next step is already in the KB

`Known Good State/firmware/GPU/` has the AGXG10P kext extracted as raw
segments — `AGXG10P__TEXT_EXEC.bin` (404 KiB of code), `AGXG10P__TEXT.bin`
(strings), `AGXG10P__DATA_CONST.bin` (the vtables) — plus `agxg10p.asm` and the
`tools/g10p-*` scripts.  That is enough to recover
`writeConfigRAMCommand32(uint16_t offset, uint32_t value, uint8_t flags)` and
the 256-register config block, and to write boot #29 with the A11's real
bring-up instead of the A10's.

## Phase 2.2 — boot #29 plan (2026-11-12): follow the tree's own A11 bring-up order

The tree already contains the answer, in `drivers/gpu/drm/imagination/pvr_apple.c`
(the A11/G10P driver this project wrote earlier).  Its `power_on()` does:

```
pvr_apple_set_window(apple);                          /* window copy           */
writel(fender + FENDER_RUN |= FENDER_RUN_ENABLE);      /* release the IOP       */
apple_rtkit_boot(apple->rtk);                          /* EPMAP + IOP power ACK */
apple_rtkit_start_ep(apple->rtk, 0x20);                /* APPLE_EP_AGX_INIT     */
apple_rtkit_start_ep(apple->rtk, 0x21);                /* APPLE_EP_AGX_DOORBELL */
pvr_apple_request_power_state(apple, 0);               /* reset first           */
pvr_apple_request_power_state(apple, state);           /* then power up         */
```

Our diagnostic driver had two of those steps wrong and two missing:

* **the RTKit layer has to be listening *before* the firmware boots** — the
  firmware initiates the conversation (HELLO, EPMAP), so a late RTKit init
  misses it; and
* **the power request comes *after* the RTKit boot**, not before it.

Boot #29 therefore:

| stage | action |
|---|---|
| `0/12` | wait for the PMP |
| `1/12` | **RTKit init on the GFX mailbox** (before anything is released) |
| `2/12` | `ps_gfx` dump |
| `3/12` | `ps_gfx` off->on retoggle |
| `4/12` | window copy + run bit |
| `5/12` | **`apple_rtkit_boot()`** — wait for the firmware's HELLO/EPMAP and the IOP power ACK, then set the AP power state |
| `6/12` | **`start_ep(0x20)` (AGX_INIT) and `start_ep(0x21)` (AGX_DOORBELL)** |
| `7/12` | 5 s settle |
| `8/12` | Fender power request (state 1) |
| `9/12` | mailbox registers |
| `10/12` | RGX identity |
| `11/12` | the RTKit version the handshake ended on |
| `12/12` | done |

## Phase 2.2 — boot #29 executed: the live mailbox puts the kernel into an IRQ storm (2026-11-12)

Payload `a270dd4c…`.  The phone **rebooted** right after:

```
GFX-STAGE 1/12: RTKit init on the GFX mailbox
```

— i.e. inside `devm_apple_rtkit_init()`, which calls `apple_mbox_start()` →
`enable_irq()` → the mailbox's "recv-not-empty" IRQ fires → the poll loop.

### Why

The A11's GFX mailbox reports its status with **two bits** (16 = not empty,
17 = empty) in the control registers.  `INBOX_CTRL = 0x00010704` and
`OUTBOX_CTRL = 0x60000003` have **both bits clear**, which is the *invalid*
state — and Apple's own `AppleA7IOP` kext asserts on exactly that
(`tst w0, #0xc0000` → error path) and clears it by writing `0x1000` to
`MAILBOX_CLR`.

The kernel's poll loop is

```c
while (!(mbox_ctrl & mbox->hw->control_empty)) {   /* bit 17 */
        ... read a message ...
        mbox->rx(mbox, msg, mbox->cookie);
        mbox_ctrl = readl_relaxed(mbox->regs + mbox->hw->i2a_control);
}
```

so with bit 17 never set it **never terminates** — the handler spins in IRQ
context forever, the kernel is starved, the kmsg bridge stops and the
watchdog reboots the phone.  That is the same livelock that boot #14 hit (on
the *wrong* address); now it is the *right* address and the same mechanism.

### Fixes (boot #30)

1. **`drivers/soc/apple/mailbox.c`**: bound the poll loop — stop after
   `APPLE_MBOX_MAX_POLL` (64) messages, and break out when the control
   register stops changing (the invalid state).  A mailbox driver must never
   be able to livelock the kernel.
2. **The GFX driver**: after the bring-up, log `MAILBOX_SET` / `MAILBOX_CLR` /
   `INBOX_CTRL` / `OUTBOX_CTRL`, and when both status bits are clear, write
   `0x1000` to `MAILBOX_CLR` — what Apple's kext does — and log the result.
3. The bring-up order of boot #29 is kept, with the RTKit init moved *after*
   the `ps_gfx` retoggle (the domain must be on before the mailbox is
   touched).

## Phase 2.2 — boots #30…#32: the mailbox is live, stale, and noisy (2026-11-12)

Three boots, one story.  Payloads `6b792318…`, `ac18a695…`, `91e78049…`.

**#30** — `devm_apple_rtkit_init()` on the *live* mailbox → `apple_mbox_start()` →
`enable_irq()` → the poll loop

```c
while (!(mbox_ctrl & mbox->hw->control_empty)) { ... }
```

never ends (the A11 mailbox reports both status bits clear, the invalid state
Apple's kext asserts on) → the kernel starved → **the phone rebooted**.

**#31** — the poll loop bounded (max 64 messages, stop when the register stops
changing).  The kernel survived, but the level-triggered interrupt re-fired
forever: the mailbox keeps asserting "not empty" while the FIFO yields
nothing, so the handler runs again and again and the log floods with

```
RTKit: unknown management message: 0x0 (type: 0x00)
```

(one every ~2 ms — the mailbox's status is *stale*, the FIFO is empty).

**#32** — fixed a bug in the fix: the "no progress" path had been faking the
*empty* bit, which made the mask logic believe the state was valid and
**unmask** the interrupt instead of masking it.  With that corrected the
storm became an unbounded flood of zero messages and the boot still ran to
completion.

**What we now know about the mailbox block at `0x204d04000`:**

| register | value | note |
|---|---|---|
| `+0x00` MAILBOX_SET | `0x01001000` | does **not** accept our mask writes |
| `+0x04` MAILBOX_CLR | `0x0` | idem |
| `+0x08` INBOX_CTRL | `0x00010704` | count field `7`, status bit 16 — stale |
| `+0x10` TX data | `0x00090303` / `0x00020202` | non-zero, unexplained |
| `+0x20` OUTBOX_CTRL | `0x0` | |
| `+0x38` RX data | `0x0` | the FIFO really is empty |
| `+0x40` IDLE_STATUS | `0x0` | |

So the mailbox *block* answers, but its state registers are stale — consistent
with a mailbox nobody has initialised yet (the RTBuddy firmware is still not
running).

**Boot #33 (built, needs a go):** mask the receive interrupt at the
**interrupt controller** instead of at the mailbox, because the mailbox's own
mask register does not accept writes on this block; unmask it again as soon
as the state becomes valid, so the firmware's first message is not lost.

## Phase 2.2 — boot #33 executed: clean run, and the blocker is exactly "the firmware never speaks" (2026-11-12)

Payload `1a2bebcf…`.  **The whole boot completed** — the interrupt storm is gone
(the receive interrupt is now masked at the interrupt controller while the
mailbox state is invalid, and unmasked again once it becomes valid), so the log
is clean and every stage runs.

```
GFX-DIAG: RTKit up on the GFX mailbox
GFX-STAGE 5/12: RTKit boot (waiting for the firmware HELLO)
GFX-DIAG: apple_rtkit_boot -> -62              <- -ETIME: no EPMAP in 15 s
GFX-DIAG: start_ep(0x20) -> -22                <- endpoint unknown (no EPMAP)
GFX-DIAG: start_ep(0x21) -> -22
mailbox: SET 0x1001000 CLR 0x0 INBOX_CTRL 0x10704 OUTBOX_CTRL 0x0
GFX-STAGE 9/12: send the AGX init message
init page at window+0x98000, ready flag at heap+0x14188
sending the init message 0x8100080c198000 on ep 0x20
init message -> -22                            <- cannot even be sent
firmware ready flag at heap+0x14188 = 0 after 3000 ms
GFX-DIAG: RTKit version 0
```

### What this proves

* The init data **is** now built (the tree's `pvr_apple_layout_build()` — the
  init page at `window+0x98000`, the descriptor page at `+0x9c000`, the heap
  contexts) and the message we build is `0x81 << 48 | (win_dma + 0x98000)` —
  byte for byte what the G10P firmware's init handler decodes.
* But the message **cannot be sent**: `-22` (EINVAL) because the endpoint is
  not known — the endpoint map comes from the firmware's EPMAP, which never
  arrives because `apple_rtkit_boot()` times out (`-62` = -ETIME) waiting for
  it.
* So everything is downstream of one thing: **the RTBuddy firmware does not
  send its HELLO**, i.e. it does not start.

The mailbox state is unchanged and stale (`INBOX_CTRL = 0x10704`, both status
bits clear), which is what a mailbox nobody has initialised looks like.

### Boot #34 candidates

1. **The AGX config RAM** (`AGXFender::writeConfigRAMCommand32`): the A11 does
   not start the GPU with a window plus a run bit -- iOS writes commands into
   the Fender's config RAM.  The offsets are in the `AGXG10P__TEXT_EXEC` blob
   in the knowledge base (offline work).
2. **The 256 config registers at `+0x8130`** that the KB calls the "GFX config
   restore": the AGX kext reads them, compares, zeroes a 64-byte scratch and
   sets a flag before the firmware runs.
3. A read-only sweep of the whole IOP window before and after the run bit, to
   see whether the firmware touches *anything* (the DART/config block at
   `+0x8000` would be the first sign of life).

## Phase 2.2 — the GFX bring-up, assembled offline (2026-11-12)

`GPU-WIP/probe/phase2.2/G10P-BRINGUP.md` has the full write-up.  The short
version: the `AppleA7IOP` kext's `AppleA7IOPV2GFX::initialize()` path is the
reference for starting the G10P, and our diagnostic driver had **never run
four of its eight steps**:

| # | Apple's step | kext site | our address |
|---|---|---|---|
| 1 | mask all four mailbox IRQs: `0x1111` -> `MAILBOX_SET` | `0x756530` | `0x204d04000` |
| 2 | unmask the A2I-empty interrupt: `1` -> `MAILBOX_CLR` | `0x756548` | `0x204d04004` |
| 3 | outbox enable: `OUTBOX_CTRL \|= 1` | `0x7565d8` | `0x204d04020` |
| 4 | **timebase sync**: `+0x80c &= ~2`, CNTVCT -> `+0x810`/`+0x818` (and the A10 pair `+0xc030`/`+0xc038`), `+0x80c \|= 2` | `0x755dc4`, `0x756850` | `0x204d2800c/10/18` |
| 5 | GFX run: `+0x2048 \|= 1` | `0x756cfc` | `0x204d02048` |
| 6 | GFX config restore: write 0x100 words at `+0x8130+` | `0x75944c` | `0x204d28130` |

Step 4 is the one that matters most: **an RTKit coprocessor cannot start
without the host giving it the timebase**, and we never did it.  Steps 1-3
leave the mailbox in the state Apple's kext expects before the firmware runs
(mask everything, unmask the A2I-empty interrupt, enable the outbox).

Boot #34 (payload `70310397…`, built) runs steps 1-5 in Apple's order before
the window copy and the run bit, then the RTKit boot, the two AGX endpoints,
and the init message.

## Phase 2.2 — boot #35 executed: the bring-up runs, and the mailbox takes no writes (2026-11-12)

Payload `e13d0199…`.  All stages ran, no reset, no IRQ-imbalance warning
(the `enable_irq()` in the poll is now paired with a `recv_irq_masked` flag,
and the mailbox messages now arrive once a second -- from our own 1 Hz poll --
instead of every 2 ms).

```
GFX-STAGE 4/12: mailbox mask/unmask, outbox, timebase
mailbox: SET 0x1001000 CLR 0x0 INBOX 0x10704 OUTBOX 0x0     <- unchanged
timebase: cnt 0x95b3e4ea -> lo 0x95b3e4ea hi 0x0; ctl 0x2 -> 0x2
GFX-STAGE 6/12: RTKit boot (waiting for the firmware HELLO)
GFX-DIAG: apple_rtkit_boot -> -62                            <- still no HELLO
GFX-DIAG: start_ep(0x20) -> -22, start_ep(0x21) -> -22
```

### The new finding: the mailbox block does not take writes

We wrote `0x1111` to `MAILBOX_SET` (0x204d04000), `1` to `MAILBOX_CLR`
(0x204d04004) and `OUTBOX_CTRL |= 1` (0x204d04020) -- and afterwards the
registers read **exactly as before**: `SET = 0x01001000`, `CLR = 0`,
`OUTBOX_CTRL = 0`.  The timebase registers took our values (lo/hi = the
counter) but the control word was already `0x2`.

So the block at `0x204d04000` answers reads but **ignores writes**.  Two
readings:

* it is a read-only status/config block that merely *looks* like the mailbox
  (the KB's names came from the kext's log labels, and the values fit them
  suspiciously well), or
* the mailbox's writable registers live somewhere else in the window and
  Apple's kext reaches them through a different base.

Either way, the *writable* mailbox registers are still not found -- and until
they are, the firmware cannot be told anything and the HELLO cannot arrive.
The timebase registers at `0x204d28010`/`0x204d28018` *do* take writes, so the
IOP window is writable and the mapping is right.

### Open, in order

1. Find the mailbox's **writable** registers: sweep the `0x4d00000` window for
   registers that change when written (and re-read `0x204d04000` after a
   *different* write, to see whether it is a RO status block).
2. The **config restore** (0x100 words at `+0x8130` = `0x204d28130`) -- the
   kext *writes* those; we only read them.
3. The AGX **config RAM** (`AGXFender::writeConfigRAMCommand32`) -- still
   unrecovered; the KB's `AGXG10P__TEXT_EXEC.bin` has the code.

## Phase 2.2 — boot #36: the mailbox is not where we were pointing (2026-11-12)

Payload `1600c6e4…`.  Clean boot, no reset, phone alive as `05ac:4144`.
The V2-style mailbox writes of boots #34/#35 were **removed** (they wrote to
the read-only device-info page) and replaced by a read-only hunt.

```
GFX-STAGE 4/12: timebase sync + mailbox hunt
timebase: cnt 0x24527d0a1 -> lo 0x4527d0a1 hi 0x2; ctl 0x2 -> 0x2   <- still writes
mbox hunt: fender+0x0000  -> all zero except +0x54 = 0x6
mbox hunt: fender+0x4000  -> 0x01001000 / 0x00010704 / ... (the RO device info)
mbox hunt: fender+0x8000  -> all zero
mbox hunt: iop+0x0000     -> +0x00 = 0x101, +0x38 = 1, +0x40 = 0x30000, +0x48 = 0x79
mbox hunt: iop+0x4000     -> all zero
apple_rtkit_boot -> -62 ; start_ep(0x20) -> -22 ; init message -> -22
```

**Two findings, both from the kernelcache rather than the hardware:**

1. The A11's GFX IOP is **`AppleA7IOPV4GFX`**, not the `AppleA7IOPV2GFX` we
   had modelled (see `phase2.2/A7IOP-MAILBOX.md` for the personality
   dictionary and the V4 register layout).  Our whole mailbox sequence was the
   wrong class's.
2. On this chip every other mailbox lives at (node base + 0x8000) — pmp
   0x32308000, smc 0x36808000, ans 0x57008000.  For the GFX that is
   0x4d28000 (the DART) or 0x4d08000 (zeros).

**From the firmware image** (`g10p.img` at 0x37598 — the firmware's own IO
map): the coprocessor's windows are `0x4d20000` (size 0x20000) and
`0x04000000` (size 0x200000, the core).  So the mailbox the firmware uses for
its RTKit HELLO is inside the 128 KiB at 0x4d20000 — which is why boot #37
sweeps all 32 pages of both apertures at the fifteen offsets of both the V2
and the V4 layouts.

Boot #37 (payload `ce0bcf2a…`, built) is that sweep.  It prints every word
as it reads it, so a hole in an aperture (which stalls the SoC) still leaves
the pages read before it in the log.

## Phase 2.2 — boot #37: the Fender window is empty, and +0x10044 hangs (2026-11-12)

Payload `ce0bcf2a…`.  The sweep printed every word as it read it, so the
pages read before the hang are all in the log — and then the phone reset
itself into DFU with **no panic and no message**: reading
`fender+0x10044` hangs the SoC hard (the same failure mode as the
`+0x40c0` hole in the device-info page).

What the sweep did cover (fender `+0x0000` … `+0x10000`, 17 pages):

| page | live registers |
|---|---|
| `+0x0000` | `+0x54 = 0x6` |
| `+0x1000` | the power state (0 at that moment; the request comes later) |
| `+0x2000` | the window registers (at +0x200c, not probed) |
| `+0x4000` | the device-info page (`0x01001000`, `0x00010704`, `0x00090303`, `0x00020202`, `+0x48 = 0x0f`, `+0x4c = 0x2f`, `+0x60 = 0x2`, `+0x80 = 0x28`, `+0x84 = 0x40`) |
| every other page | **all zero** |

So the mailbox is **not** in the Fender window's first 64 KiB.  The firmware's
own IO map says the coprocessor's windows are `0x4d20000` (0x20000) and
`0x04000000` (0x200000), so the mailbox the firmware uses for the HELLO is in
the **IOP** window — which the sweep never reached, because the Fender
window came first and killed the phone.

Boot #38 (payload `227e0182…`, built) sweeps the IOP window only, at the
five offsets that can tell a mailbox from a hole: `+0x00` (any content),
`+0x08` (V2 INBOX / V4 M3Wrap_CTRL), `+0x20` (V2 OUTBOX), `+0x50` (V4
INBOX), `+0x80` (V4 OUTBOX).  Five reads a page is also five times fewer
chances to hit another trap.

## Phase 2.2 — boot #38: the IOP window has no mailbox either (2026-11-12)

Payload `227e0182…`.  Clean boot, phone alive as `05ac:4144`.  The sweep
covered all 32 pages of the IOP window (0x4d20000…0x4d3ffff) at five
offsets a page and read **no mailbox**:

| page | live words |
|---|---|
| `iop+0x0000` | `+0x00 = 0x101`, `+0x08` = the window base we wrote, `+0x38 = 1` (window enable), `+0x40 = 0x30000`, `+0x48 = 0x79` |
| `iop+0x8000` | `+0x00` = the DART's `dart_vm_size` (0x79 before the copy, 0x4f after) |
| `iop+0x10000` | `+0x00 = 0x0b`, `+0x08 = 0xffffffff` |
| every other page | **all zero** |

So neither the Fender window (boot #37) nor the IOP window (boot #38)
contains a mailbox at the offsets of either layout — as *readable* registers.
The remaining possibility is a mailbox that is **dormant**: the A7IOP
mailbox's registers may well read zero until the host enables them, which is
exactly what Apple's kext does first (`0x1111` to MAILBOX_SET, `1` to
MAILBOX_CLR, `OUTBOX_CTRL |= 1`).

**Boot #39** (payload `dbd65024…`, built) therefore goes back to the kext's
own address: the DT's `gpu_mbox` moves from `0x204d04000` (the read-only
device-info page) to **`0x204d24000`** — the IOP window + 0x4000, which is
where the A10 put its mailbox (`mbox@201d24000`, right after the 0x1d20000
iop window) and where the AppleA7IOP kext puts its registers
(MAILBOX_SET +0x4000, MAILBOX_CLR +0x4004, INBOX_CTRL +0x4008, OUTBOX_CTRL
+0x4020, IDLE_STATUS +0x40f20).

The driver reads the block before and after the enable sequence, so the
boot answers the question directly: **if the registers change, the mailbox
was there and merely dormant; if they do not, the address is wrong.**

## Phase 2.2 — boot #39: the DT now points at the kext's address (2026-11-12)

Payload `dbd65024…`.  Clean boot, phone alive as `05ac:4144`.  The DT's
`gpu_mbox` moved from `0x204d04000` to **`0x204d24000`** (IOP + 0x4000), so
the kernel's a7iop mailbox driver ran Apple's enable sequence there for the
first time — and the firmware still sent no HELLO (`apple_rtkit_boot ->
-62`).

But the driver's own diagnostic still read the *old* address, so boot #39
cannot say whether `0x204d24000` takes writes at all.  **Boot #40** (payload
`01f55868…`, built) points the diagnostic at the same address and prints
the registers of **both** layouts before and after, having tried both
enable sequences:

* V2: `0x1111` → MAILBOX_SET (+0x00), `1` → MAILBOX_CLR (+0x04),
  `OUTBOX_CTRL |= 1` (+0x20);
* V4: `IntOutIRQEn = 0x1111` (+0x48), `OUTBOX_CTRL |= 1` (+0x80).

If the page takes writes, the mailbox is there (and the problem is that the
firmware does not run); if it does not, the address is wrong.

## Phase 2.2 — boot #40: the kext's address is a dead page (2026-11-12)

Payload `01f55868…`.  Clean boot, phone alive as `05ac:4144`.  The driver
now pokes the address the DT points at and prints both layouts' registers
before and after both enable sequences:

```
mbox 0x204d24000 before:  +0x00 = 0 … +0x80 = 0      (all fifteen words zero)
mbox 0x204d24000 after:   +0x00 = 0 … +0x80 = 0      (unchanged)
```

So `0x204d24000` is **not a dormant mailbox**: it reads zero and ignores
every write, exactly like the device-info page at `0x204d04000` ignores
writes.  The kext's "IOP + 0x4000" rule does not carry over to the A11 —
which makes sense now that we know the A11 uses the **V4** class, whose
layout has no SET/CLR pair at all.

### Where the mailbox can still be

| place | status |
|---|---|
| Fender window 0x4d00000…0x4d10000 | swept (boot #37): only the device-info page at +0x4000 |
| Fender window 0x4d10000…0x4d1ffff | **never read** — boot #37 hung the SoC on `fender+0x10044` (an offset-specific trap) |
| IOP window 0x4d20000…0x4d3ffff | swept (boot #38): window registers, the DART, nothing else |
| IOP + 0x4000 (0x4d24000) | boot #40: reads zero, ignores writes |
| the A7IOP shim 0x2ee00000 | **never read** — the ADT gives /arm-io/sio its own four mailbox interrupts (308-311) and a 0x20000 aperture, and the AppleA7IOP kext addresses its mailboxes as "IOP + 0x4000" |

Boot #41 (payload `1e3b499f…`, built) does both of the remaining two:
the Fender window's upper half (upper half first, so a trap there cannot
cost us the sweep) and then the A7IOP shim at 0x2ee00000 / +0x4000 /
+0x8000.

## Phase 2.2 — boot #41: the GFX apertures are empty, the shim hangs (2026-11-12)

Payload `1e3b499f…`.  The Fender window's **upper half** (pages 17…31) read
**all zero** — so there is no mailbox anywhere inside the two 128 KiB
apertures the ADT gives the GFX.  Then the driver read the A7IOP shim
aperture at `0x2ee00000` and **the phone died** (the log simply stops at
"8c/12: the A7IOP shim aperture"; the SoC hangs on that address, like it
does on `fender+0x10044`).  That lead is dead — the shim's registers are
not reachable from the AP.

### The position rule the A10 gives

On the A10 the GFX's mailbox is its own DT node at `0x1d24000`, which is
**one page past the end of the iop window** (`0x1d20000` + `0x4000` = its
size).  The A11's iop window is `0x20000` long, so the same rule puts its
mailbox at **`0x4d40000`** — a page that the ADT does not list under
`gfx-kf` (and it does not list the A10's mailbox under the A10's gfx node
either: that one had its own node).

Boot #42 (payload `0aa937ab…`, built) therefore probes

* the GPU **core** window `0x04000000`…`0x04003000` (the firmware's IO map
  lists it at size 0x200000), and
* the page **past the IOP window**, `0x4d40000`, plus `0x4d48000`,

read-only, core first (it is a device we have read before).

## Phase 2.2 — boot #42 died on the core window; the firmware's IO map explains why (2026-11-12)

Payload `0aa937ab…`.  The driver printed "8c/12: the core window and the
page past the IOP window" and then the phone **hung** — reading
`0x204000000 + 0x00` (the RGX's first core register) traps the SoC, so we
never reached the interesting page.  Reading the RGX's register space blind
is not safe: only `+0x18` (CORE_ID) and `+0x20` have ever been read there.

### The firmware's own IO map (the key)

Both firmware images carry the same table, and the A10's lets us calibrate
it:

| | A10 (`gfx-t8010-const.bin` at 0x35565) | A11 (`g10p.img` at 0x3759c) |
|---|---|---|
| IOP window | base **0x01d20000**, size **0x20000** | base **0x04d20000**, size **0x20000** |
| core window | base **0x01000000**, size **0x01000000** | base **0x04000000**, size **0x02000000** |

The A10's mailbox (0x1d24000) is **inside** that IOP window, at +0x4000.  On
the A11 the page at +0x4000 is dead (boot #40), so the A11's mailbox is in
the same window at a **different offset** — and it is **dormant**: its
status registers read zero until the host enables it, which is why every
read-only sweep (boots #37, #38) came up empty.

**Boot #43** (payload `70f55003…`, built) therefore enables every page of
the IOP window with the sequence Apple's AppleA7IOPV2 class uses (mask all
four interrupts, unmask A2I-empty, enable the inbox and the outbox) and
with the V4 class's equivalents (IntOutIRQEn, INBOX_CTRL, OUTBOX_CTRL),
then reads each page back: **the mailbox is the page that takes the
write**.  The read-only probe came first, so this is no longer a blind
write, and it all happens before the window copy, so the window registers
are unaffected.

Also found offline: the AGX **hwdata** table in the kernelcache's
`__PLK_DATA_CONST` (0xfffffff006f8ab88, 53 entries of
{firmware address, mask, buffer offset}) — the values the host hands the
firmware: 0x20/0x24, 0x48/0x4c, 0x140/0x148, 0x188…0x19c, 0x404…0x414,
0x500, 0x800…0x80c, 0x900…0x91c, 0xc10/0xc14, 0xc30/0xc34, 0xe00.  It
includes the timebase pair at 0x808/0x80c and the A10-pair at 0xc30/0xc34
— the very offsets our driver writes ✓ — so it is the hwdata layout, the
same mechanism the A12 driver builds (`agx_fw.c`'s `agx_build()`).

## Phase 2.2 — boots #43…#45: the enable sweep, and what it rules out (2026-11-12)

Payloads `70f55003…` (IOP sweep), `2f898500…` (Fender sweep), `214d320f…`
(the two candidate pages in full).  All three booted cleanly.

The enable sweep writes both classes' sequences to every page of an
aperture and prints the pages that take the write.  The results:

| page | takes | what it is |
|---|---|---|
| `iop+0x0000` | +0x04, +0x20 | the firmware window registers |
| `iop+0x8000` | +0x00 | the DART (`dart_vm_size`) |
| `iop+0xc000` | +0x04, +0x08 | **empty apart from our writes** |
| `iop+0x10000` | **+0x00, +0x04, +0x08, +0x20, +0x48** | the only page that takes *both* V4 writes — but it is a device-info/ID block, not a mailbox (boot #45) |
| `fender+0x0000` | +0x54 | (a lone register) |
| `fender+0x1000` | — | the power state |
| `fender+0x2000` | — | the window registers |
| `fender+0x4000` | +0x80 (0x28 → 0x29) | the device-info page — *not* fully read-only after all |

Boot #45 dumped `iop+0x10000` in full: `+0x10/+0x14` are a 64-bit serial
that counts down between boots, `+0x30` and `+0x40` likewise, `+0x08/+0x0c`
are 0xffffffff — a chip-ID block, not a mailbox.  `iop+0xc000` is empty
apart from our own writes.

**So neither aperture contains a mailbox that accepts the enable
sequence.**  Three things are still open, in order:

1. **The mailbox may need a different enable value.**  The V4 class's
   `M3Wrap_CTRL` (+0x08) and `IntOutIRQEn` (+0x48) are the registers we
   wrote, but only the *A7IOPV4GFX* code knows their values; our guesses
   (1 and 0x1111) may simply not enable anything, and a write-protected
   block would look exactly like a dead page.
2. **The clock gate.**  The ADT gives `/arm-io/gfx-kf` `power-gates = 149`
   and `clock-gates = 149` — we have only ever touched the *perf state*
   (`ps_gfx` at PMGR 0x80338), never a gate.  If the GFX's clock is off,
   the mailbox's registers would read zero *and* ignore writes, which is
   exactly what every candidate does.  The PMP gate message we tried in
   earlier boots may have been the wrong lever (or the wrong format).
3. **The core window.**  The firmware's IO map lists `0x04000000` at size
   0x200000, so the firmware can reach it — and the mailbox may live
   there.  Reading it blind is dangerous: `0x20400000 + 0x00` traps the
   SoC (boot #42), so it has to be probed one offset at a time.

## Phase 2.2 — the PMP's clock-gate message, decoded from its own firmware (2026-11-12)

The PMP firmware (`pmp-t8015.bin`) contains the string `!clg: %08x`
(0x012c60) — the log line the firmware writes when it *rejects* a gate
message.  Its handler is at 0x0100e920, and it parses the **high** 32 bits
of the 64-bit message it receives:

```
  bits 0..11   the gate id
  bits 12..19  the device
  bits 20..    the command
```

and it rejects the message outright when bits 22..23 are set (the `!clg`
path at 0x0100e9aa).  The value it then writes to the PMGR is selected by
the command:

| command | value written |
|---|---|
| bit 31 set | `device << 12` |
| bit 30 set | `device << 20` |
| bits 20..21 != 0 | `device << 21` |
| otherwise | **nothing** |

**Both halves of the boot #25 sweep were wrong.**  The command went into the
*low* word of the message (the PMP reads the high one), and the command was
1 — whose bits 20..21 are zero, so the PMP would have done nothing even if
it had seen it.  A correct message is therefore

```
(cmd << 52) | (device << 44) | (gate << 32)
```

with a command of at least 4 (or with bit 30/31 set).

Boot #46 (payload `83763b65…`, built) sweeps 12 commands × the PMGR device
ids (GFX-KF 149, its list index 121, GFX 124) × 5 gate ids, starting the
endpoint 32 first, and watches for the PMP's reply.

### Boot #46: the gate message never left (payload `83763b65…`)

The message format was right, the *endpoint* was wrong: the RTKit layer
refused every send with "Endpoint 0x20 is not running" — 0x20 is the AGX
init endpoint, and the PMP never acknowledged a STARTEP for it.

But the format itself now makes the endpoint obvious.  The PMP's handler
parses the message's high 32 bits as

| high-word bits | payload bits | field |
|---|---|---|
| 0..11 | 32..43 | the gate id |
| 12..19 | 44..51 | the device |
| 20.. | 52..63 | the command |

and rejects the message when bits 22..23 are set (payload bits 54..55 =
the *type's* bits 2..3).  That is exactly the layout of an RTKit
**management** message — type in bits 59:52, payload below — so the gate
request is a management message on **endpoint 0**, not an app endpoint.

Boot #47 (payload `065690af…`, built) sends 27 command values (all well
clear of the management types the tree knows — HELLO 1, STARTEP 5,
SET_IOP_PWR_STATE 6, EPMAP 8, SET_AP_PWR_STATE 0xb — because sending one of
those by accident would confuse the PMP) × the PMGR device ids (GFX-KF 149,
its list index 121, GFX 124) × 4 gate ids, on endpoint 0, and watches for
the PMP's reply (our receive callback prints every message it gets).

### Boot #47: the PMP does not answer either (payload `065690af…`)

324 management messages went out cleanly (endpoint 0 is always available, so
none of them was refused) — and **the PMP never replied**, and the enable
sweep that ran right after them still found no mailbox.  So none of

* 27 command values (0x20…0xc4, all with the type's bits 2..3 clear and all
  clear of the management types the tree knows),
* 3 device ids (GFX-KF 149, its list index 121, GFX 124),
* 4 gate ids (149, 121, 124, 0)

turned the GFX's clock on.  (The only messages the RTKit layer saw were the
spurious type-0 ones that the device-info page at 0x204d04000 produces.)

### What the PMP's own strings say

The AppleA7IOP kext reads **`ps-reg-offset`** and **`debug-ps-clock-gate`**
from the device tree — the PMGR register offsets are *properties*, not
constants, so the kext can drive a chip whose PMGR layout differs.  The
D21's ADT has no such property on `/arm-io/gfx-kf`, so those belong to the
PMP's node.

### The remaining plan

1. **Read the `AppleA7IOPV4GFX` register maps.**  The class has two maps —
   `_agxRegisterMap` (the AGX registers: the DART, the timebase, the config
   words, all measured in the IOP window at 0x4d20000) and
   `_wrapRegisterMap` (the mailbox wrapper).  Two maps means two apertures,
   and `gfx-kf` has two: 0x4d20000 and 0x4d00000.  The map's *data* would
   give the physical offsets directly, and `initialize()` would show which
   aperture is which.  The vtable of the class is what is missing; the
   M3Wrap base class's vtable is at `__PLK_DATA_CONST` 0xfffffff006ccb258.
2. **The gate service's endpoint.**  The PMP's handler is reached through a
   computed dispatch (no function-pointer table entry), and the RTKit layer
   refuses to send on an endpoint that has not been started — so an endpoint
   sweep needs the STARTEP to be acknowledged first, which it was not for
   endpoint 0x20.
3. **The enable values.**  Only the kext knows what `M3Wrap_CTRL` and
   `IntOutIRQEn` must be set to.

## The PMGR picture (offline, 2026-11-12)

The A11's ADT gives the PMGR's device table and the register banks behind it:

| device | id | flags | its register |
|---|---|---|---|
| GFX | 124 | perf | PMGR window 0 + 0x80338 (= our `ps_gfx`) |
| GFX-SGX | 148 | no_ps | window 1 + 0x80000 (nominal) |
| GFX-KF | 149 | no_ps | window 1 + 0x80000 (nominal) |
| GFX-BUSY | 123 | no_ps | window 1 + 0x80000 (nominal) |
| PMP | 54 | perf, **critical, on** | window 0 + 0x80308 |

**The GFX has no "on" flag; the PMP does.**  The ADT that the bootloader
hands over therefore says: the PMP is running, the GPU is not powered.  That
is expected under PongoOS — nothing ever ran the GPU's power-up sequence —
and it fits every symptom: the mailbox answers reads but ignores writes,
the coprocessor never sends its HELLO, and the AGX's own registers are all
reset values.

The GPU's power state is requested through the PMGR's ps bank (window 0 +
0x80300 + psidx*8, 8-byte stride ✓ — the GFX is psidx 7 → 0x80338 ✓, and
`ps_regs[4].mask = 0x002a04ff` says which bits may be written ✓), but the
*PMP* is the one that has to act on the request.

### The A12 does it without the PMP

BadApple's A12 guide (`kieroid/badapple`, `docs/gpu.md`) says:

> iBSS leaves GPU rails 2 (SRAM) and 4 (core) at 0, so any RGX access wedges
> the coprocessor. Clear bits 10 and 12 of `0x23b0a0000` and the rails
> follow the GPU DVFS table at `0x23b070000`.

So on the A12 the GPU's rails are a **plain PMGR register** that Linux
writes directly (the A12's PMGR + 0xa0000), and the BadApple/Cascadia A12
driver never asks the PMP.  The A11's GPU is very likely the same story —
the AGX's fender/core apertures are at the *same addresses* on both chips
(`Fender 0x204d00000, RGX 0x204000000` in the A12's hwdata B, and the
A11's `gfx-kf`/`sgx` nodes ✓) — but the A11's PMGR layout differs (its ps
banks are at window 0 + 0x80000…0x88000 ✓, not at 0xa0000 ✓).

The A11's ADT has no `pwrgate-regs` table (the A12's does), so on the A11 the
GFX's rails are the PMP's job — which is exactly the gate message we have
been trying to get right.

### The AGX hwdata (the A11's own version)

The kernelcache's hwdata table (53 entries of {firmware address, mask,
buffer offset}) has offsets 0x20/0x24, 0x48/0x4c, 0x140/0x148,
0x188…0x19c, 0x404…0x414, 0x500, 0x800…0x80c, 0x900…0x91c, 0xc10/0xc14,
0xc30/0xc34, 0xe00 — including the timebase pair at 0x808/0x80c and the
A10-pair at 0xc30/0xc34, the very offsets our driver writes ✓.  The A12's
hwdata B is at +0x640 (the IO maps) / +0x958 (power mode) / +0xa70 (perf
tables) / +0x16d0 (unit masks) — a newer ABI, but the same idea.

### Boot #48: the core is alive, the Kingfisher is not (payload `66963de6…`)

The PMGR's ps bank decodes (our driver's own decode ✓):

```
ps_gfx @0x80338 = 0x1f0003ff  (auto 1, clk 1, pwr 1, actual 0xf, target 0xf)
ps @0x80308    = 0x1f0f00ff  (auto 1, clk 0, pwr 0)
ps @0x80318    = 0x1400024f  (auto 1, clk 1, pwr 0)
```

and the retoggle (writing 1 to the GFX's entry ✓) only cleared the "auto"
bit ✓ — the PMP did not take it back ✓.

So the **GFX device (id 124) is clocked and powered** ✓, and the GPU core
answers (CORE_ID = 0x7E1 ✓).  What is dead is the **GFX-KF** — the
Kingfisher, the side that owns the *mailbox IRQs* (259-262 ✓) and the
IOP/Fender windows ✓.  The GFX-KF is one of the three `no_ps` devices
(GFX-SGX 148, GFX-KF 149, GFX-BUSY 123 ✓) — it has no power-*state*
register at all, so its gate is a plain gate register in the
`pmgr1 + 0x80000` bank ✓, indexed by device id:

| device | id | offset in that bank |
|---|---|---|
| GFX-BUSY | 123 | +0x3b8 |
| GFX-SGX | 148 | +0x4a0 |
| GFX-KF | 149 | +0x4a8 |

The bank we dumped only showed entries at +0x00…+0x38, because the dump was
0x40 bytes long ✗ — the GPU's entries are beyond it ✓.

Also dumped `pmgr0 + 0xa0000`: that is the **DVFS/voltage table** on the A11
(0xbb8ffc05 ✓, 0x380ffc05 ✓ — the A12's guide calls the equivalent table
"the GPU DVFS table" ✓), not the rail register, so the A11's rail register
is probably at `pmgr0 + 0x70000` ✓ (the A12's offsets are swapped ✗).

**Boot #49** (payload `7c8722dd…`, built) dumps that bank wide (0x600 bytes ✓)
plus `pmgr0 + 0x70000` ✓, so the three GPU entries can be read directly.

## Phase 2.2 — boot #49: two more PMGR candidates ruled out (2026-11-12)

Payload `7c8722dd…`.  Clean boot, phone alive as `05ac:4144`.

* **`pmgr1 + 0x80000`** (the bank the three `no_ps` GPU devices point at):
  33 non-zero entries, but only up to `+0x140` — **nothing at the
  device-id offsets** (GFX-BUSY 123 → +0x3b8, GFX-SGX 148 → +0x4a0,
  GFX-KF 149 → +0x4a8).  So that bank is *not* indexed by device id, and
  the GPU's gates are somewhere else.
* **`pmgr0 + 0x70000`**: the **DVFS/voltage table** (0x00014605 = 17925 µV,
  0x3d094605, ten idle entries of 0x00014605) — not a rail register.  So
  on the A11 the A12's two offsets are swapped: `0x70000` is the A12's
  "GPU DVFS table" and `0xa0000` is the A12's "rail register" position.
  Both are DVFS tables here.

What the ps bank says about the GPU (our decode ✓):

```
ps_gfx @0x80338 = 0x1f0003ff  (auto 1, clk 1, pwr 1, actual 0xf, target 0xf)
ps @0x80308    = 0x1f0f00ff  (auto 1, clk 0, pwr 0)
ps @0x80318    = 0x1400024f  (auto 1, clk 1, pwr 0)
```

The GFX is clocked and powered, and the GPU core answers (CORE_ID ✓), so
the dead domain is the **GFX-KF** — the Kingfisher, which owns the mailbox
IRQs (259-262) and the Fender/IOP windows.  It is a `no_ps` device, so its
gate is a plain gate register, and we have not found it yet.

Also: the driver now reads the device-info page's `+0x80` as writable (the
enable sweep changed it from 0x28 to 0x29), so that page is not entirely
read-only after all.

## Offline RE, 2026-11-12 (no boot): the G10P mailbox, from Apple's kext

Lead 1 (the `AppleA7IOPV4GFX` register-map data) is **solved on the read
side**.  `GPU-WIP/tools/a7iop-v4-gfx.py` reproduces everything offline from
the D21 kernelcache.

* the kext's class hierarchy and every REQUIRE string (file, function,
  condition) are now known — `AppleA7IOPV4GFX.cpp` is the A11's class;
* the "register map" is **not** an offset table: the accessor is
  `ldr x8,[x0,#256]; ldr w0,[x8,w1,uxtw]` (0xfffffff00575b100), so the
  offsets the kext passes around *are* the physical offsets;
* `AppleA7IOPV4GFX` overrides `getMailboxBulk` and uses **+0x110** (CPU_CTRL),
  **+0x114** (status), **+0x800** (TX) and **+0x830** (RX) — *not* the
  M3Wrap base class's +0x08/+0x48/+0x50/+0x80;
* the AGX register block is the **Fender window (0x204d00000)**, so the
  mailbox is at **0x204d00110 / 0x204d00114 / 0x204d00800 / 0x204d00830**;
* CPU_CTRL bits: 0 = enabled, 16 = TX full, 17 = RX empty; 0xc0000 = invalid.

**Every earlier boot used the wrong offsets.**  The "enable sequence" of boots
#43/#44 wrote at +0x08 and +0x48 — the *base* class's registers — and **+0x110
was never read once in 19 boots**.  Boot #50 will read the new offsets.

### Boot #50: the mailbox at Apple's V4 GFX offsets (payload `09c1f308…`)

Clean boot, phone alive as `05ac:4144`.  New stage **8b2/12** read every
offset Apple's `AppleA7IOPV4GFX` uses, in both apertures.

```
mailbox map 0x204d00000 (the Fender window):
  +0x0008 = 0x00000000   M3Wrap_CTRL (the base class's)
  +0x0028 = 0x00000000   ?
  +0x0048 = 0x00000000   M3Wrap_IntOutIRQEn
  +0x004c = 0x00000000   M3Wrap_IntOutSts
  +0x0050 = 0x00000000   INBOX_CTRL
  +0x0060 = 0x00000000   TX
  +0x0080 = 0x00000000   OUTBOX_CTRL
  +0x00a0 = 0x00000000   RX
  +0x0110 = 0x00000000   CPU_CTRL  <== the GFX's mailbox control
  +0x0114 = 0x00000000   CPU_CTRL status
  +0x0b88 = 0x00000000
  +0x1008 = 0x00000000   the power state + 8
  +0x1020 = 0x00000000   the power state + 0x20
  +0x4008 = 0x00010704   the device-info page + 8   <== LIVE
  +0x800 (TX) = 0 0 0 0
  +0x830 (RX) = 0 0 0 0

mailbox map 0x204d20000 (the IOP window):
  +0x0008 = 0x0e100000   the firmware window base
  +0x0028 = 0x00100000
  +0x0048 = 0x0000004f
  +0x0110 = 0x00000000   CPU_CTRL
  +0x0114 = 0x00000000
  +0x4008 = 0x00000000   (the dead page at 0x4d24000)
  +0x800 (TX) = 00000060 00180018 00000000 60000003
```

**The AGX register block is confirmed to be the Fender window**: `+0x4008`
reads `0x00010704`, which is exactly the second word of the device-information
page we measured at `0x204d04004`.  The IOP window has the firmware-window
registers at +0x08/+0x28/+0x48 and the dead page at +0x4000, so it is *not*
the AGX block.

**But the mailbox read all zero — because of an ordering bug in my own
probe.**  Stage 8b2/12 runs *before* stage 9/12, which is where the driver
requests the Fender's power state; the log shows

```
GFX-STAGE 9/12: Fender power request (state 1)
fender power: state @0x1000 = 0x0 (state 0, ack 0)
fender power: state 1 -> 0x1 after 10 ms (status 0x0)
```

so at the moment of the probe the block was still **powered down** (its own
power-state register read 0).  A powered-down block reads zero.  The offsets
are right; the *timing* was wrong.

**Boot #51** (payload `d332ce32…`) moves the probe after the power request
(new stage 9b/12) and then performs Apple's own enable sequence, which
`AppleA7IOPV4GFX` implements at `0xfffffff00575b72c` (vtable slot +124):

```
readReg(0x114) -> w0
w8 = (w0 & ~1) | 1
str w8, [this->_agxMappedRegs + 0x114]
```

i.e. a read-modify-write of **bit 0 of +0x114**.  (The M3Wrap base class does
the same to its INBOX_CTRL at +0x50; the GFX class overrides it to +0x114.)

Also decoded offline from the same kext:

* the mailbox messages are **16 bytes**, not 8;
* the control word is a **ring queue**: bits 8-10 = the TX write pointer,
  bits 12-14 = the RX read pointer, bit 16 = TX full, bit 17 = RX empty
  (`0xfffffff00575b8f4` decodes them; 8 entries deep);
* `+0x800` = TX data, `+0x830` = RX data (16 bytes each).

### Boot #51: the mailbox, with the Fender powered (payload `d332ce32…`)

Clean boot, phone alive as `05ac:4144`.  New stage **9b/12**, after the Fender
power request:

```
GFX-STAGE 9/12: Fender power request (state 1)
fender power: state @0x1000 = 0x0 (state 0, ack 0)
fender power: state 1 -> 0x1 after 10 ms (status 0x0)
GFX-STAGE 9b/12: the mailbox, with the Fender powered
mailbox before: CPU_CTRL(0x0110) = 0x00000000, status(0x0114) = 0x00000000
mailbox after:  CPU_CTRL(0x0110) = 0x00000000, status(0x0114) = 0x00000000
TX(+0x800) = 00000000 00000000 00000000 00000000
RX(+0x830) = 00000000 00000000 00000000 00000000
```

**The enable write did not stick either.**  AppleA7IOPV4GFX's setter is a
read-modify-write of bit 0 of +0x114 (vtable slot +124,
`0xfffffff00575b72c`); the driver did exactly that and the register still
reads 0.  A register that ignores writes is a register whose domain is dark.

The device-information page was also re-measured to settle the AGX block
base — and it is **8-byte stride**, not 4:

```
fender+0x4000:  +0x00 = 0x01001000   +0x08 = 0x00010704
                +0x10 = 0x00090303   +0x18 = 0x00000080
```

so the kext's read of **+0x4008 = 0x00010704** is an exact match for the
page's third 32-bit field — the **AGX register block is the Fender window
(0x204d00000)**, confirmed.

## The PMP's management-message dispatch (offline, 2026-11-12)

`pmp-t8015.bin`, the management-message handler at **0x0100ddc2**:

```
0x0100ddcc: ubfx r0, r3, #20, #4    ; the type = the high word's bits 20..23
0x0100ddce: cmp r0, #15
0x0100ddd0: bhi #70
0x0100ddd4: tbb [pc, r0]           ; a 16-entry jump table at 0x0100ddd8
```

`r3` is the message's **high** 32 bits, so the **type is the message's bits
52..55** — four bits, 16 types:

| type | handler | | type | handler |
|---|---|---|---|---|
| 0 | 0x0100dedc | | 8 | 0x0100ddf6 |
| 1 | 0x0100df38 | | 9 | 0x0100de28 |
| 2 | 0x0100dde2 | | 10 (0xa) | 0x0100de1e |
| 3 | 0x0100de64 | | **11 (0xb)** | **0x0100df88** ← SET_AP_PWR_STATE |
| 4 | 0x0100df5e | | 12 (0xc) | 0x0100ddda |
| 5 | 0x0100dfbe | | 13 (0xd) | 0x0100de20 |
| 6 | 0x0100ddde | | 14 (0xe) | 0x0100df96 |
| 7 | 0x0100de78 | | 15 (0xf) | 0x0100dfa8 |

The **clock-gate** handler is at **0x0100e920** (not in this table — it is
reached through a function pointer).  Decoded:

```
r2 = the message's high word
tst r2, #0xC00000        ; bits 22..23 -> "!clg: %08x" (reject)
r6 = r2 >> 20            ; the command  (message bits 52..63)
r1 = sbfx(r2, 0, 12)     ; the gate id  (message bits 32..43)
r3 = ubfx(r2, 12, 8)     ; the device   (message bits 44..51)
value = (cmd bit31) ? device << 20
      : (cmd bit30) ? device << 12
      : (cmd bits 20..21) ? device << 21
      : device << 12
```

and the helper is called with the constant **0x202** and the gate id.

**So a gate request is `(cmd << 52) | (device << 44) | (gate << 32)` with the
type in the low four bits of `cmd` (message bits 52..55) and message bits
54..55 clear** — the type must be < 16.  Boot #47's 324 shapes should have
covered those, so the remaining suspects are the *gate id* and the *0x202*
register selector, and the fact that the PMP's reply is a management message
that our driver logs as **"unknown management message: 0x0 (type: 0x00)"**
and throws away.

### Boot #52: the AGX block's pages 0 and 1 (payload `0afc7c76…`)

Clean boot, phone alive as `05ac:4144`.  Stage **9a/12** dumped the AGX
register block (the Fender window) word by word:

```
agx+0x0054 = 0x00000006
agx+0x1000 = 0x00000001
agx+0x1014 = 0x00000002
```

**Three live registers in the whole 8 KiB.**  `+0x0054 = 6` was known;
`+0x1014 = 2` is new; `+0x1000 = 1` is our own power request.

The `ps-reg-offset` hypothesis is **wrong**: `+0x1008` and `+0x1020` are
both zero and ignore writes (we wrote 0x11 to each).  So the mailbox's own
power-state register is somewhere else, or the mailbox is gated from a
different block entirely.

The rest of the boot was unchanged: the mailbox at `+0x110`/`+0x114` still
reads zero and the enable write still does not stick.

## The PMP's clock-gate handler, decoded properly (2026-11-12)

The earlier addresses were 12 bytes out: llvm-mc prints one line per
*instruction*, so the addresses have to be accumulated from the encoding
lengths, not from the byte offset (`GPU-WIP/tools/pmpdis.py` does it
correctly now).  With that fixed:

* the management dispatch is at **0x0100ddc2** and takes the type from the
  message's **bits 52..55** — four bits, sixteen types — via a `tbb` jump
  table at **0x0100dde8**;
* **type 3 → 0x0100e92c**, which is the clock-gate handler (the "!clg: %08x"
  string is in its literal pool at 0x0100e9bc);
* type 11 (0xb) → 0x010131ee, the SET_AP_PWR_STATE handler (the one that
  works).

The handler decodes the message's **high** word as

| bits | meaning |
|---|---|
| 0..11 | the gate id (`sbfx`, signed) |
| 12..19 | the PMGR device (`ubfx`) |
| 20..31 | the command |

with bits 22..23 of the high word (message bits 54..55) rejecting the
message, and the value it writes chosen by the command:

| command | value written |
|---|---|
| bit 31 set | `device << 20` |
| bit 30 set | `device << 12` |
| command bits 20..21 != 0 | `device << 21` |
| otherwise | `device << 12` |

**And the bug in boot #47: all 324 of its gate messages went out on the
GFX's own RTKit channel — the one on the dead mailbox — so none of them
ever reached the PMP.**  They have to go out on the **PMP's** management
endpoint, which works (the PMP answers our SET_AP_PWR_STATE on it).
Boot #53 sends them there.

### Boot #53: the PMP answers (payload `18132120…`)

Clean boot, phone alive as `05ac:4144`.  The gate messages went out on the
**PMP's** management endpoint this time, and the PMP replied to **every
single one**:

```
gate: cmd 0x3 dev 149 gate 0 -> msg 0x0039500000000000 (ret 0)
RTKit: unknown management message: 0x40000000000000 (type: 0x04)
...
gate sweep: 84 management messages sent to the PMP
```

90 replies in all: **84 of type 0x04** (one per request) and the 6 periodic
ones of type 0x00.  So:

* the message format is right — the PMP dispatches it,
* **the reply type is the request type + 1** (HELLO 1/REPLY 2,
  SET_IOP_PWR_STATE 6/ACK 7, **gate 3/REPLY 4**),
* the reply payload is `0x40000000000000` — **identical for all 84
  requests**, so the status does not depend on the device, the gate id or
  the command we chose.  The request is accepted but nothing is gated.

**The mailbox is still dark**: `CPU_CTRL (+0x110) = 0`, the enable write
does not stick, and the PMGR gate bank (`pmgr1+0x80000`) is unchanged.

### What the PMP writes, and where (offline)

The handler writes `device << 12` (or `<< 20`, `<< 21`) and passes the
constant **0x202** to the helper that does the write.  The `<< 20` and
`<< 21` forms land far outside any 1 MiB PMGR window, so the `<< 12` form
names a **register**: PMGR window + (device << 12).

| device | id | register offset |
|---|---|---|
| GFX-BUSY | 123 | 0x7b000 |
| GFX | 124 | 0x7c000 |
| GFX-SGX | 148 | 0x94000 |
| **GFX-KF** | **149** | **0x95000** |

None of those offsets has ever been read.  Boot #54 dumps them (in PMGR
windows 0 and 1) **before and after** the gate sweep: whatever the PMP
changes is the register it wrote — no need to guess the encoding.

### Boot #54: crashed — the PMGR's windows are not adjacent (payload `164a91a3…`)

The phone took an **SError on CPU5** and rebooted (it came back into iOS
fine; no harm done).  The log shows exactly where:

```
gate reg before: window 0 +0x7b000      <- read fine (all zero)
gate reg before: window 1 +0x7b000      <- SError here
```

**Boot #54 assumed PMGR window 1 = window 0 + 0x100000.**  It is not: the
PMGR's two windows are **0x232000000** (the ADT's 0x32000000) and
**0x235200000** (the ADT's 0x35200000) — 32 MiB apart, not 1 MiB.  So
`window 0 + 0x100000` is the hole immediately past window 0, and reading it
takes an asynchronous abort.

Boot #49 had it right (`pmgr1+0x80000` = 0x235280000 ✓).

**Boot #55** (payload `e0fe8296…`) sweeps the real addresses —
`pmgr0+0x7b000`, `pmgr0+0x93000`, `pmgr1+0x93000` — before and after the
gate sweep, printing each chunk's header first so that if one of them is
a hole, the SError names it.

### Boot #55: the candidate gate registers, before and after (payload `e0fe8296…`)

Clean boot, **no crash** (the window bases are fixed), phone alive as
`05ac:4144`.  The candidate registers, dumped before and after the 84
gate messages:

```
gate reg before: pmgr0+0x7b000
  +0x7c000 = 0x3000f2ab
  +0x7c004 = 0xffe10c0e
  +0x7c008 = 0xffffffff
  +0x7c00c = 0xffffff97
  +0x7c010 = 0xffffffff
  +0x7c014 = 0x80109600
  +0x7c800 = 0x00000005
gate reg before: pmgr0+0x93000      (all zero)
gate reg before: pmgr1+0x93000      (all zero)
```

**and the "after" dump is byte-for-byte identical — the PMP wrote nothing
here.**

Two things follow:

1. **`device << 12` does land on something real for the GFX** (124 << 12 =
   0x7c000 ✓ — a live block), but that block holds *data*
   (0xffe10c0e, 0xffffffff, 0x80109600 — voltage/rail-looking), not a gate
   register, and it did not change.
2. The **GFX-SGX (0x94000) and GFX-KF (0x95000) offsets are empty** in
   both PMGR windows.  So the Kingfisher's gate register, if it exists, is
   not at `device << 12` — the offset must come from the *gate id* or from
   the 0x202 selector instead.

Combined with the reply being `0x40000000000000` for every one of the 84
requests, the likeliest reading is that **the request is being rejected
before any write** — the gate id is wrong.

Boot #56 therefore sweeps the **gate id** (the message's high word bits
0..11, the one field never varied) across 0..255 for each GPU device, and
watches for a reply status that differs from 0x40000000000000.  It touches
no PMGR register, so it cannot take an SError.

### Boot #56: the gate id, swept (payload `d9b1fe6c…`)

Clean boot, phone alive as `05ac:4144`.  1024 requests (gate id 0..255 for
each of the four GPU devices, command 0x40000003):

```
1024 x  unknown management message: 0x40000000000000 (type: 0x04)
   6 x  unknown management message: 0x0              (type: 0x00, the periodic ones)
```

**Every reply is identical, and nothing changed**: the PS bank is the same
as boot #49's, and the mailbox is still dark (`CPU_CTRL = 0`, the enable
write does not stick).

So the gate id (the high word's bits 0..11) is not the missing piece
either.  The **only field never varied is the message's low word** — the
RTKit *payload*.  The PMP's handler stores it at `obj[0]` and hands it to
the helper, whose very first act is `and r0, r0, #31` compared against 31
and 16 — so the payload selects something (a gate class, a value).  Every
request so far carried a payload of **zero**.

**Boot #57** (payload `ae0162a0…`) sweeps 21 payloads x 4 gate ids x 4
devices and then reads the PS bank, the AGX block and the mailbox.  The
observable is the mailbox coming alive, not the reply: the reply has been
constant from the start.

### Boot #57: the payload sweep — and the reply was never a status (payload `ae0162a0…`)

Clean boot, phone alive as `05ac:4144`.  336 requests (21 payloads x 4 gate
ids x 4 devices) and the replies are:

```
   16 x  0x40000000000000      <- payload 0
   16 x  0x40000000000001      <- payload 1
   16 x  0x40000000000002      <- payload 2
   ...
   16 x  0x4000000007b000      <- payload 0x7b000
   16 x  0x40000000095000      <- payload 0x95000
   16 x  0x400000ffffffff      <- payload 0xffffffff
```

**The reply echoes the payload.**  It is `0x40000000000000 | payload`, the
same for every request — so the reply was never a status and never told us
anything.  (The `0x40000000000000` is a constant flag bit; the PMP's
dispatcher answers type N with type N+1.)

And nothing changed: the PS bank is unchanged, the mailbox is still dark.

### The gate request, fully decoded (offline, 2026-11-12)

The handler's tail (0x0100c142) is the actual write:

```
0x0100c15e: ldr  r1, [r5, #8]       ; the base = device << 12
0x0100c162: ldr  r2, [r1, r0]      ; the register at base + 0x202
0x0100c164: bic  r2, r2, #0x8960   ; clear bits 5, 6, 11, 12
0x0100c168: it   eq
0x0100c16a: addeq.w r2, r2, #0x2000 ; set bit 13 if the message == 1
0x0100c16e: str  r2, [r1, r0]      ; write it back
```

So the PMP **clears bit 6** — the "gated" bit — of a per-device gate
register at `(device << 12) + 0x202`, in the PMP's own address space (which
is why the AP cannot see the register change at the same address: we
probed pmgr0 and pmgr1 at 0x93000..0x97000, which covers 0x95202, and it
stayed zero).

**But bit 6 is exactly the bit the AP's own gate bank carries**: the ADT's
`pmgr/ps-regs[0]` is `{reg 1, offset 0x80000, mask 0x00200c53}` — a bank
whose writable mask includes bits 6 and 13 — and three of its entries read
**0x244 (bits 6, 9, 10)**.

**Boot #58** (payload `00696796…`) therefore walks that bank from the AP,
clears bit 6 in one entry at a time, and watches the mailbox's CPU_CTRL
after each write.  If one of those entries is the GFX-KF's gate, the
Kingfisher powers up and we learn which one it was.  Every value is saved
and restored if nothing works, and the register is one we have already
mapped and read safely dozens of times, so there is no SError risk.

### Boot #58: ungating from the AP — the writes do not stick (payload `00696796…`)

Clean boot, phone alive as `05ac:4144`.  Stage 9c/12 walked the AP's gate
bank (pmgr1 + 0x80000) and cleared bit 6 in each entry that had it, reading
the mailbox's CPU_CTRL after every write:

```
ungate: entry 0  0x1f0000ff -> 0x1f0000ff, CPU_CTRL = 0x00000000
ungate: entry 13 0x00000244 -> 0x00000244, CPU_CTRL = 0x00000000
ungate: entry 22 0x00000244 -> 0x00000244, CPU_CTRL = 0x00000000
...
ungate: no entry woke the mailbox
```

**Every write read back unchanged.**  Clearing bits 5 and 6 of 0x1f0000ff
should have given 0x1f00009f, so the write was *rejected*, not raced: **the
AP cannot write the PMGR's gate bank.**  The mask in the ADT
(`ps-regs[0].mask = 0x00200c53`) describes what the *PMP* may write there,
not the AP.  (Bit 5 is not even in the mask; bit 6 is, and it still did
not take.)

So the Kingfisher's gate can only be cleared by the PMP itself, from the
PMP's own address space — which is consistent with the PMP writing to
`(device << 12) + 0x202`, an address the AP does not have a mapping for.

**The three entries that read 0x244 (bits 6, 9, 10)** — indices 13, 18, 19,
22, 24, 25, 26, 28, 29, 30, 34, 37 — are the most likely "gated" devices,
but the AP cannot touch them.

### Boot #59 (planned): the PMP v2 call on endpoint 32

Tree commit `6586463337d4`.  Offline, this session decoded the PMP v2
message from ApplePMP.kext's own send path (`_sendPMCommand`, kext at
0xfffffff0050e0e00): `msg = (1<<52)|(cmd<<48)|(domain<<42)|((arg>>12)<<16)`,
ack = {cmd+1 at 44..51, domain at 40..43, device at 32..39}.  Also: the
ADT says GFX-KF/SGX/BUSY all sit on gate-bank **entry 0** (psreg 0,
psidx 0 → 0x235280000), and the management type-3 handler bails silently
when the handle it resolves is not registered — which is why 336
management requests never wrote anything.

Stage 3b starts endpoint 32 and sweeps 88 messages (16 commands; 16×4
device forms; the clg word ×{bit52} in the mgmt placement), watching
CPU_CTRL/status, ps_gfx and the gate bank after each.  Repeated at 9d.

### Boot #59: endpoint 32 is ALIVE — cmds 1/3/5 ack with the +1 convention (payload `bc98cfa9…`)

Tree `6586463337d4`.  Clean boot, phone alive as `05ac:4144`.

```
pmp-v2: start_ep(32) -> 0
pmp-t8015-v1: Received unexpected message to EP32: 0          <- the start confirm
pmp-v2: start: CPU_CTRL 0, status 0, ps_gfx 0x0f0003ff, bank0 0x1f0000ff
EP32: 2000000000000    <- ack to cmd 1 (cmd+1 = 2), sent 47.79, ack 47.80
EP32: 40000ffffffff    <- ack to cmd 3 (cmd+1 = 4) + payload 0xffffffff, sent 48.05
EP32: 6000000000000    <- ack to cmd 5 (cmd+1 = 6), sent 48.31
```

* **cmds 1, 3, 5 are the live PM commands** (the ack nibble = cmd + 1,
  exactly ApplePMP's `pm_msg_get_cmd(ack_msg) == command + 1`).
  Commands 0, 2, 4, 6..15 never acked.
* **each command acked only ONCE**: the same commands later in the sweep
  (with devices) and in the 9d re-run got nothing.  So the interesting
  variants must be sent FIRST on a fresh boot.
* **cmd 3's ack carried a value**: `0xffffffff` — a read of an
  unmapped/absent target (the message had no device).
* **the bank[6]/bank[20] toggles are housekeeping, not us**: they fired
  on unrelated (cmd, dev) pairs across the two sweeps (cmd 5/148+123 in
  run 1; cmd 7/149+124 and cmd 11/123, cmd 12/149 in run 2), are ~110 ms
  wide and ~2 s apart — a periodic PMP tick writing status into
  pmgr_mini's bank.  Do not attribute bank changes to commands without a
  flush/quiet-baseline control.
* `start_ep(32)` the second time returned -22 (already started); sends
  still worked but nothing acked.
* the GFX mailbox stayed dark (CPU_CTRL 0) through both sweeps; RTKit
  version 0 at the end (the GFX's own channel never booted).

**Interpretation**: cmd 3 looks like a *read* (it returns a 32-bit
value); cmd 5 the likely *write*; cmd 1 maybe a state set.  With
`arg = (dev << 12) | 0x202` — the very address the firmware's clg
handler writes — cmd 3 should return the device's gate register.

### Boot #60: cmd 3 reads, cmd 5 writes, the ack echoes the device (payload `7ed55d4f…`)

Tree `889c94d0d597`.  Clean boot.

* **quiet 3 s baseline: zero bank changes** — boot #59's bank[6]/bank[20]
  toggles were message-driven after all, not periodic housekeeping.
* **cmd 3 (the read) acked 12/12**: the first 8 (dev at 16..23) returned
  `0x40000ffffffff`; the bits-32..39 form returned
  `0x40095ffffffff / 0x4007c… / 0x40094… / 0x4007b…` — **the ack echoes
  the device at [39:32]**, exactly where ApplePMP's
  `pm_msg_get_device()` check reads it.  Payload always `0xffffffff`.
* **cmd 5 (the write) acked 20/20** (`0x6…`), flushes (cmd 0) silent —
  and changed nothing: no bank moves, ps_gfx unchanged, mailbox dark.
* cmd 1, sent last after 40 messages, got nothing.
* the full 41-entry bank was dumped: bank[0] `0x1f0000ff`, the twelve
  `0x244` entries at 13/18/19/22/24/25/26/28/29/30/34/37.
* **queue lesson**: boot #59's 100 ms cadence outran the PMP's ~255 ms
  ack pace; at ~200 ms/message everything acks.  Drive ep 32 slowly.

**Offline (same session)**: the firmware's private gate interface is a
hardware block whose command register sits at `+0x40` with the layout
`{cmd[19:16], device[15:8], enable[0]}` (read at 0x0100cb4a, written at
0x0100cb82); a message builder at 0x0100cba0 packs
`(arg3 << 20) | (arg2 >> 12)`.

**Interpretation**: `0xffffffff` for every PMGR id smells like "no such
device" — the PMP's device indices are its own, not the PMGR's.
**Boot #61** (tree `29afcad77de1`) sweeps the cmd-3 read across all 64
one-byte device indices at bits 32..39; any non-`0xffffffff` payload is
a real device, and its index is what the write must carry.

### Boot #61: the read sweep, 0..63 — every device reads 0xffffffff (payload `aa50d37e…`)

Tree `29afcad77de1`.  Clean boot.  128 cmd-3 reads (64 in 3b + 64 in 9d),
**all acked 1:1** at the 200 ms cadence, the device correctly echoed in
the ack (`0x40000`…`0x4003f`), the payload **always `0xffffffff`**.
The mailbox stayed dark; ps_gfx and the bank never moved.

Two readings of the constant `0xffffffff`:

* (a) the read targets `(dev << 12) + 0x202` on the PMP's private bus and
  every page reads all-ones — unmapped, **or gated** (Apple MMIO reads of
  a gated domain return all-ones);
* (b) the read address comes from the message's *payload*, which was
  always 0 (reading address 0).

**Boot #62** (tree `ba03eead168b`): the PMP driver now captures the
ep-32 replies (a sequence number + `apple_t8015_pmp_reply_wait()`, so
the sweep prints its replies inline), then

* A: cmd 3 with the address in the payload — `0x95202` (the clg
  handler's `(149 << 12) + 0x202`), `0x32080000` (the PMP's own view of
  gate-bank entry 0, which the AP reads as `0x1f0000ff` — a matching
  reply would be a smoking gun), and a payload-0 control;
* B: the read sweep across **all 256** device indices; anything not
  returning `0xffffffff` is marked LIVE.

### Boot #62: the read ignores the payload; all 256 pages read all-ones (payload `d87ff1b4…`)

Tree `ba03eead168b` (+ `d457ada24a8e` build fixes).  Clean boot.

* the PMP driver now captures the ep-32 replies (`apple_t8015_pmp_reply_seq()`
  / `apple_t8015_pmp_reply_wait()`), so the sweep prints replies inline.
* **phase A**: cmd 3 with the address in the payload — `0x95202`,
  `0x32080000` and `0` ALL returned `0x40095ffffffff`: the device echoed,
  the payload **ignored**.  Hypothesis (b) is dead.
* **phase B**: the read sweep across all 256 device indices — **0 live**,
  every page reads `0xffffffff`.  Mailbox dark, bank unchanged.

**The firmware-side explanation** (offline, this session): the clg
handler resolves its target through an **eight-entry registry**
(`0x01017284`: count 8, then entries; walked by the split helper at
`0x0100a7a8` and by the transaction dispatcher at `0x0100dce4`, index =
the handle's **high 16 bits**).  Our device values (123/124/148/149)
can never be a registry index (0..7) — every request so far failed the
resolve silently and only echoed.  Also decoded: the mgmt type-3 tbb
target `0x0100de0b` is a common queueing path (types 3,4,5,6,10,11,14,15)
that feeds the transaction dispatcher (`0x0100dc60`, types 1..8, its own
tbb at 0x0100dc96).

**Boot #63** (tree `3400f64a6f76`): sweep registry-sized device values
0..7 — reads on ep 32 (a mapped page will not read all-ones), writes on
ep 32, and the device field of the management type-3 clg form.
