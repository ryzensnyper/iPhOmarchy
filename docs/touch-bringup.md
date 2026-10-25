# Touch bring-up notes (A11 / D21)

Touch is the gate for a usable graphical shell on this phone: the USB port is **device-mode
only** (no USB keyboard/mouse), so without touch a compositor is unreachable on the device.
Software rendering is fine (`labwc` on `simpledrm` with `WLR_RENDERER=pixman`, as henrikklee
does on iPad) — input is the blocker.

## What the hardware is (from the ADT)

```
spi1 @0x2E404000 (compatible spi-1,samsung)  IRQ AIC 292, clock-gates [75], clock-ids [333]
└── multi-touch   compatible "hid-transport,k1"
    ├── reg = <0x7c 0x0 ...>                      (controller registers)
    ├── interrupts = <102 0x06000000>             (via pinctrl_ap line 102)
    ├── function-reset      = pinctrl 36 GPIO(0x21)
    ├── function-enable_cs  = pinctrl 36 GPIO(0x8a)
    ├── function-power_ldo  = pmgr pKW4('rBK3')
    └── function-clock_enable = TCLK(0x8, 0x64, 0x8000)
```

The SPI **controller** is already supported (`spi-apple` matches `apple,spi`) and this project
has it working — see `patches/0001`. The **touch controller** (`hid-transport,k1`) has no driver
in-tree.

## The `k1` family insight

The A10 iPad 7/iPhone 7 touch firmware is named `dfrmtfw-j172-**k1**f19-6.bin`, and the A11 ADT
compatible is `hid-transport,**k1**`. So A11 is the **same k1 family, same HBPP14 firmware-upload
mechanism** as the A10 work in
[Pauli1Go/HoolockLinux](https://github.com/Pauli1Go/HoolockLinux) (whose `docs/touch.md` is a
full bring-up guide). Their `drivers/input/touchscreen/apple_z2.c` is the port base.

Port shape (see [bringup-plan.md](bringup-plan.md) for the full surface):

1. Their touch lifecycle: power/reset → SPI config → HBPP14 firmware upload via **SmartIO DMA**
   → two firmware-ready IRQs → DeviceInfo → D9 surface descriptor → report init → runtime IRQ.
2. We need A11 equivalents of: the touch clock (`clk-apple-t8015-touch`), SmartIO + SIO-DMA
   (`iop,t8015`, `sio@2EE00000`, IRQ 308-311), and an A11 touch firmware blob
   (`apple/dfrmtfw-d21-k1....bin` plus `apple/t8015-smartio.bin`).
3. Calibration (multitouch/orb-gap/orb-force/shape-dynamic-accel) lives in the ADT as `syscfg`
   references; the A10 project's patched m1n1 copies these into the Linux DT. We need the A11
   equivalent.

Their documented effort for A10 touch alone was ~11 days (with Codex assistance). Budget weeks,
not hours.

## Firmware provenance

Touch/SmartIO firmware comes from the matching device's firmware and must be extracted legally
by the user (same IPSW path we used for the ADT — see [../tools/README.md](../tools/README.md)).
It is **not** included in this repo.
