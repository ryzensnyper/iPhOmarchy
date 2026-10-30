# Omarchy on iPhone 8 Plus (D21 / A11) — plan & reality

> **Historical (2026-10-25, pre-touch).** Current state: [ROADMAP.md](ROADMAP.md) and
> [touch-bringup.md](touch-bringup.md). The hardware port surface below is still the
> reference for the remaining drivers (Wi-Fi/BT).

Status date: 2026-10-25. Companion to `/home/doug/checkm8-kit/HANDOFF-2026-10-25.md`.

## What already works (baseline)

* Dual-boot: iOS intact on `nvme0n1p1`; Arch Linux ARM installed on `nvme0n1p2`.
* Boot: pongoOS + checkm8 (via **palera1n**, not checkra1n) → `m1n1` → Hoolock kernel
  `7.3.0-rc1-g6831bc701a6c-dirty` (built by `doug@omarchy`).
* Working: main display (**simple-framebuffer**, `simpledrm`), brightness, buttons, NVMe,
  USB2 device-mode gadget (`172.16.42.1`, ssh `alarm`/`alarm`), battery/charger info (SMC),
  cpufreq, RTC, watchdog.
* Kernel tree: **HoolockLinux/linux** branch `hoolock`. m1n1: **HoolockLinux/m1n1** `idevice`.
  Docs: **HoolockLinux/docs**.

## The hard truth about wifi / touch / BT / GPU

From Hoolock `docs/features/A11.md` (and `A10.md`): **none of wifi, Bluetooth, or touch are
listed as supported on any device**, and **GPU + Display Pipe are `TBA`** ("active work is not
being undertaken at this time"). henrikklee's iPad 6 touch+WiFi is his **own** driver work
("repo with … drivers … coming soon"), not upstreamed.

So these are **original driver bring-up**, not configuration. Effort, in order of tractability:

| Subsystem | Where it lives | Effort | Notes |
|---|---|---|---|
| **Bluetooth** | Broadcom UART, upstream `hci_bcm` | days | Needs a DT node on `serial0` (`apple,s5l-uart`) + firmware + `CONFIG_BT_HCIUART_BCM`. Best "prove the pipeline" target. |
| **Touch** | Apple SPI controller + touch controller | days–weeks | The **gate**: phone USB is device-mode only, so no USB kbd/mouse ⇒ a graphical shell is useless without touch. Refs: Asahi `spi-apple`, apple touch drivers. Needs SPI controller DT + touch DT + driver. |
| **Wi-Fi** | Broadcom **PCIe** + `brcmfmac` | weeks | Needs PCIe controller DT (`apple,t8015-pcie`), SART/DART DMA, firmware match. |
| **GPU (G11P)** | Apple AGX | **out of scope** | No mainline driver; Asahi AGX targets M-series. `TBA` upstream. |

Display note: with only `simpledrm`, a wlroots compositor still runs via
`WLR_RENDERER=pixman` software rendering — so a shell is possible **without** the GPU, but
**only** once touch exists. That is exactly henrikklee's approach (`labwc`, not Hyprland).

## Findings after pulling the source (2026-10-25)

* Source cloned to `/home/doug/hoolock/linux` (branch `hoolock`, commit **6831bc701** = our running
  kernel) and `/home/doug/hoolock/docs`. Example config: **`docs/config_16k`** (16K pages).
* Baseline build works on this host with `LLVM=1 ARCH=arm64` (clang 22). Rebuilt
  `t8015-d21.dtb` is **byte-identical** to the kit's `d21-boot.dtb`, and `Image.gz` builds clean.
  DT-only changes need just `make dtbs` (seconds) — no full kernel rebuild.
* Drivers **already built in** (`config_16k`): `SPI_APPLE` (matches generic `apple,spi`),
  `SERIAL_SAMSUNG` (the `s5l-uart`), `SERIAL_DEV_BUS`+`BT_HCIUART_BCM` (Broadcom UART BT),
  `APPLE_DART`, `PCIE_APPLE`, `NVME_APPLE`, `APPLE_SART`, `BACKLIGHT_APPLE_DWI`.
* **PCIe caveat:** `drivers/pci/controller/pcie-apple.c` only has `apple,pcie` → `t8103_hw`.
  A11 PCIe needs new driver `data` + a DT node.
* **Bluetooth caveat:** on t8103/t8112/t600x the BT node is a **PCIe function**
  (`compatible = "pci14e4,5f71"`). If A11 is the same, BT is *not* a simple UART serdev and
  shares the PCIe blocker with Wi-Fi.
* **SPI/touch caveat:** the DTS has no SPI controller node and there is no touch driver in the
  tree for Apple phones; touch needs a controller node **and** touch-controller work.
* `t8015.dtsi` today has: `serial0`, `i2c0..3`, USB (dwc2/ehci/ohci), `aic`, `pmgr`/`pmin`,
  `dwi_bl` backlight, `pmp`, 4×`pinctrl`, `spmi`, `wdt`, `smc`, `sart` (IOMMU), `nvme`. No
  pcie/spi/bluetooth/display/GPU nodes.

### The unblocking artifact: the ADT

The authoritative hardware description for a specific device is Apple's **ADT** (Apple Device
Tree), which m1n1 parses. It lists the real register windows, interrupts, GPIOs and chip
compatible strings for the *actual* silicon. Writing accurate DT nodes for touch / BT / Wi-Fi /
PCIe needs it. Next step: dump the ADT from the device (m1n1 / pongoOS session).

## Progress log

### 2026-10-25 — SPI controller brought up (loop validated)
Added `spi1` (`apple,t8015-spi`, `apple,spi`) to `arch/arm64/boot/dts/apple/t8015.dtsi` from the
ADT (`reg 0x2E404000`, AIC IRQ 292, `power-domains = <&ps_spi1>`). Built with `make dtbs` only,
repacked via `step6/make-blob.sh` (shipped kernel unchanged) → booted: **`/sys/class/spi_master/spi0`
exists and the platform device `22e404000.spi` binds to the `spi-apple` driver.** No kernel
rebuild, no PC heat. This proves the edit-DT → build → flash loop works; every future node uses it.

Procedure that now works:
```
# edit arch/arm64/boot/dts/apple/t8015.dtsi in ~/hoolock/linux
make -j$(nproc) LLVM=1 ARCH=arm64 dtbs
cp arch/arm64/boot/dts/apple/t8015-d21.dtb ~/checkm8-kit/linux-kit/step6/d21-boot.dtb
cd ~/checkm8-kit/linux-kit/step6
BOOTARGS="root=/dev/nvme0n1p2 rootwait rw console=tty0" ./make-blob.sh ../m1n1-linux-p2-<tag>.bin
# then: boot iOS -> palera1n -p -> pongoOS -> pongoterm: /send <blob> ; bootm
```
Note: `palera1n -p` holds USB interface 0 while its shell runs — quit it (Ctrl-C) **before**
`pongoterm`. `usbmuxd` must be running for palera1n to find the iOS device.

### 2026-10-25 — uart1 (Bluetooth H4 UART) added
Added `serial1: serial@22e604000` (`apple,s5l-uart`, AIC IRQ 283, `ps_uart1`) to `t8015.dtsi`,
status `okay`. Payload: `m1n1-linux-p2-uart1.bin`. Expected: a second tty appears.

Bluetooth notes: ADT BT child is `bluetooth,n88` (Transport speed 3,000,000; Apple vid `0x5ac`,
product 4768; wake/power via pinctrl 36 + pmgr `pKW4('gP09')`). **No kernel driver** matches it
(`hci_bcm` only knows `brcm,bcm*`), and `samsung_tty` has **no serdev support** — so the viable
route is **userspace over the tty** (`btattach`/`hciattach` with an Apple/Broadcom protocol),
not a serdev driver. The child node is left commented in the DTS with the ADT data.

## KEY REFERENCE: Pauli1Go/HoolockLinux (A10 bring-up, working touch/wifi/BT)

`github.com/Pauli1Go/HoolockLinux` (branch `hoolock`) is a Hoolock fork with a **working** A10
(T8010) bring-up — validated on **iPhone 7 Plus (D111)** and iPad 7 (J172): touch (multi-touch),
Wi-Fi (BCM4355C1/`brcmfmac`), Bluetooth (BCM4355C0/`hci_bcm`), battery/charging, NVMe root.
Companions: `Pauli1Go/HoolockLinux-bringup-docs` (`docs/touch.md`), `Pauli1Go/HoolockLinux-linux-firmware`,
`Pauli1Go/m1n1` / `m1n1-ipad7` (patched loader: publishes NVMe HMB + touch calibrations into DT).

Driver/DT additions to port (A10 -> A11):
```
drivers/clk/clk-apple-t8010-touch.c      PMGR touch clock
drivers/soc/apple/apple-sio-core.c       SmartIO coprocessor (firmware upload DMA)
drivers/dma/apple-sio-dma.c              SIO DMAengine
drivers/spi/spi-apple.c                  T8010 SPI (DMA, word sizes, CS, PIO)
drivers/input/touchscreen/apple_z2.c     touch protocol (HBPP14 fw upload, Z2 framing, reports)
drivers/pci/controller/pcie-apple.c      + T8010 PCIe host bridge
drivers/bluetooth/hci_bcm.c              + BCM4355C0 (brcm,bcm4355c0-bt)
brcmfmac + SysCfg/NVMEM                  Wi-Fi firmware/calibration
arch/arm64/boot/dts/apple/t8010*.dtsi    board DTs
```

**Why this maps to us well:** the A10 iPad 7 touch firmware is `dfrmtfw-j172-**k1**f19-6.bin`, and
**our A11 ADT touch compatible is `hid-transport,k1`** — the *same k1 family and HBPP14 mechanism*.
So `apple_z2.c` is a direct port base; we need a D20/D21/D22 firmware blob and t8015 wiring.

### Concrete port surface (measured 2026-10-25)

Their fork base = **7.2.0-rc1**; ours = **7.3.0-rc1** (one release; drivers should port with minor
friction). Raw `diff -rq` is useless (base drift touches almost every file) — port by *file*.

| Item | Path | A11 action |
|---|---|---|
| Touch protocol | `drivers/input/touchscreen/apple_z2.c` (2450 L) | add D20/D21/D22 board + A11 fw name + GPIOs (ADT) |
| SmartIO core | `drivers/soc/apple/apple-sio-core.c` (953 L) | add `iop,t8015`; ADT `sio` reg `0x2EE00000`+0x20000, IRQ 308-311 |
| SIO DMA | `drivers/dma/apple-sio-dma.c` (504 L) | mostly generic |
| SPI | `drivers/spi/spi-apple.c` (theirs, 1048 L) | merge; add t8015 clock/descriptor data (spi1 base already up) |
| Touch clock | `drivers/clk/clk-apple-t8010-touch.c` (206 L) | add t8015 PMGR offsets |
| PCIe bridge | `drivers/pci/controller/pcie-apple-h9p.c` (separate!) | add t8015: ADT `apcie` ECAM `0x61000000`, IRQ 340-349 |
| Bluetooth | `drivers/bluetooth/hci_bcm.c` | add A11 BT binding (`bluetooth,n88`, product 4768) + gpios + `.hcd` |
| Wi-Fi | brcmfmac + SysCfg/NVMEM | BCM4357 (`wlan-pcie,bcm4357`, PCIe port 3) + fw/cal |
| DT | `arch/arm64/boot/dts/apple/t8015*.dtsi` | add sio/sio-dma, touch@spi1, apcie, uart1-BT nodes |
| Firmware | `apple/t8015-smartio.bin`, `apple/dfrmtfw-d21-k1*.bin` | extract from A11 IPSW |
| Loader | `Pauli1Go/m1n1` patches | A11 touch calibrations + NVMe HMB injection |

A11 SIO ADT (for the DT): `sio@2EE00000` compatible `iop,t8015`, `interrupts = <309 308 311 310>`,
`clock-ids [299,300]`, `power-gates [90]`; child `iop-sio-nub` → `sio-dma` (`sio-dma-controller`).
A11 touch clock: ADT `uart/sio` clock ids + PMGR (map when porting `clk-apple-t8015-touch`).

### Porting shape (A10 -> A11)

1. Add **T8015 hw info** alongside T8010 in `pcie-apple` (PCIe host bridge + DART/SART).
2. Port **SmartIO + SIO DMA** and the **touch clock** to t8015 PMGR offsets.
3. Add **spi1** (done, controller up) + a **D21 multi-touch node** (from the ADT) and adapt
   `apple_z2.c` (new firmware name, GPIOs, controller units).
4. **Bluetooth**: add `uart1` (done) + `hci_bcm` binding for the A11 BT (`bluetooth,n88`,
   product 4768) and a matching `.hcd`.
5. **Wi-Fi**: t8015 PCIe node (`apcie,t8015`, ADT data captured) + `brcmfmac` BCM4357 firmware.
6. Supply device firmware/calibration (extract from the A11 IPSW / device) and, if needed, the
   patched m1n1 pieces (HMB + touch calibrations) for A11.
7. Wire m1n1 bootargs to load an initramfs that carries the firmware (probe needs it early).

Firmware needed (A10 names shown; A11 equivalents TBD): `apple/t8010-smartio.bin`,
`apple/dfrmtfw-<board>-k1....bin`. A11 SmartIO fw and touch fw must come from D20/D21/D22 firmware.

## Build environment (host = this CachyOS PC)

From docs/tutorials/SETUP.md:
```
make -j$(nproc) LLVM=1 ARCH=arm64 Image.gz dtbs      # after placing config_16k as .config
```
Then repack the payload: `step6/make-blob.sh` (m1n1.bin | bootargs | dtb | Image.gz).
Boot it exactly like stages A/C in the checkm8 kit, then `pongoOS` → `pongoterm`.

## Plan

1. **Reproducible build** — clone Hoolock linux + docs; build stock `config_16k` for t8015; confirm
   our rebuilt `Image.gz` + `t8015-d21.dtb` boots identically. (Establishes the loop.)
2. **Bluetooth** — add `bluetooth`/UART node to the D21 DT, enable `hci_bcm` + firmware; verify
   `hciconfig`/`btmon` sees a controller. (Fastest end-to-end win.)
3. **Touch** — bring up the SPI controller + touch controller in DT; port/adapt the touch driver;
   verify an input device appears and events flow.
4. **Compositor** — labwc (pixman) + a touch-adapted shell/launcher (model on henrikklee's
   "touch adapted shell"); layer Omarchy's opinions (`jondkinney/armarchy`, aarch64) on top.
5. **Wi-Fi** — PCIe + brcmfmac + firmware; last of the "possible" items.
6. **GPU** — not attempted.

## Shortcuts to watch

* **henrikklee** (x.com) — "repo with install instructions, tooling, drivers and touch adapted
  shell"; previewed a single-command install. iPad 6 is A10 (T8000-class) vs our A11, but both
  are on the same Hoolock tree, so porting is realistic.
* **ivan.codes** — ported Omarchy to a Pixel 4 via postmarketOS + Arch Linux ARM; repo TBA.
* **jondkinney/armarchy** (`amarchy-3-x`) — Omarchy aarch64 install for Arch Linux ARM.

## References

* Hoolock linux: https://github.com/HoolockLinux/linux (branch `hoolock`)
* Hoolock docs:  https://github.com/HoolockLinux/docs   (features/A11.md, tutorials/SETUP.md)
* m1n1 (hoolock): https://github.com/HoolockLinux/m1n1 (branch `idevice`)
* Omarchy aarch64: https://github.com/jondkinney/armarchy (branch `amarchy-3-x`)
