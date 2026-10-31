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
- [x] **Palm rejection** (patches 0037/0038, 2026-10-31) — per-contact size latch:
      `tool_major ≥ 2000` OR record **area** `major×minor ≥ 2.5M`. Measured on-device:
      a hard finger press reaches 1812×1214 (2.2M) while palms land 2.84M-8.0M, so
      area separates what major alone cannot. Verified: medium + hard palm presses
      produce zero evdev events; a finger tap under a resting palm registers (the iOS
      behavior — a resting palm is pressure-0 and never reaches the size rules).
- [x] **Deployed into the installed omarchy-a system** (2026-10-31) — omarchy-a
      v0.1.1-d21 installed via the Orchard CLI (custom d21 adapter); touch loads at
      boot via `d21-touch.service` (gold poke config) and the labwc/Quickshell
      desktop is touch-reactive. Health gate: healthy rolls stream 19-24 fps,
      p50 26-33 ms, zero gaps, zero phantoms.

Closed: the **still-contact refresh cadence** (~1.9 s) turned out to be a drain-loop-era
artifact — with one-frame-per-IRQ (patch 0034) a verified 9.7 s dead-still hold streams
at 14.9 fps with zero gaps; it only survives in the big-contact path (a still palm shows
one ~1.9 s re-scan gap per session). The poke sweep it motivated is void.

Still open in M1: the boot-to-boot **delivery-mode variance** (healthy vs
phantom-transient vs half-rate vs dead reloads, ~1/6 healthy; gate every session through
the idlecheck meter and re-roll via `systemctl restart d21-touch`).

### M2 — Bluetooth (next up)
- [ ] ADT says BT is on **uart1** (`0x2E604000`, IRQ 283), `bluetooth,n88`, 3 Mbaud. uart1 node
      exists (`patches/0001`); needs a boot-test.
- [ ] Add an `hci_bcm` binding for the A11 BT + a `.hcd` from `BlueTool` (hcdpack).
- [ ] Verify with BlueZ (scan/pair).

Orchard template to follow (`OrchardLinux/hardware`, j71b is the reference):
- `kernel/patches/j71b/0003-j71b-bluetooth-driver.patch` — in-tree `hci_bcm.c` quirk
  flags (`wake_before_power_cycle`, `set_baudrate_before_patch`,
  `broken_read_transmit_power`, `fixup_le_adv_report_evt_type`). The D21 shape is the
  same: a quirk struct entry for the T8015 BT, selected from the DT compatible.
- `devices/j71b/firmware.json` — the public firmware **recipe**: IPSW url+sha,
  `extract_patterns`, and `files[]` with destinations (`BCM.apple,j71b.hcd` →
  `lib/firmware/brcm/`). For the D21: the BCM4357 `.hcd` from the `iPhone10,2` IPSW
  (`BlueTool`/hcdpack output), destination `lib/firmware/brcm/BCM.apple,d21.hcd`.
- `devices/j71b/device.toml` `[support]` flags — flip `bluetooth` when runtime-confirmed.

### M3 — Wi-Fi
- [ ] Port the **T8010 PCIe host bridge** (`pcie-apple-h9p.c`) → `apcie,t8015`
      (ADT ECAM `0x61000000`, IRQ 340-349, DART `dart-apcie3`).
- [ ] `brcmfmac` for **BCM4357** (`wlan-pcie,bcm4357`, PCIe port 3) + firmware (`.bin`/`.clm_blob`/
      `.txcap_blob`) and SysCfg/NVMEM calibration.

⚠️ Known hazard from the 2026-10-30 session: enabling apcie port 3 + DARTs killed the
console at t≈62.8 s — bring the hang-proof console (`CONFIG_USB_G_SERIAL=y` +
`console=ttyGS0`) or bisect the DART map before touching this again.

Orchard template to follow:
- `kernel/patches/j71b/0002-j71b-wifi-driver.patch` — in-tree `brcmfmac` fixes (e.g. the
  `bus_reset` work cancel before `brcmf_attach()` init). D21 will need its own
  PCIe-DMA/IOMMU-shaped fixes plus `kernel/configs/d21` `CONFIG_BRCMFMAC` fragment.
- `devices/j71b/firmware.json` destinations: `brcmfmac4355c1-pcie.apple,j71b.{bin,clm_blob,
  txcap_blob,txt}` — for the D21: **`brcmfmac4357-pcie.apple,d21.{bin,clm_blob,txcap_blob,txt}`**
  extracted from the `iPhone10,2` IPSW (`C-4357__s-C1F5E/`), plus the NVMEM/SysCfg txt.
- `kernel/modules/j71b/power/` shows the out-of-tree module convention if a helper
  module is preferred over in-tree patches.

### M4 — Adaptive charging
- [ ] Identify the D21 charging PMIC in the live ADT (`scharge` on i2c; chestnut is the
      display/touch PMIC, not the charger) and map its charge/input-limit registers.
- [ ] Out-of-tree policy module following **`kernel/modules/j71b/power/j71b_charge_policy.c`**:
      a conservative charging *lease* (root-only renewal, input-current limit registers
      `0xa03`/`0xa0c` on the j71b PMIC, PM notifiers that park renewals and synchronously
      restore the safe handoff limit before suspend). The D21 module targets the T8015
      PMIC's equivalent registers from the ADT.
- [ ] Runtime lease service following **`runtime/j71b/j71b-charge-lease/`**: userspace
      grants/renews charging leases (thermal-aware / battery-healthy ramps = the
      "adaptive" part), root-only, rechecks PMIC+battery every renewal.
- [ ] Verify with a USB power meter if available; never enable a limit we cannot restore.

### M5 — Audio
- [ ] Map the D21 audio path from the live ADT: the Apple audio controller (MCA/I2S) and
      the speaker/receiver codec nodes (T8015 codec wiring differs from M-series — no
      Orchard reference exists, this is the least-charted of the four).
- [ ] `kernel/configs/d21`: `CONFIG_SND_*` Apple audio options the tree supports.
- [ ] Kernel patches for any T8015-specific MCA/codec gaps, then a runtime config
      (PipeWire/WirePlumber) for the simple cases (speaker, receiver, mic).
- [ ] Usability bar: audio out for the desktop UI + terminal bell before media playback.

### M6 — Omarchy shell polish
- [x] Layer Omarchy opinions on the Arch Linux ARM install — **done 2026-10-31**: the
      Orchard CLI installed omarchy-a v0.1.1-d21 with labwc + the Quickshell
      omarchy-ipad shell, tablet autologin, wvkbd.
- [ ] Touch-adapted shell polish on the installed system (gestures, on-screen keyboard
      behavior, rotation).
- [ ] Target: `labwc` + software render on `simpledrm`, usable with touch — **met**.

### M7 — Display / GPU (long-term, out of near-term scope)
- Display pipe (`disp0,t8015`) and GPU (`G11P`) have **no mainline driver**; upstream marks them
  TBA. Not required for M1–M6 (simple-framebuffer is enough).

## Cross-cutting

- **Firmware extraction** (see `tools/` and the A10 project's `-linux-firmware` repo): A11 needs
  `apple/t8015-smartio.bin` (from the kernelcache), `apple/dfrmtfw-d21-…` (makez2fw),
  BCM4357 Wi-Fi fw, and a BT `.hcd`. Never commit Apple firmware or per-device calibration.
- **Loader**: the A10 project's m1n1 fork publishes NVMe HMB + touch calibration into the DT; we
  need the A11 equivalent.
- **Keep iOS bootable** — it is the only route into DFU.
