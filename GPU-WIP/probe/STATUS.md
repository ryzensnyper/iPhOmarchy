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
