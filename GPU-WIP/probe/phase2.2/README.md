# Phase 2.2 patch kit — boot the GFX IOP, wait for RTKit HELLO

**Status: boot #2 executed 2026-11-10 — the driver hit a resource conflict
and unwound before any register write.  Cause found and fixed in the tree
(`gpu/phase2.2` working tree); **the fix is not built yet**.  See "Boot #2
result" below.**

Context: `../kb/A11-GPU-G10P-STAGE2.md` (Phase 2.2) and
`../kb/A11-GPU-G10P-BOOTCHAIN.md` (verified facts + the three traps).

## What it changes (3 files in `d21-touchgood`, 1 file in the payload)

| # | file | change |
|---|---|---|
| 1 | `drivers/soc/apple/apple-t8015-gfx.c` | replace the 2.1 stub with the 2.2 version here |
| 2 | `arch/arm64/boot/dts/apple/t8015.dtsi` | `gpu` gains `mboxes` + `firmware-name`; new `gpu_mbox` node — content in `t8015-gpu.dtsi` here |
| 3 | `drivers/soc/apple/Kconfig` | help text of `APPLE_T8015_GFX` only (symbol unchanged, defconfig unchanged) |
| 4 | payload `d21-desktop-boot/rootfs/lib/firmware/apple/gfx-t8015.bin` | the firmware blob — `install-firmware.sh`, a separate install step |

Kconfig help text (replaces the 2.1 text):

```kconfig
config APPLE_T8015_GFX
	tristate "Apple T8015 (A11) G10P GPU GFX IOP"
	depends on ARCH_APPLE || COMPILE_TEST
	depends on PM
	help
	  Power the GFX domain of the Apple T8015 (A11) SoC and boot the G10P's
	  firmware on the "gfx-kf" IOP.  The G10P's firmware must be alive
	  before any AP-side access to the RGX / Fender windows is safe.

	  Phase 2.2 stops after the RTKit handshake: it sends no AGX init data
	  and reads no RGX register.  Without the firmware blob in the payload
	  it does nothing beyond holding the power domain on.

	  Say Y here for the D21 GPU bring-up.
```

## The boot sequence (what the driver does)

1. **Domain on** — the platform core has already run the domain's power_on
   (`PS_TARGET = 0xf`, poll `PS_ACTUAL`) before `->probe()` (Phase 2.1).
2. **Mailbox started** — `devm_apple_rtkit_init(..., mbox index 0, ...)`
   binds `mboxes = <&gpu_mbox>` and enables the receive IRQ, *before* the IOP
   can send anything.  If the mailbox has not probed yet this returns
   `-EPROBE_DEFER` (no big allocations on the retry).
3. **Window** — 1 MiB coherent buffer (40-bit DMA mask, 16 KiB-aligned);
   programmed into *both* window copies:
   Fender `+0x200c..+0x2020` (4-byte stride) and IOP `+0x0008..+0x0030`
   (8-byte stride), then `IOP+0x0038 = 1`.
4. **Firmware** — `request_firmware("apple/gfx-t8015.bin")`; copied to the
   window, the rest zeroed up to `0x8f000` (the image does not cover the
   firmware's runtime/BSS).  Then `Fender+0x2048 |= BIT(0)` releases the IOP
   CPU.
5. **RTKit** — `apple_rtkit_wake()` sends `SET_IOP_PWR_STATE(INIT)` and waits
   for HELLO, EPMAP and the power-state ACK (1 s each).  Expected:
   `RTKit: Initializing (protocol version 12)`.
6. **Startep** — `STARTEP` for endpoint `0x20` (AGX init) and `0x21`
   (doorbell).  **No init page is sent** — the init message is Stage 3.

## Complete list of device writes

| where | what |
|---|---|
| Fender `+0x200c..+0x2020` | window: address lo/hi, zeros, size lo/hi, zero |
| IOP `+0x0008..+0x0030` | the same, at 8-byte stride |
| IOP `+0x0038` | window enable = 1 |
| Fender `+0x2048` | read-modify-write, bit 0 = 1 (run); cleared on failure |
| mailbox regs | the mailbox driver's own IRQ-mask writes at probe |
| mailbox | RTKit management messages (HELLO reply, EPMAP reply, power state) |

**No RGX access.**  The `rgx` window is mapped (for 2.3) but never read or
written in this phase.  Display, touch, storage, Wi-Fi: untouched.

## The gate

`request_firmware()` returning `-ENOENT` is not an error: the driver logs
`apple/gfx-t8015.bin not installed; IOP not started` and returns 0.  A kernel
with this patch but without the blob is therefore a Phase 2.1 boot.  That
makes the apply and the firmware install separable.

## Review points (deliberate choices)

1. **`apple_rtkit_wake()` rather than `boot()` alone.**  `pvr_apple.c` calls
   `apple_rtkit_boot()` directly; the proven `pmp_t8015_v1.c` calls
   `apple_rtkit_wake()`, which sends the IOP power-state request first.  We
   follow the proven path.  If the G10P firmware really answers without that
   request, `wake()` is still harmless; if it rejects it, the failure is
   visible in dmesg and we switch to `boot()`.
2. **IRQ order.**  The ADT's `gfx-kf` array is `[260, 259, 262, 261]`; the
   names are mapped in that ADT order.  If RTKit never receives HELLO, this
   is the **first suspect** (try the other pairing of the four lines).
3. **STARTEP without the init page.**  The plan includes it (A10's minimal
   handshake).  If starting `0x20` makes the firmware complain, drop the two
   `start_ep()` calls — HELLO is the 2.2 criterion, not STARTEP.
4. **RTKit buffers** are carved from the window between `0x8f000` and
   `0x98000` (the pvr layout's space before the init page).  If the firmware
   asks for a larger buffer, the driver logs an error from RTKit, but the
   handshake has already succeeded.
5. **The compatible stays `apple,t8015-gpu`.**  The PowerVR match entry
   (`apple,t8010-gpu`) and the coldplug trap are untouched.
6. **Probe order.**  `gpu` defers until `gpu_mbox` is bound; the mailbox also
   lists `ps_gfx` as its domain, so its probe-time register writes happen with
   the domain on.

## Build result (2026-11-09 — applied and built, NOT booted)

Applied as `d616c1dbc383` on `gpu/phase2.2`, with the firmware installed.
`orchard build` exited 0; `apple-t8015-gfx.o` compiled with no warnings.

**Rebuild 2026-11-10 (after the boot-#2 fix `485453dd66d9`):** payload
`a0bbc54995249af42c2eccaa8b3d47c4ff26fd47a212c5dea5ac0afd0e4b44d1`
(copy `/tmp/opencode/phase2.2b-linux.bin`).  This is the row the retry
boot uses.

| item | value |
|---|---|
| payload | `out/apple-16k/linux.bin`, 61 097 072 B, sha256 `a0bbc54995249af42c2eccaa8b3d47c4ff26fd47a212c5dea5ac0afd0e4b44d1` |
| kernel | `Image.gz` 8 327 488 B, sha256 `15ade92aa88a2191…`; contains the 2.2 strings; release still `7.3.0-rc1-orchard-apple-16k` |
| DTB | unchanged, `t8015-d21.dtb` sha256 `064ce2538d55cd50…`; `gpu` has `mboxes = <&gpu_mbox>` and `power-domains = <&ps_gfx>`; `gpu_mbox@4d24000` present with IRQ order 260/259/262/261 |
| firmware | unchanged in the initramfs, 381 728 B, sha256 `bd7b98e2833142d834bf3ac08dfc4a1d1f00d25a06ce04a67731a808a92bcc5c` (matches `g10p.img`) |
| receipt | kernel / D21 DTB / initramfs component hashes match `linux.bin.json` (build EXIT 0) |

**Recovery side effect:** same as 2.1 — `out/` now holds the 2.2 payload,
not the known-good one.  Copy the frozen payload
(`f44886c1…`) back before any `--no-build` recovery boot.

Approvals 1 and 2 are done; **approval 3 (boot #2) is pending**.

## Boot #2 result (2026-11-10 — executed, driver did not bind)

The payload booted and reached userspace in ~15 s.  The GPU driver probed
and unwound immediately, **before touching any register**:

```
apple-t8015-gfx 4000000.gpu: GFX power domain is up
apple-t8015-gfx 4000000.gpu: error -EBUSY: can't request region for resource [mem 0x04d20000-0x04d3ffff]
apple-t8015-gfx 4000000.gpu: probe with driver apple-t8015-gfx failed with error -16
```

Cause: the `iop` window (`0x4d20000..0x4d3ffff`) contains the mailbox page
(`0x4d24000..0x4d24fff`), which the mailbox device claimed when it probed.
`devm_platform_ioremap_resource_byname("iop")` calls `request_mem_region()`
on the whole window, so it failed with `-EBUSY`; the probe unwound, the
device detached, and the domain dropped to `off-0`.

Safety: no Fender/IOP/RGX write happened (the failure is the second driver
line), no crashlog, no oops; display, touch and NVMe unaffected.

**Fix (applied to the tree, not yet built):** map only the first 4 KiB of
the IOP window with `devm_ioremap()`, which does not claim the region.  The
window registers used here are at `+0x08..+0x38`, below the mailbox page at
`+0x4000`; the mailbox's page is never mapped by this driver.

**Latent bug elsewhere:** `drivers/gpu/drm/imagination/pvr_apple.c` maps
`"iop"` the same way, so the PowerVR path would hit the identical `-EBUSY`.
Fix it there before that driver is ever booted.

**Verifier fixes for the retry:** the HELLO check is now scoped to
`4000000.gpu` (macsmc and nvme-apple also log `RTKit: Initializing`, which
produced a false PASS in boot #2), the mailbox IRQ check greps the
`4d24000.mbox-*` lines, and two hard checks were added for a failed probe
and for the firmware gate.

## Boot #3 result (2026-11-10/11 — executed, hard reset, no output)

The retry payload `a0bbc549…` (kernel `15ade92a…`, fix `485453dd66d9`)
uploaded fine (`RUN_EXIT=0`) and the phone **reset to iOS within a second
or two, with no text on the screen**.

**No text is the expected symptom of a probe that is too early.**
`drivers/Makefile` links `soc/` (line 46) **before** `gpu/` (line 68), and
both `apple-t8015-gfx` and `simpledrm` register at `device_initcall`.
So the GPU driver probes at ~0.65 s, *before* simpledrm has registered the
framebuffer; the VT console has nothing to draw on and every `dev_info()`
of the driver is lost.  Nothing of boot #3 was observable, on screen or in
a log.

**What boot #3 did reach.**  It was the first boot that touched **any** GFX
register: the mailbox driver only *maps* its page (`apple_mbox_probe()`
writes nothing — the mask and FIFO-enable writes live in
`apple_mbox_start()`, which only runs when RTKit starts).  The first-ever
GFX accesses were therefore, in order:

| # | access | code |
|---|---|---|
| 1 | mailbox mask `0x1111` → `IOP+0x4000`, mask clear `0x1001` → `+0x4004`, FIFO enables → `+0x4008` / `+0x4020`, `enable_irq` | `apple_mbox_start()` in `devm_apple_rtkit_init()` |
| 2 | Fender window `+0x200c..+0x2020` (6 words, 4-byte stride) | `apple_t8015_gfx_set_window()` |
| 3 | IOP window `+0x08..+0x30` (6 words, 8-byte stride) | `apple_t8015_gfx_set_window()` |
| 4 | IOP window enable `+0x38 = 1` | `apple_t8015_gfx_set_window()` |
| 5 | run bit `Fender+0x2048` RMW bit 0 | `apple_t8015_gfx_probe()` |
| 6 | `apple_rtkit_wake()` (a mailbox message — cannot reset the SoC) | `apple_t8015_gfx_probe()` |

The A10 reference in this repo (`drivers/gpu/drm/imagination/pvr_apple.c`,
proven on a J71b iPad 6 at 60 fps) uses the same order, the same register
offsets and the same mailbox driver, so the *sequence* is not the suspect;
what differs on the A11 is the power/clock state of the GFX block.

## Boot #4 (diagnostic) — what the next build changes

Only the driver changes; the **register sequence is untouched**.

| change | why |
|---|---|
| register the driver at `late_initcall` instead of `device_initcall` | `late_initcall` runs after every `device_initcall`, i.e. after simpledrm registered the framebuffer: the VT console is live and can show the log |
| `msleep(2000)` before the first GFX access | gives the console time to take the VT over and the user time to watch the screen |
| `GFX-STAGE n/6:` line + `msleep(1200)` before each step | the last line on screen names the access that stalled the bus, even if the reset is immediate |

Expected on the phone's screen, in this order:

```
GFX-DIAG: first IOP access in 2 s; watch the screen
GFX-STAGE 1/6: mailbox (RTKit) init
GFX-STAGE 2/6: Fender window copy
GFX-STAGE 3/6: IOP window copy
GFX-STAGE 4/6: IOP window enable
GFX-STAGE 5/6: release the IOP (run bit)
GFX-STAGE 6/6: RTKit wake
```

**How to read the result.**  If the phone resets to iOS, the last
`GFX-STAGE` line that appeared is the access that hung the bus (read the
screen while it boots; the phone clears it on reset).  If the phone stays up
and reaches SSH, the driver got past every step and the failure is in the
handshake, not in an access.  If a kernel oops appears, the trace is on the
screen.

## Boot #4 build (2026-11-11)

Tree commit `e9c4c84d0c6e` (driver only), rebuilt from
`d21-touchgood` with `orchard build --device d21 --kernel-tree …`:

| item | value |
|---|---|
| payload `linux.bin` | `6f595e1b911ffb97c901f7f5eca9a8c828b9bc6018976721a3785297b457d1be` (61 096 872 B) |
| kernel `Image.gz` | `584703e9a8f15f5197b9ad52f9dac30abbe2d0fb71fdf528cc52253ef57f1e1c` (8 327 367 B) |
| DTB `t8015-d21` | `064ce2538d55cd50…` (unchanged) |
| initramfs | `d54f35e291ea5c47…` (unchanged) |
| firmware `apple/gfx-t8015.bin` | `bd7b98e2833142d8…` (unchanged) |
| build | **EXIT 0** (`/tmp/opencode/phase2.2c-build.log`) |

Two upload attempts failed **before any image byte was transferred** — the
failing transfer is the 4-byte "image size" control request, before the
bulk transfer starts (`USB control 1: LIBUSB_ERROR_TIMEOUT`), and the
second attempt then failed at `libusb_set_configuration`.  PongoOS ended
its session and the phone fell back to iOS (`mode: other`, PID `05ac:12a8`).
**No Linux boot happened**; the phone was in PongoOS for a long time before
the attempt, and a fresh PongoOS session has clean memory for the 61 MB
upload buffer.

## Approval status

1. apply + build — **done** (`d616c1dbc383`, EXIT 0)
2. install firmware + rebuild — **done** (`bd7b98e2…` in the initramfs)
3. boot #2 — **done 2026-11-10: failed safely, see above**
4. fix + rebuild — **done** (tree fix `485453dd66d9`, payload `a0bbc549…`)
5. boot #3 (2.2 retry) — **done 2026-11-10/11: hard reset, no output, see
   above**
6. diagnostic rebuild (late_initcall + stage lines) — **pending approval**
7. boot #4 (diagnostic) — **pending: needs an explicit go**

## Verification after boot #2

`sh verify.sh`.  Hard checks: RTKit HELLO line, `GFX IOP released` +
`GFX firmware is up`, no `GFX firmware crashed`, domain `on` with both
`4000000.gpu` and `4d24000.mbox`, mbox bound to `apple-mailbox`, no `powervr`,
fb0/touch/NVMe unchanged, no oops/panic.  Warnings: unknown management
messages.

## Failure handling

* `wake()` times out → the driver clears the run bit, logs
  `GFX firmware did not answer`, probe still succeeds, boot continues.  The
  phone stays up; nothing else was touched.
* No HELLO at all → check the IRQ order, then `wake` vs `boot`, then the
  run-bit base (Fender vs IOP).
* Rollback: reboot.  The known-good payload remains the fallback; to undo the
  patch, `git checkout --` the three files (or reset the tree to
  `5744368dec2c`).

## What this does **not** do

* No AGX init page, no RGX reads, no Fender power state (2.3), no job, no
  display path change.

## Boot #7 result (2026-11-11 — executed, log captured, mailbox READ hangs)

Payload `074b84e2…` (kernel `357c690c…`) = the boot #6 build with the
hardened log bridge.  The phone booted, the gadget came up (`05ac:4144`),
15 966 bytes of kernel log arrived over the USB network, then the phone
reset to iOS.  Last two lines:

```
[   12.767642] apple-t8015-gfx 4000000.gpu: GFX-STAGE 0/7: ps_gfx power state (PMGR read)
[   14.815634] apple-t8015-gfx 4000000.gpu: GFX-STAGE 1/7: mailbox register read (IOP+0x4008)
```

So the fault is a **read** of the mailbox A2I register: the IOP block does
not answer at all.  Nothing was written to it, and `enable_irq()` was never
reached.  Stage 0's value did not print because that build's
`of_parse_phandle_with_args(..., NULL, -1, ...)` returned `-EINVAL`; the
next build uses `of_parse_phandle()` and logs every bail-out path.

Also in the same log:

```
pmp-t8015-v1 232300000.pmp: Direct firmware load for apple/pmp-t8015.bin failed with error -2
pmp-t8015-v1 232300000.pmp: unable to load firmware
apple-pmgr-pwrstate ...:power-controller@80308: sync_state() pending due to 232300000.pmp
apple-pmgr-pwrstate ...:power-controller@80310: sync_state() pending due to 232300000.pmp
```

`@80308`/`@80310` are `ps_pmp`/`ps_pms_sram` — powered, but nothing ever
claimed the PMP device, so the PMP firmware has never run in any boot.

## Boot #8 (PMP) — what the next build changes

1. `install-pmp-firmware.sh` extracts the PMP image out of the D21
   kernelcache (`tools/kc_pmp_extract.py`) and installs it as
   `/lib/firmware/apple/pmp-t8015.bin`.  126 608 bytes, sha256
   `2dcf73b5…`, byte-identical to the extraction in the A11 KB; identical in
   the D21 and D22 kernelcaches; fits the PMP's `0x20000` SRAM window.
2. `pmp_t8015_v1.c`: under the `gpu-diag` bootarg only, the bring-up
   (`upload → AKF remap → start → RTKit init → wake`) is deferred to a work
   item at 14 s and staged with `PMP-DIAG n/4: …` + 1 s holds, so the log
   survives if the PMP block itself hangs.  Without the bootarg the driver
   is unchanged (boots in probe).
3. `apple-t8015-gfx.c`: the GFX diagnostic work moves 12 s → 20 s so the PMP
   runs first; before the mailbox read it now dumps the PMGR `0x80300`
   power-state bank and reads the RGX core id / revision, to distinguish
   "whole domain dark" from "only the IOP sub-block dark".

Payload `b9151d1a…` (kernel `00b70cc7…`, initramfs `14055d71…`), built and
verified to contain both firmware files.  **Not booted — needs an explicit
go.**

What each outcome means:

| log says | conclusion |
|---|---|
| silence after `PMP-DIAG 0/4` | the PMP block is dark too; gates are a lower-level problem |
| `PMP is up`, then mailbox read hangs | PMP runs but does not gate the GPU unprompted → the AP must send the gate request; RE the AppleT8015PMPFirmware ↔ AppleA7IOP protocol |
| `PMP is up`, RGX id printed, mailbox hangs | GPU domain alive, IOP sub-block gated on its own |
| `PMP is up`, mailbox answers | the PMP is the gate owner → continue with RTKit HELLO |

## Boot #8 result (2026-11-11 — executed: PMP runs, GPU still dark)

Payload `b9151d1a…` streamed 17 713 bytes before the reset.

* **PMP: every stage completed.** `PMP-DIAG 0/4 … 4/4`, `RTKit: Initializing
  (protocol version 12)`, then `error -ETIME: Failed to wake PMP`.  So the
  PMP's SRAM window, AKF remap, `control = 1` start and mailbox are all
  reachable — that block is *not* dark.  Only the HELLO handshake is missing.
* **GPU: the RGX core itself hangs.** The log ends at
  `GFX-STAGE 1/8: RGX core id read (0x4000000+0x18)`, so it is not just the
  IOP sub-block: the whole GPU address space is unreachable.
* **`ps_gfx` is genuinely active**: `@0x80338 = 0x1f0003ff` — target 0xf,
  actual 0xf, `WAS_PWRGATED` and `WAS_CLKGATED` both set (it came out of both
  gates). Full bank snapshot is in `STATUS.md`.

Next, offline (no boot needed):

1. RE the `AppleT8015PMPFirmware` kext's gate request — the AP-side protocol
   for `30:clkG()` / `30:pwrG()`; the ADT's `pmgr-dock-fifo-agent` says the
   PMP has a dock FIFO, and the AGX kext strings include `pmp-dart`,
   `pmp-sw-interrupt`, `pmp-clock-gating`.
2. Find the GFX clock-source register in the ADT's PMGR block (the `GFX`
   clock entry, `perf_idx 44`; `clock-ids = [265]` on `sgx`) and compare with
   `clk-apple-t8010-touch.c`'s register layout.
3. Diagnose the `-ETIME`: compare `apple_rtkit_wake()` with m1n1's `rtkit.c`
   (the only reference that starts an A11-era IOP).

## Boot #9 — DOSSIER (2026-11-12, built, NOT booted — needs a go)

Items 1–3 above were worked offline; the results and the full ADT power model
are in **`PMP-POWER-MODEL.md`** next to this file, and the boot #8 re-read is
in `../STATUS.md`.  Summary of what changed:

* **The `-ETIME` is not "no HELLO".**  `RTKit: Initializing (protocol version
  12)` is printed by the HELLO handler, so the PMP *did* answer; the dispatch
  never reached `SET_AP_PWR_STATE(ON)` because mainline waits 1000 ms for the
  IOP power ACK and m1n1 waits forever.  The PMP firmware validates that AP
  power message (`Invalid AP power: %d`), and an AP that never declares
  itself on cannot expect gate services.
* **The GPU's gates have no PMGR register.**  `GFX-SGX`/`GFX-KF`/`GFX-BUSY`
  are `no_ps` (virtual) devices whose only parent is `GFX`; there is no
  `pwrgate-regs` array on T8015 either.  The PMGR is a `pmgr-dock-fifo-agent`,
  so a PS transition is only a *request* to the PMP.
* **The GFX clock has two candidate registers** (`0x2320003c0` and
  `0x2320b43c0`); boot #9 reads, never writes, that block.

### Files this build touches (4)

| file | change |
|---|---|
| `drivers/soc/apple/rtkit.c` | `APPLE_RTKIT_WAIT_MS` 1000 → **15000**; HELLO/EPMAP/IOP-ACK/AP-ACK transitions promoted to `dev_info` (DIAG) |
| `drivers/soc/apple/pmp_t8015_v1.c` | bring-up at 12 s; poll `apple_rtkit_is_running()` for 25 s; send `SET_AP_PWR_STATE(ON)` by hand if `boot()` aborted; export `apple_t8015_pmp_up` (copy in this directory) |
| `drivers/soc/apple/apple-t8015-gfx.c` | wait for `apple_t8015_pmp_up` (≤40 s); PS-bank + both DVFS windows (read-only); `ps_gfx` off→on re-toggle, aborting before the GPU accesses if the domain does not come back; then mailbox read, RTKit bring-up, RGX read (copy in this directory) |
| payload `init` (unchanged) | `gpu-diag` early stop + kmsg bridge at `172.16.42.2:6666` |

### Per-outcome interpretation

| log | meaning |
|---|---|
| `IOP power state transition: 0x0 -> 0x220` then `-> 0x20` | the PMP only needed time |
| `PMP is up (AP power state ON …)` | the AP power message landed; gates are now requestable |
| `retoggle: ps_gfx stuck at actual …` | the PMGR handed the domain to the PMP and it did not come back — strong evidence for PMP-owned gating |
| mailbox `A2I control` prints a value | the fender/IOP sub-block is clocked |
| `GFX firmware is up; RTKit handshake complete` | **Phase 2.2 passes** |
| `rgx: core id …` | Phase 2.3 identity read for free |
