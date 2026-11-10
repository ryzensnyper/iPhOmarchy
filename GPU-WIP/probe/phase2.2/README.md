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

| item | value |
|---|---|
| payload | `out/apple-16k/linux.bin`, 61 097 072 B, sha256 `4987f034e7e78a79ee5e6199844c61b39ede25bb844c48495dfd891ec44cc515` (copy `/tmp/opencode/phase2.2-linux.bin`) |
| kernel | `Image.gz` 8 327 567 B, sha256 `7f669d35b7d9912b…`; contains the 2.2 strings; release still `7.3.0-rc1-orchard-apple-16k` |
| DTB | `t8015-d21.dtb` sha256 `064ce2538d55cd50…`; `gpu` has `mboxes = <&gpu_mbox>` and `power-domains = <&ps_gfx>` (phandle 0x31, `label = "gfx"`); `gpu_mbox@4d24000` present with IRQ order 260/259/262/261 |
| firmware | `lib/firmware/apple/gfx-t8015.bin` inside the initramfs, 381 728 B, sha256 `bd7b98e2833142d834bf3ac08dfc4a1d1f00d25a06ce04a67731a808a92bcc5c` (matches `g10p.img`) |
| receipt | kernel / D21 DTB / initramfs component hashes match `linux.bin.json` |

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

## Approval status

1. apply + build — **done** (`d616c1dbc383`, EXIT 0)
2. install firmware + rebuild — **done** (`bd7b98e2…` in the initramfs)
3. boot #2 — **done 2026-11-10: failed safely, see above**
4. fix + rebuild — **pending** (tree fix applied, build not run)
5. boot #3 (2.2 retry) — **pending; this consumes the last planned boot**

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
