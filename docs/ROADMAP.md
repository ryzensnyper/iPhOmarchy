# Roadmap

Goal: a **usable Omarchy-flavoured Linux** on the iPhone 8 Plus (D21 / A11 / T8015), dual-booting
with iOS. The hard part is driver bring-up; the de-risking reference is the A10 work in
[Pauli1Go/HoolockLinux](https://github.com/Pauli1Go/HoolockLinux) (working touch/Wi-Fi/BT on the
iPhone 7 Plus). Port surface: [bringup-plan.md](bringup-plan.md). Hardware map:
[hardware-map.md](hardware-map.md).

## Milestones

### M0 — Foundations ✅ (done)
- Dual-boot: iOS on `nvme0n1p1`, Arch Linux ARM on `nvme0n1p2`, booting via pongoOS → m1n1.
- Reproducible kernel/DT build (`make ... dtbs`); DT-only changes need no kernel rebuild.
- **SPI1 controller up** (`spi-apple`), DT loop proven. See `patches/0001`.
- Full A11 hardware map decoded from the Apple Device Tree (`hardware/`).

### M1 — Touch ✅ **WORKING** (2026-10-30)
Six-finger multitouch with pressure/tool and palm/hover suppression over evdev. What it took
(all decoded from the ADT, the iOS kernelcache and live captures — see
[touch-bringup.md](touch-bringup.md)):

- [x] Port **`apple_z2.c`** to the D21 (`hid-transport,k1`, SPI1, GPIO 102 IRQ — **level-low**).
- [x] Boot the controller from a container built out of Apple's own **`D21.mtprops`**
      (C1F5E,4 personality, fw 0x0773) + the four calibration blob slots.
- [x] **Turn on the touch high-voltage rail** — the `display-pmu,chestnut` PMIC switch the
      ADT names as `function-power_ana` (patch 0020). Without it the controller scans and
      reacts but never emits a single contact frame.
- [x] Decode the **0x44 contact frame format** (signed surface units) and replay the
      fwconfig **Boot Sequence register pokes** (patch 0028) — idle delivery metronome →
      continuous stream.
- [x] Kext-faithful interrupt pull + **one frame read per IRQ** (patch 0034) — the drain
      loop's off-IRQ pulls were the stream-death root cause.
- [x] **Pressure-based contact validity** (patches 0035/0036) — the 0x44 state byte's
      meaning varies with fw state; pressure is the invariant.

Open (in order): the controller's **still-contact refresh cadence** (~1.9 s bursts during
stationary holds — drag streams continuously; suspect the small-integer Boot Sequence pokes),
**palm rejection** for pressed palms (tool-size rule), and the boot-to-boot **delivery-mode
variance** (healthy vs phantom-transient vs half-rate reloads).

### M2 — Bluetooth
- [ ] ADT says BT is on **uart1** (`0x2E604000`, IRQ 283), `bluetooth,n88`, 3 Mbaud. uart1 node
      exists (`patches/0001`); needs a boot-test.
- [ ] Add an `hci_bcm` binding for the A11 BT + a `.hcd` from `BlueTool` (hcdpack).
- [ ] Verify with BlueZ (scan/pair).

### M3 — Wi-Fi
- [ ] Port the **T8010 PCIe host bridge** (`pcie-apple-h9p.c`) → `apcie,t8015`
      (ADT ECAM `0x61000000`, IRQ 340-349, DART `dart-apcie3`).
- [ ] `brcmfmac` for **BCM4357** (`wlan-pcie,bcm4357`, PCIe port 3) + firmware (`.bin`/`.clm_blob`/
      `.txcap_blob`) and SysCfg/NVMEM calibration.

### M4 — Omarchy shell
- [ ] Layer Omarchy opinions on the Arch Linux ARM install (`jondkinney/armarchy`, aarch64).
- [ ] A touch-adapted compositor/shell (model on henrikklee's iPad `labwc` approach).
- [ ] Target: `labwc` + software render on `simpledrm`, usable with touch.

### M5 — Display / GPU (long-term, out of near-term scope)
- Display pipe (`disp0,t8015`) and GPU (`G11P`) have **no mainline driver**; upstream marks them
  TBA. Not required for M1–M4 (simple-framebuffer is enough).

## Cross-cutting

- **Firmware extraction** (see `tools/` and the A10 project's `-linux-firmware` repo): A11 needs
  `apple/t8015-smartio.bin` (from the kernelcache), `apple/dfrmtfw-d21-…` (makez2fw),
  BCM4357 Wi-Fi fw, and a BT `.hcd`. Never commit Apple firmware or per-device calibration.
- **Loader**: the A10 project's m1n1 fork publishes NVMe HMB + touch calibration into the DT; we
  need the A11 equivalent.
- **Keep iOS bootable** — it is the only route into DFU.
