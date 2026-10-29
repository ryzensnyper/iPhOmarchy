# iPhOmarchy

**Linux on the iPhone 8 Plus** (`iPhone10,2`, D21AP — Apple A11 / T8015), in the spirit of the
[OrchardLinux](https://github.com/OrchardLinux) project: device descriptions, kernel patches and
configuration, firmware recipes and bring-up tooling for a usable Linux phone on Apple A-series
hardware — on the last generation exploitable with checkm8, dual-booting with an intact iOS.

This repository owns the **research, hardware maps, kernel patch series, firmware tooling and
bring-up documentation**. It is not a ready-to-flash image; it documents what works, what does
not, and exactly what remains. The kernel tree this project develops against is
[Hoolock Linux](https://github.com/HoolockLinux/linux) (A7–A11 mainline-based); the D21 driver
work is maintained as the patch series in [`patches/`](patches/) on top of it.

> Device: iPhone 8 Plus (Global), `iPhone10,2`, iOS 16.7.16 (identifiers redacted).
> Host: CachyOS x86_64. Boot: checkm8/palera1n → PongoOS → m1n1 → Linux from `nvme0n1p2`.

## Supported hardware

Currently: **iPhone 8 Plus (Global, D21AP)**, experimental. Boot is tethered, the display is a
simple framebuffer, and touch is under active bring-up — nobody has published working touch on
this driver generation (Z2/HBPP 0x103) for any device other than Orchard's iPad 6 (J71b, 0x104).

| Piece | State |
|---|---|
| Jailbreak / pwned boot (checkm8, palera1n rootless) | ✅ tethered, reproducible |
| Dual-boot: iOS on `nvme0n1p1`, Linux on `nvme0n1p2` | ✅ working |
| Boot Linux from the internal partition | ✅ (pongoOS → m1n1 → kernel → rootfs) |
| Display (simple framebuffer, 1080×1920) | ✅ working, brightness ✅; real KMS is TBA upstream |
| Touch controller boot/calibration (Z2, HBPP 0x103) | ✅ controller boots, calibrates, scans |
| **Touch input** | ❌ contact frames never delivered — under active investigation |
| Wi-Fi (BCM4357 over `apcie`) | ❌ parked |
| Bluetooth (N88 UART + patchram) | ❌ parked |
| GPU | ❌ out of scope (no mainline A11 driver) |

## What makes this device interesting

- The touch stack is the **Z2 / AppleHIDTransport HBPP generation**: the controller boots from a
  container built from Apple's own `D21.mtprops` profile, is calibrated from four blob slots, and
  reports contacts as **0x76 HID frames** (32-byte header + 48-byte contact records, X/Y as
  0..1 fractions of the sensor surface). The frame format is decoded here and the in-kernel
  parser already matches it — the open question is the frame-delivery path.
- **Nobody has working touch on this generation in Linux.** OrchardLinux's J71b (iPad 6) is the
  only working reference and it differs in container layout, HBPP version (0x104 vs 0x103) and
  power sequencing (`function-power_ana` is a *display-pipeline* function on D21).
- All of it is reconstructed from: the live Apple Device Tree, the iOS 16.7.16 kernelcache
  (`AppleHIDTransport*`, `AppleMultitouchDriver`), the userspace `MultitouchSupport` framework,
  and live captures from jailbroken iOS.

## Repository layout

- [`docs/`](docs/) — bring-up plan, dual-boot guide, hardware map, touch-bringup state
- [`hardware/`](hardware/) — decoded Apple Device Tree / ADT extracts for the D21
- [`patches/`](patches/) — the kernel patch series (input: apple-z2 D21 driver work; SPI/UART DT)
- [`tools/`](tools/) — firmware/container tooling, extraction scripts, deploy helpers
- [`scripts/`](scripts/) — device-side helpers

## Use

Bring-up today is driven from a Linux host with the device in DFU/pwned mode; see
[docs/dual-boot.md](docs/dual-boot.md) for the boot path and [docs/bringup-plan.md](docs/bringup-plan.md)
for the plan. Kernel changes land in [`patches/`](patches/) and are applied to a
[Hoolock Linux](https://github.com/HoolockLinux/linux) checkout.

- [Touch bring-up state and open questions](docs/touch-bringup.md)
- [Hardware map](docs/hardware-map.md)
- [Roadmap](docs/ROADMAP.md)

Public content contains recipes, decoded structure and code — **no private Apple firmware,
per-device calibration, ECIDs or other device identifiers.** Device-specific inputs are
prepared on the user's own host from their own device.

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
