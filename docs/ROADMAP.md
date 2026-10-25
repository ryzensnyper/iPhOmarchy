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

### M1 — Touch (the gate for any UI)
Phone USB is device-mode only, so a compositor is unreachable without touch. Software render
(`labwc` + `WLR_RENDERER=pixman` on `simpledrm`) is fine; input is the blocker.
- [ ] Port **touch clock** (`clk-apple-t8015-touch`) from A10 → t8015 PMGR offsets.
- [ ] Port **SmartIO + SIO-DMA** (`iop,t8015`; ADT `sio@2EE00000`, IRQ 308-311).
- [ ] Merge the A10 **T8010 SPI** enhancements into `spi-apple.c`; add t8015 data.
- [ ] Port **`apple_z2.c`**; add a D21 multi-touch node (ADT: `hid-transport,k1`, SPI1, IRQ 292).
- [ ] Build an **A11 touch firmware** container (`dfrmtfw-d21-…`) with `makez2fw`
      (`--dynamic-calibration`).
- [ ] Contribute the **A11 touch calibration bridge** in m1n1 (ADT `syscfg` → DT).

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
