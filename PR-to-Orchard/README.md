# PR proposal to OrchardLinux/orchard — apple_z2 recovery hardening (A11/D21 findings)

Status: DRAFT — do not send until the patch series is generated against the
assembled orchard kernel tree and passes their checks (checkpatch --strict +
the tests/ convention, cf. PR #52).

## What we are offering

Four generic apple_z2 hardening changes, all measured on hardware (D21 =
iPhone 8 Plus, T8015/A11 — the same SoC as Orchard's d221/iPhone X work, PR
#40/#55), all in the SHARED driver paths (J71b/J71t/J81/J172/D11/D111/N61
affected to varying degrees):

### 1. The IRQ-type landmine: restore the runtime type on EVERY exit path
Their J71b base flips the IRQ to LEVEL_LOW at runtime
(`saved_irq_type`/`irq_type_changed`, `apple_z2_j71b_restore_irq_type()`) and
restores it ONLY in the unload path. A boot that fails, is raced by removal,
or is aborted anywhere between the flip and the restore leaves the type
applied in the pinctrl GPIO irq domain. From then on EVERY probe fails:

    irq: type mismatch, failed to map hwirq-102 for pinctrl@233100000!
    error -EINVAL: request_irq(0) 0x0 apple_z2_irq [apple_z2] apple-z2-irq
    probe with driver apple-z2 failed with error -22

— and because the SPI core probes asynchronously (PROBE_PREFER_ASYNCHRONOUS),
insmod still exits 0: the unit/systemd looks fine while the driver is UNBOUND
(no touch, no recovery, no logs). The stale mapping clears only on a full
power cycle. Measured on D21 2026-11-03; reproduced across five consecutive
reloads. FIX (two parts): (a) restore the type in the boot error path too
(not just stop), and skip the flip entirely when a stop is in flight
(`stopping` flag, Orchard-79f5e69-style); (b) recommend describing the runtime
polarity in the DT so the flip is a no-op (we did exactly that on D21 —
interrupts-extended flags edge->LEVEL_LOW — and the class is dead).
This plausibly explains Orchard issue #22/#24 flakiness on J71b as well.

### 2. The boot-edge storm guard
A dead/wedged controller that holds ATN asserted re-fires the level IRQ
~44,000 times a second (measured; /proc/interrupts delta). The threaded
handler then crowds out the boot thread and a firmware-upload step never
finishes: the boot HANGS after the preamble with no log (reproduced twice,
once wedging rmmod into an unkillable D-state flush_work). FIX: in the
!booted IRQ path, complete() at most once per jiffy, and after ~200k edges
(~4.5 s of continuous storm; a healthy boot's assert phase stays far below)
mask the IRQ so the remaining boot waits time out BOUNDED and the recovery
ladder backs off.

### 3. A hard boot deadline inside the firmware loader loops
`while (fw_idx < fw->size)` loader loops have no global bound; per-step waits
have timeouts but a stalled transfer chain can still exceed any sane boot.
FIX: set a 60 s `boot_deadline` at boot start and check it (and `stopping`)
per loader step -> abort to the error path. Evidence: two hangs under storm
on D21.

### 4. The successful-restart-without-frames cap (closes the PR #52 gap)
PR #52 states the open problem verbatim: "confirming that repeated successful
controller boots followed by another stall do not cause a restart loop (the
three-attempt limit currently bounds failed boots within one recovery, not
repeated successful recoveries)". Our D21 implementation closes exactly this:
count consecutive in-driver restarts that boot fine but never deliver a
single valid frame; after N (we use 5) give up auto-recovery with a loud
error and leave the system to userspace. ANY valid frame resets the counter.
Composes with both the 79f5e69 ladder (which we ported: retries -> release+mask
-> 3 bounded resyncs -> full restart) and PR #52's control-stall detector.
Also: the ladder's "did it recover?" test must accumulate across its reads —
checking only the LAST read's frame-valid flag declared a STREAMING
controller failed and restart-looped it (measured 2026-11-03).

## Evidence pack
- evidence/type-mismatch-unbound.txt — the -22 probe failure + the unbound
  "active" unit (from captures/dmesg-zombie-20261103.gz, D21).
- evidence/storm-and-hang.txt — the 43.9k IRQ/s storm + the silent boot after
  the rail cycle.
- evidence/restart-loop-rung-bug.txt — valid frames interleaved with header
  gaps declared "resynchronisation failed".
- Host-side full logs: ~/omarchy-iphone/captures/dmesg-zombie-20261103.gz.

## What we did NOT offer (and why)
- The D21 SMC rail semantics (rBK3 function key, RW probe, OFF->ON with state
  readback): real and load-bearing for A11 half-boots, but D21-specific (SMC
  function keys differ per SoC; the iPad SMC keys are unknown to us). Offered
  as INFORMATION in the cover letter, not as code.
- Our D21-specific knobs (pres_min/tool latches/pokes): device tuning, not
  upstream material.

## Validation story for the cover letter
- Hardware: D21 (iPhone 8 Plus, T8015/A11), Orchard-style RAM payload
  (m1n1 + DTB + Image.gz via pongoOS bootm), root on NVMe p3.
- The recovery ladder (79f5e69 port + the D21 silence watchdog + the rBK3
  rail cycle inside power_off) recovered half-booted/dead rolls repeatedly
  WITHOUT a rebind or reboot: `D21: in-driver restart succeeded` after
  `smc rBK3 OFF state=0 -> ON state=1` (the A11 digital-core rail is an SMC
  function key; the wedged core state survives everything short of cutting it).
- The four fixes above were each driven by a reproduced failure on that rig.

## Mechanics (to finish before sending)
1. Reconstruct the assembled kernel tree: torvalds @ the orchard linux base
   (PR #52 names cee9395acd8043be0644b25c34bfa86623f2b935) + the series
   0001..N from kernel/patches/drivers/input/ (+ any interdependent series).
2. Rebase the four changes onto THEIR apple_z2.c (function names above are
   from their 0001 + 79f5e69 + PR #52; our file diverged for D21 so the port
   must be hand-done, not copied).
3. tests/: follow PR #52's convention (Python compiling + executing the added
   C helpers with mocked kernel ops) for: the dead-restart cap, the deadline
   check, the storm guard's edge accounting, the type-restore pairing.
4. checkpatch.pl --strict clean; commit subjects in their style
   ("Input: apple_z2: ..."); Assisted-by: LLM trailer (they use it).
5. Series shape: 4 patches, each standalone-revertable, ordered 4 -> 1
   (smallest risk first) or as one series if they prefer; reference PR #52
   (composition, not conflict) and PR #40/#55 (the A11 hardware context).

## Open question carried from D21 (2026-11-03 night — resolve before sending #1)
With the DTB fixed to LEVEL_LOW (verified by extracting the DTB from the sent
payload: interrupts-extended = 24 102 4), a LATER reload still hit the type
mismatch once the runtime flip had been active and a stop had restored it.
So on the apple GPIO irq domain, `irq_set_irq_type()` back to the DT type does
NOT reliably reset whatever `irq_create_fwspec_mapping()` compares against on
the next probe (the mapping's recorded type and/or the pin's hardware type
diverge). The DT fix makes flip and restore no-ops (both LOW), which should
make the mismatch impossible — the one residual observation suggests the
no-op path still diverged once; retest on a clean boot reading the flip log
("level-low (was 4)") EARLY (before any ring flood) and then a single reload.
If it still fires, the probe must harden further (e.g., request the IRQ with
the trigger the domain actually holds, or dispose/recreate the mapping).
