# Known-good state — touch + omarchy-a desktop

This is the **D21 baseline**: the state we return to when an experiment
(Wi-Fi, GPU, BT, …) goes wrong. It is the D21 touch **DIAMOND build** with
the **omarchy-a desktop** running and touch live inside it.

Recorded 2026-11-07.

## What "known good" means

| Piece | State |
|---|---|
| Boot | checkm8/palera1n → PongoOS → m1n1 → Linux (tethered) |
| Storage | iOS on `nvme0n1p1`, Linux root on `nvme0n1p2`, iOS intact |
| Display | simple framebuffer 1080×1920 (+ brightness) |
| **Touch** | `apple_z2` DIAMOND build — 6-point multitouch, pressure/tool, palm/hover suppression over evdev |
| **Desktop** | omarchy-a (Orchard CLI install, labwc + Quickshell), touch-reactive via `d21-touch.service` (gold poke config, auto-loads each boot) |
| Wi-Fi / BT / audio / GPU | not working — see below |

Verified health gate for a good touch boot: healthy rolls stream 19–24 fps,
p50 26–33 ms, zero gaps, zero phantoms (see
[touch-bringup.md](touch-bringup.md)). Delivery-mode variance is still open
(healthy ~1/6 reloads): gate each session through the idlecheck meter and
re-roll with `systemctl restart d21-touch`.

## The DIAMOND touch build

The reproducible recipe is [../diamond/BRING-UP.md](../diamond/BRING-UP.md);
the kernel side is `patches/0040`; the deploy/verify path is
`diamond/verify-diamond.sh`, the systemd unit and the gold poke config.
The touch-critical kernel patches are 0020 (chestnut HV + PMIC/DT), 0034
(one frame read per IRQ), 0035/0036 (pressure-based contact validity) and
0037/0038 (palm rejection).

## Parallel Orchard-lane known-good (cross-reference)

The touch work was also brought up in the Orchard lane; that lane's own
frozen known-good (used for the Orchard kernel work) is:

- Kernel branch `backup/d21-touch-pre-rebase` @ `c2a38a5db829`
  (base `df7c930f80ab`), worktree
  `/home/doug/projects/OrchardLinux/trees/d21-touchgood`.
- Orchard distro `a7fea82` (touch-only; the commits after it are the
  abandoned Wi-Fi work).
- A frozen snapshot at `/home/doug/Known Good State/` (prebuilt payload,
  kernel + distro bundles, firmware, loaders, `README.md`, and the GPU
  research under `firmware/GPU/`).

This is listed for recovery context only; the two lanes use different base
kernels (Hoolock vs Orchard) and are not interchangeable.

## Recovery

1. Put the phone in DFU, then PongoOS (checkm8/palera1n).
2. Boot the known-good payload/root.
3. Load touch: `modprobe apple_z2` (or the `d21-touch.service` on the
   installed system) and check the idlecheck meter.
4. If the phone ends up on iOS after a bad experiment, force-restart
   (Power + Vol Down ~10 s) and re-enter DFU; iOS is always intact.

## Explicitly **not** part of known good

- **Wi-Fi** — the loader strips the `wifi@0,0` node from the booted D21 DT,
  so the pwrctrl rail never powers APCIE port 3 and the link never trains;
  the attempts that got further reset the phone to iOS. Closed for now.
- **GPU** — [gpu-wip.md](gpu-wip.md); research only, nothing boots.
- Bluetooth, audio, adaptive charging — queued (see [ROADMAP.md](ROADMAP.md)).
