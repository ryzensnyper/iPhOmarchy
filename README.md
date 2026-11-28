# iPhOmarchy

**Linux on the iPhone 8 Plus** (`iPhone10,2`, D21AP, Apple A11 / T8015), built on
[OrchardLinux](https://github.com/OrchardLinux). The phone runs the
[Omarchy-A](https://github.com/OrchardLinux/omarchy-a) desktop from its own storage, next
to an intact iOS. Every working kernel and m1n1 change is in Orchard `main`; this repository holds
the D21 bring-up: the boot recipe, decoded hardware notes, the earlier patches and the
tooling behind them. Fixes go to Orchard as pull requests (kernel work to
[OrchardLinux/linux](https://github.com/OrchardLinux/linux), m1n1 work to
[OrchardLinux/m1n1](https://github.com/OrchardLinux/m1n1)).

> Device: iPhone 8 Plus (Global), `iPhone10,2`, iOS 16.7.16 (identifiers redacted).
> Boot (tethered): checkm8 → PongoOS → Orchard payload (RAM) → Omarchy-A on `nvme0n1p3`.
> iOS stays on `nvme0n1p1`.

## Hardware status

| Piece | State | Where |
|---|---|---|
| Boot: checkm8 → PongoOS → Orchard payload, Omarchy-A installed on `nvme0n1p3` | ✅ tethered; iOS intact | [desktop/orchard-main](desktop/orchard-main/) |
| Omarchy-A desktop (labwc, greetd, lock-screen PIN) | ✅ v0.3.6 | [desktop/orchard-main](desktop/orchard-main/) |
| CPUs and frequency scaling, NVMe storage, RTC, watchdog, reboot | ✅ | Orchard `main` |
| USB networking and SSH | ✅ | Orchard `main` |
| Display (boot framebuffer 1080×1920) and brightness | ✅ no GPU acceleration | Orchard `main` |
| Touch: multitouch with pressure and palm rejection, shared `apple_z2` driver | ✅ in Orchard `main` | [docs/touch-bringup.md](docs/touch-bringup.md) |
| Power button | ✅ | Orchard `main` |
| Wi-Fi (BCM4357 over PCIe) | ✅ | Orchard `main` ([#251](https://github.com/OrchardLinux/orchard/pull/251), [#252](https://github.com/OrchardLinux/orchard/pull/252)) |
| Suspend/resume (s2idle, wake on the side button) | ✅ screen back in 0.3 s, touch about 8 s later | Orchard `main` ([#253](https://github.com/OrchardLinux/orchard/pull/253)); side-button wake on the installed system: [desktop/orchard-main](desktop/orchard-main/) |
| Always-On Processor (AOP) | ✅ firmware (from the IPSW, through the recipe) boots and serves the motion sensors and compass | Orchard `main` ([#260](https://github.com/OrchardLinux/orchard/pull/260), [#254](https://github.com/OrchardLinux/orchard/pull/254)) |
| Touch ID sensor | ⚠️ identified and switched off at boot; not usable | Orchard `main` ([#257](https://github.com/OrchardLinux/orchard/pull/257)) |
| Home button | ❌ parked: needs the Secure Enclave (see below) | notes: [patches/d21-wifi-suspend-aop](patches/d21-wifi-suspend-aop/) |
| Battery and charger (level, status, voltage, temperature, health, cycle count) | ✅ `macsmc-power`; the charge-now and energy-now readings came out byte-swapped on this SMC, fixed in [#259](https://github.com/OrchardLinux/orchard/pull/259) | Orchard `main` |
| Volume buttons and ring/silent switch | ✅ `KEY_VOLUMEUP`/`KEY_VOLUMEDOWN`; the ring switch reports `KEY_MUTE` | Orchard `main` |
| Motion sensors (accelerometer, gyro, barometer) | ✅ factory calibration and mount matrices; the desktop rotates with the phone | Orchard `main` ([#260](https://github.com/OrchardLinux/orchard/pull/260)) |
| Compass (magnetometer) | ✅ reads the field in µT on the device's axes, with the factory calibration from the ADT; no heading on the desktop yet (iio-sensor-proxy only takes HID compasses) | Orchard `main` ([#261](https://github.com/OrchardLinux/orchard/pull/261)) |
| Bluetooth (BCM4357, UART) | ✅ an Xbox controller pairs over Bluetooth and every button, stick and trigger works; audio not tested yet | in review: kernel [OrchardLinux/linux#14](https://github.com/OrchardLinux/linux/pull/14), recipe [#301](https://github.com/OrchardLinux/orchard/pull/301) |
| Audio (codec, speaker amps, AOP microphone) | ❌ | queued |
| GPU (G10P) | ⚠️ research only | [GPU-WIP/](GPU-WIP/), [docs/gpu-wip.md](docs/gpu-wip.md) |
| Cameras, cellular, NFC | ❌ not started | |

### Touch ID and the Home button

The iPhone 8 Plus Home button is solid-state. The AOP firmware runs its click logic, but only
reports clicks once the Touch ID sensor (Apple calls it Mesa) reports a finished reset.

- The sensor sits on its own SPI bus (spi3) and only answers in **SPI mode 2**. In its boot
  ROM it reports ID `0x3352`.
- Even after iOS's exact power-on reset, the AOP never sees that "reset complete". Most
  likely the sensor first has to run its firmware patch. On iOS that patch comes from the
  **Secure Enclave**, after a session with the sensor is set up. It isn't in the root
  filesystem, and the Secure Enclave firmware is encrypted.

So the Home button most likely needs the Secure Enclave running under Linux, and is parked. In the
meantime, PR #257 switches the sensor off at boot, so it no longer draws power while Linux
runs.

## Repository layout

- [`desktop/orchard-main/`](desktop/orchard-main/): the boot recipe. A RAM payload built
  with `orchard build` hands over to Omarchy-A on `nvme0n1p3`. Also how to install a new
  Omarchy-A release into `p3`, and the suspend/resume changes for the installed system
  (`p3/`).
- [`patches/`](patches/): kernel patches.
  - [`d21-wifi-suspend-aop/`](patches/d21-wifi-suspend-aop/): the bring-up notes and
    patches for DART, Wi-Fi, background touch resume and the AOP. All of it is in Orchard
    `main` now; kept for reference.
  - [`d21-touch-fixes/`](patches/d21-touch-fixes/), [`d21-import-shared/`](patches/d21-import-shared/):
    the touch work that went into Orchard's shared driver.
  - `0001`–`0045`, [`orchard-ref/`](patches/orchard-ref/), `REBUILD-VERMAGIC.md`: the
    earlier Hoolock-based touch bring-up, kept for reference.
- [`docs/`](docs/): dual-boot guide, hardware map, touch bring-up, roadmap.
- [`hardware/`](hardware/): decoded Apple Device Tree extracts for the D21.
- [`tools/`](tools/), [`scripts/`](scripts/): firmware and container tooling, device-side
  helpers.
- [`diamond/`](diamond/): the earlier DIAMOND touch build (Hoolock kernel), superseded by
  the shared driver in Orchard `main`.
- [`GPU-WIP/`](GPU-WIP/): GPU research notes.

## Use

1. Boot the phone into PongoOS with checkm8. `palera1n -p` pwns reliably here; see
   [docs/dual-boot.md](docs/dual-boot.md). Those are older notes from when Linux lived on
   `nvme0n1p2`; the pwn steps still apply.
2. Build the payload from a plain checkout of Orchard `main` (no local patches are needed
   any more) and boot it: [desktop/orchard-main/README.md](desktop/orchard-main/README.md).
3. Firmware comes from your own device and IPSW and is never in this repository:
   - the touch container, built from the device's own `mtprops` and ADT calibration with
     [`tools/`](tools/);
   - the Wi-Fi firmware and NVRAM;
   - the AOP firmware.

**No Apple firmware, per-device calibration, ECIDs or other device identifiers are committed
here.** Device-specific inputs are prepared on your own host from your own device.

## Related projects

- [OrchardLinux](https://github.com/OrchardLinux): the kernel, build tooling and Omarchy-A
  this runs on; D21 fixes go there as pull requests
- [Hoolock Linux](https://github.com/HoolockLinux/linux): the A7–A11 kernel Orchard builds on
- [Pauli1Go/HoolockLinux](https://github.com/Pauli1Go/HoolockLinux): the A10 (iPhone 7
  Plus / D111) bring-up the early touch work started from
- [m1n1](https://github.com/AsahiLinux/m1n1), [pongoOS](https://github.com/checkra1n/pongoOS),
  [palera1n](https://github.com/palera1n/palera1n): the boot chain

## License

See per-file SPDX identifiers and upstream licenses. This repository's own content is
GPL-2.0-only where derived from kernel work, MIT otherwise.
