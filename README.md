# iPhOmarchy

**Linux on the iPhone 8 Plus** (`iPhone10,2`, D21AP — Apple A11 / T8015), in the spirit of
[OrchardLinux](https://github.com/OrchardLinux): device descriptions, a kernel patch series,
firmware recipes and bring-up tooling for a usable Linux phone on Apple A-series hardware —
on the last generation exploitable with checkm8, dual-booting with an intact iOS.

**Touch works.** Six-finger multitouch with pressure, tool size and palm/hover suppression
over evdev — on the Z2/HBPP 0x103 controller generation, where the only previously working
Linux reference was Orchard's iPad 6 (J71b, 0x104). See
[docs/touch-bringup.md](docs/touch-bringup.md) for the decoded wire format, the measured
delivery laws, and the two bugs that mattered (a chestnut high-voltage rail nobody turns
on, and an interrupt drain loop that raced the controller into silence).

> Device: iPhone 8 Plus (Global), `iPhone10,2`, iOS 16.7.16 (identifiers redacted).
> Boot: checkm8/palera1n → PongoOS → m1n1 → Linux from `nvme0n1p2` (tethered).

## Hardware status

| Piece | State |
|---|---|
| Pwned boot (checkm8, palera1n rootless) | ✅ reproducible, tethered |
| Dual-boot: iOS on `nvme0n1p1`, Linux on `nvme0n1p2` | ✅ iOS intact |
| Display — simple framebuffer 1080×1920, brightness | ✅ (real KMS is TBA upstream) |
| **Touch** — 6-point multitouch, pressure/tool, palm/hover rejection | ✅ **working** — open: controller's still-contact refresh cadence (~1.9 s), palm rejection for pressed palms |
| Wi-Fi (BCM4357 over `apcie`) | ❌ parked |
| Bluetooth (N88 UART + patchram) | ❌ parked |
| GPU | ❌ out of scope (no mainline A11 driver) |

## How the touch stack works

The D21 controller is **not** driven like the A10 parts. The container that boots it is built
from Apple's own `D21.mtprops` profile (C1F5E,4 personality, fw 0x0773) plus per-device
calibration blobs; its high-voltage analog rail is the **display-PMIC chestnut** regulator
(the first step of iOS's touch power sequence — `function-power_ana` is a display-pipeline
function here); and contacts arrive as **0x44 D11-family frames** — 24-byte header +
30-byte records in signed surface-descriptor units, with the state byte's meaning varying
by firmware state, so contact validity is decided by pressure. Everything was reconstructed
from the live ADT, the iOS 16.7.16 kernelcache (`AppleHIDTransport*`,
`AppleMultitouchDriver`), `MultitouchSupport.framework` and live captures from jailbroken
iOS — decoded structures are in this repo; no Apple firmware or per-device calibration is.

## Repository layout

- [`patches/`](patches/) — the kernel patch series (0001–0036) for
  [Hoolock Linux](https://github.com/HoolockLinux/linux), branch `a11-port`. Cumulative;
  the touch-critical ones are 0020 (chestnut HV + PMIC/DT), 0034 (one frame read per IRQ)
  and 0035/0036 (pressure-based contact validity).
- [`docs/`](docs/) — dual-boot guide, hardware map, touch bring-up state, roadmap
- [`hardware/`](hardware/) — decoded Apple Device Tree / ADT extracts for the D21
- [`tools/`](tools/) — firmware/container tooling, extraction scripts, deploy helpers
- [`scripts/`](scripts/) — device-side helpers

## Use

1. Boot: [docs/dual-boot.md](docs/dual-boot.md) (palera1n → payload → Linux).
2. Kernel: apply [`patches/`](patches/) in order to a Hoolock Linux checkout;
   build `Image.gz` + dtbs; rebuild the boot payload with root on `nvme0n1p2`.
3. Firmware: build the touch container from the device's own `mtprops` + ADT calibration
   (`tools/`), install to `/lib/firmware/apple/` on the device, verify the personality via
   the d3 property read (`07 73`).
4. Touch: `modprobe apple_z2` (or insmod with the Boot Sequence pokes — see
   [docs/touch-bringup.md](docs/touch-bringup.md)) → `/dev/input/event*` multitouch.

**No private Apple firmware, per-device calibration, ECIDs or other device identifiers are
committed here.** Device-specific inputs are prepared on your own host from your own device.

## Related projects

- [OrchardLinux](https://github.com/OrchardLinux) — the inspiration and the J71b/Z2 reference;
  their `hardware` repository is the model for this one
- [Hoolock Linux](https://github.com/HoolockLinux/linux) — the base kernel (A7–A11)
- [Pauli1Go/HoolockLinux](https://github.com/Pauli1Go/HoolockLinux) — working A10 (iPhone 7
  Plus / D111) bring-up, parent of this tree's touch paths
- [m1n1](https://github.com/AsahiLinux/m1n1), [pongoOS](https://github.com/checkra1n/pongoOS),
  [palera1n](https://github.com/palera1n/palera1n) — the boot chain

## License

See per-file SPDX identifiers and upstream licenses. This repository's own content is
GPL-2.0-only where derived from kernel work, MIT otherwise.
