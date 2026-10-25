# iPhOmarchy

Running **Omarchy-flavoured Linux** on an **iPhone 8 Plus (D21 / Apple A11 / T8015)** via
checkm8/palera1n + m1n1 — dual-booting with iOS, and bringing up the hardware needed for a
usable graphical phone UI.

This repo is the **research, hardware map, tooling and bring-up plan** produced while getting
there. It is not a ROM or a ready-to-flash image; it documents what works, what doesn't, and
exactly what remains.

> iPhone 8 Plus (Global), `iPhone10,2`, iOS 16.7.16 (device identifiers redacted).
> Host: CachyOS x86_64. Kernel: Hoolock Linux `7.3.0-rc1` (m1n1 + pongoOS boot).

## Status

| Piece | State |
|---|---|
| Jailbreak (checkm8 / palera1n) | ✅ tethered, reproducible (see [docs/dual-boot.md](docs/dual-boot.md)) |
| Dual-boot: iOS on `nvme0n1p1`, Arch Linux ARM on `nvme0n1p2` | ✅ working |
| Boot Linux from internal partition | ✅ (pongoOS → m1n1 → kernel → `root=/dev/nvme0n1p2`) |
| Display | ⚠️ simple-framebuffer only (`simpledrm`), brightness ✅; real KMS is TBA upstream |
| SPI1 controller | ✅ brought up by this project (DT) |
| Touch | ❌ driver missing (`hid-transport,k1`; k1 family) — **the gate for a phone UI** |
| Wi-Fi | ❌ (`apcie,t8015` + BCM4357 + `brcmfmac`) |
| Bluetooth | ❌ (`bluetooth,n88` over uart1) |
| GPU | ❌ out of scope (no mainline A11 driver; upstream marks TBA) |

The full hardware map (register bases, IRQs, compatibles) decoded from the device's Apple Device
Tree is in **[docs/hardware-map.md](docs/hardware-map.md)** and
[hardware/adt-d21-peripherals.txt](hardware/adt-d21-peripherals.txt).

## Why this is hard

Upstream [Hoolock Linux](https://github.com/HoolockLinux/linux) (the A7–A11 Linux project)
supports this device only to the level shown above: **touch, Wi-Fi and Bluetooth are not
supported on any iPhone/iPad**, and GPU/display-pipe are marked *TBA*. So the remaining work is
**driver bring-up**, not configuration.

The de-risking reference is [Pauli1Go/HoolockLinux](https://github.com/Pauli1Go/HoolockLinux) — a
Hoolock fork with a **working** A10 (T8010) bring-up on the iPhone 7 Plus / iPad 7, including
touch, Wi-Fi and Bluetooth. Our A11 touch is the **same `k1` family** as theirs, so their stack is
a port base. See [docs/bringup-plan.md](docs/bringup-plan.md) for the measured port surface.

## Layout

```
docs/
  dual-boot.md          jailbreak + dual-boot Linux guide (working procedure)
  hardware-map.md       A11 peripherals from the Apple Device Tree
  bringup-plan.md       Omarchy plan + A10->A11 port surface
  touch-bringup.md      touch notes + reference to the Pauli1Go work
hardware/
  adt-d21-peripherals.txt   curated ADT node excerpt (uart1/spi1/sio/apcie/disp0)
tools/
  fetch-dt.py           fetch + unwrap a DeviceTree.im4p from any IPSW (HTTP range, no 5 GB DL)
  README.md             how to decode an ADT (lzfse + m1n1 adt.py)
patches/
  0001-t8015-add-spi1-and-uart1.patch        device-tree work from this project
  0002-push-rootfs-part-check-md5.patch      bugfix for the flashing helper
scripts/
  build-payload.sh      assemble the m1n1 payload (m1n1 | bootargs | dtb | Image.gz)
```

## Credits / references

- [HoolockLinux/linux](https://github.com/HoolockLinux/linux), [HoolockLinux/m1n1](https://github.com/HoolockLinux/m1n1), [HoolockLinux/docs](https://github.com/HoolockLinux/docs) — the upstream A7–A11 Linux work.
- [Pauli1Go/HoolockLinux](https://github.com/Pauli1Go/HoolockLinux) (+ `-bringup-docs`, `-linux-firmware`, `m1n1`) — the A10 bring-up this plan ports from.
- [palera1n](https://github.com/palera1n/palera1n) and [checkra1n](https://checkra.in) — checkm8/pongoOS.
- Apple Device Tree tooling: Asahi Linux docs, `m1n1` proxyclient.
- ivan.codes (Omarchy-on-a-phone, postmarketOS) and henrikklee (Omarchy on iPad 6) for community
  direction.

Nothing here ships Apple proprietary firmware, iOS IPSWs, or the `rootfs.ext4`/`palera1n`
binaries; refer to the upstream projects.
