# A11 / T8015 GPU — Stage 2 plan: enable the GFX power domain, then power the core

*(Planning document.  Nothing here has run on hardware.)*

Stage 2 in this plan is the step **after** Stage 1 — booting the GFX IOP and
observing the RTKit HELLO.  Stage 2 cannot happen without Stage 1: on the
A10, the Fender power-request and any RGX read only take effect with the
firmware alive, and an AP read of the GPU registers before the core is
powered reliably panics (this phone already rebooted to iOS once from an
AP-side access of an *unpowered* GPU window).

## Why this order

| attempt | outcome |
|---|---|
| `/dev/mem` read of `0x04D00000` before any domain was enabled | AP hung, phone rebooted to iOS (2026-11-08/09) |
| A10 `ps_gfx` f/f, before the GFX firmware boot | safe; the domain comes up, the core still needs the firmware before RGX can be read |

Every register poke in this plan goes through the kernel's PMGR power-domain
framework or a driver inside it — never `/dev/mem`, never userspace.

## Objective

Enable the A11's GFX (G10P) power domain from Linux, verify it online,
then boot the GFX IOP and power the RGX core and read its identity
registers.  No jobs are submitted and no GPU registers are written by this
stage.

## The hardware pieces (this phone)

| node | purpose | reg / base |
|---|---|---|
| `pmgr` | PMGR block | `power-management@232000000`, size `0x8c000` |
| `ps_gfx` | **GFX power-state** | `power-controller@80338`, 32-bit, compatible `apple,t8015-pmgr-pwrstate` (driver `drivers/pmdomain/apple/pmgr-pwrstate.c`, built-in) |
| `gpu` (to add) | RGX + Fender + GFX IOP | see the sketch below |
| `gpu_mbox` (to add) | RTKit mailbox | A `+0x4000` ⇒ absolute `0x04D24000` (by analogy with A10's `mbox@201d24000 = A+0x4000`) |
| GFX IOP IRQs | `[260, 259, 262, 261]` | parent = AIC (`interrupt-parent = 28`) |
| RGX IRQs | `[255, 256, 257, 258, 263]` | unused here |

`ps_gfx` already exists in the DT of this phone's kernel (t8015-pmgr.dtsi).
Enabling it is one existing driver write: `PS_TARGET = PS_ACTIVE (0xf)`,
then poll `PS_ACTUAL == 0xf`.  Nothing new needs writing for 2.1.

## Phases

### Phase 2.1 — socket the GFX domain behind a real consumer (needed for any AP access)

Add to the d21 kernel tree, in `arch/arm64/boot/dts/apple/t8015.dtsi` (or a
new `t8015-gpu.dtsi` referenced from it):

```dts
/* sketch; every address is taken from the ADT (see A11-GPU-G10P-FINDINGS.md) */
gpu: gpu@4000000 {
    compatible = "apple,t8015-gpu";
    reg = <0x0 0x04000000 0x0 0x100000>,   /* RGX  */
          <0x0 0x04d00000 0x0 0x20000>,    /* Fender window W */
          <0x0 0x04d20000 0x0 0x20000>;   /* GFX IOP window A */
    reg-names = "rgx", "fender", "iop";
    mboxes = <&gpu_mbox>;
    power-domains = <&ps_gfx>;
    firmware-name = "apple/gfx-t8015.bin";
};

gpu_mbox: mbox@4d24000 {
    compatible = "apple,t8015-a7iop-mailbox";
    reg = <0x0 0x04d24000 0x0 0x1000>;
    interrupt-parent = <&aic>;
    interrupts = <AIC_IRQ 260 IRQ_TYPE_LEVEL_HIGH>,
                 <AIC_IRQ 259 IRQ_TYPE_LEVEL_HIGH>,
                 <AIC_IRQ 262 IRQ_TYPE_LEVEL_HIGH>,
                 <AIC_IRQ 261 IRQ_TYPE_LEVEL_HIGH>;
    interrupt-names = "send-empty", "send-not-empty",
                      "recv-empty", "recv-not-empty";
    #mbox-cells = <0>;
    power-domains = <&ps_gfx>;
};
```

This mirrors the A10 node (`gpu@201000000 … mbox@201d24000`, in
`t8010.dtsi` — the same tree layout, same `ps_gfx` domain).

Then a *minimal* driver for the `gpu` node that:
* requests `power-domains = <&ps_gfx>` at probe (domain comes up),
* registers the platform device,
* maps RGX / Fender / IOP **but touches no register**,
* does not load any firmware, does not boot the IOP.

Build, boot once ("go"), verify:
* `dmesg` shows the power domain activated,
* `/sys/kernel/debug/pm_genpd/…` (or equivalent) lists `gfx` as enabled,
* `simplefb` display still up, `apple-z2` touch IRQ firing, fb0 1080×1920×32,
* `/dev/rtc0`, NVMe, network all unchanged.

Rollback: reboot — reverts to the known-good state; nothing on NVMe changed.

**Do not** enable `DRM_POWERVR_APPLE` / `apple,t8015-gpu` in the config at this
phase — the driver must not touch hardware yet.

### Phase 2.2 — boot the GFX IOP (Stage 1 proper)

With 2.1 in place and the phone known-good:

1. Install the firmware `apple/gfx-t8015.bin` (the `g10p.img` copy — sha256
   `bd7b98e2833142d834bf3ac08dfc4a1d1f00d25a06ce04a67731a808a92bcc5c`).
2. The driver (same skeleton as `pmp_t8015_v1.c`):
   * allocates a 0x8f000-byte physically contiguous bounce buffer at
     ≥16 KiB alignment, copies the firmware, zeroes the rest;
   * maps the RGX / Fender / IOP windows;
   * sets the AKF windows to the buffer (the A10 recipe — both windows;
     offsets confirmed present in the G10P kext, identical to the A10);
   * releases the CPU (the A10 path: `W+0x2048 |= 1`);
   * talks RTKit over the new mailbox — expect RTKit HELLO v12, then EPMAP
     and STARTEP (the A10's minimal handshake).
3. Observe: `RTKit: Initializing (protocol version 12)` in the serial log;
   zero crashlog bytes.

**Do not** send the AGX init data, **do not** write RGX/USC, **do not** bind
a GL/ایکVulkan stack.  Success = HELLO received.

### Phase 2.3 — power the core, read identity (Stage 2)

With the firmware alive (2.2 succeeded):

1. `Fender+0x1000 ← 0x11` (state 1) — the exact write from `fender-power-on.sh`
   and from the G10P kext at `0x2600` (CONFIRMED).
2. Poll `Fender+0x1000` bit 4 until it clears (timeout ~100 ms); if it never
   clears, stop — the firmware is not initialised, and reading RGX may panic.
3. Read `Fender+0x2058` — expected `0x0` (A10 behaviour after state 1).
4. Read `RGX_CR_CORE_ID` (`0x04000018`) and `CORE_REVISION` (`0x04000020`).
5. Compare against A10's `0x011b0602` / `0x000d0a00` — **different** values
   expected on G10P; the key thing is a stable, sane ARM64-style readback
   with no panic.

If CORE_ID reads `0x…`, we now know the core is reachable and powered —
that is Stage 2's whole claim.

## What can go wrong, and what it costs

| failure | consequence | recovery |
|---|---|---|
| 2.1: domain fails to power, or DT doesn't register | driver logs a probe error, boot continues, GFX never powered | reboot; DT revert |
| 2.1: a fault in the 5-line driver panics the kernel | reboot; known-good payload still boots (slots A/B) | reboot; keep a rebuilt known-good payload |
| 2.2: firmware doesn't answer / IOP faults | IOP holds or dies; AP survives | reboot; disable the node |
| 2.3: RGX read before the core is powered | panic; phone reboots to iOS | reboot; Stage 2 is only attempted after 2.2 reports HELLO |
| display / Wi-Fi / touch break | — | out of scope; nothing touches them |

## What Stage 2 does **not** prove

* It does not power the RGX *shading* engine for jobs; it only establishes
  that the power domain and the core can be brought up by the firmware.
* It does not submit any job, run any shader, or verify the command stream.
* It does not prove the G10P ISA or the display path.

## Explicit approvals required before any device action

1. Approval to touch the kernel tree for the DT node and the IOP driver
   (`d21-touchgood` or the chosen tree) — **not granted yet**.
2. Approval to rebuild the kernel and reboot the phone with it.
3. One "go" per boot (2.1, 2.2, 2.3) — three boots total.
4. Approval to install `apple/gfx-t8015.bin` (only for 2.2).
5. Confirmation that the known-good payload stays the fallback (no NVMe
   changes).
6. Decision point after 2.1: stop, or continue to 2.2.

## Evidence to collect (all boots)

`dmesg`; `/proc/cmdline`; `/sys/kernel/debug/pm_genpd/*` (if present);
`cat /sys/class/graphics/fb0/virtual_size`; `fbset`; touch IRQ lines;
`cat /proc/modules`; NVMe health; final `dmesg | tail -50` and serial log.

## Order of work

Stage 2 needs Stage 1 (2.2) before 2.3.  Total boots: 3.  Cumulative
kernel-tree work: one DT patch + one new driver, both reviewable before any
build.  All effort after 2.1 can be stopped with no phone writes at any
point.
