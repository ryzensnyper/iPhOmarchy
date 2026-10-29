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
   (`apple/dfrmtfw-d21-c1f5e-3.bin` plus `apple/t8015-smartio.bin`). Note the D21 touch firmware
   personality is `c1f5e`, the **same as A10 D111** (`dfrmtfw-d111-c1f5e-2.bin`) — not the J172
   iPad's `k1f19`.
3. Calibration (multitouch/orb-gap/orb-force/shape-dynamic-accel) lives in the ADT as `syscfg`
   references; the A10 project's patched m1n1 copies these into the Linux DT. We need the A11
   equivalent.

Their documented effort for A10 touch alone was ~11 days (with Codex assistance). Budget weeks,
not hours.

## Status (2026-10-26)

Branch `a11-port` in the Hoolock kernel tree now carries the four software pieces:

| Piece | State |
|---|---|
| Touch clock (`clk-apple-t8010-touch.c` + t8015) | driver + DT; PMGR offset `0x78000` **inferred from T8010, unverified** |
| SmartIO + SIO-DMA | ported; DT `sio@22ee00000` **disabled** (probing boots the coprocessor) |
| SPI (`spi-apple.c`) | merged with `apple,t8015-spi` → T8010 legacy path (D21 spi1 is `spi-version 1`) |
| `apple_z2.c` | full Pauli driver ported; **no D21 board entry yet** |

Remaining (all need a live device / m1n1):

1. A `apple_z2_d21_info` variant: D21 firmware personality matches D111 (iPhone protocol path),
   but the ADT power sequence is `power_ana → power_ldo → clock_enable` (ana/ldo GPIOs + the touch
   clock) rather than A10's `hv`/`core` regulators — so the power path needs a D21-specific variant.
2. The D21 multi-touch DT node (GPIOs: reset `pinctrl 36 GPIO(0x21)`, enable_cs `GPIO(0x8a)`,
   IRQ line 102 edge-falling, power_ana `pmgr 98:dpLE(0x302)`, power_ldo `pmgr 75:pKW4('rBK3')`).
3. Calibration blobs from m1n1 (`syscfg` → DT `apple,z2-*-cal-blob`).

## Firmware provenance

Touch/SmartIO firmware comes from the matching device's firmware and must be extracted legally
by the user (same IPSW path we used for the ADT — see [../tools/README.md](../tools/README.md)).
It is **not** included in this repo.

## Status (2026-10-29): TOUCH WORKS

The blocker was never the protocol — it was **power**. The D21 touch controller's high-voltage
analog rail (mutual-cap drive) is the `display-pmu,chestnut` I2C PMIC switch that the ADT names
as `function-power_ana = 98:dpLE(0x302)` — the FIRST step of iOS's touch power sequence
(power_ana → power_ldo → clock_enable). Nothing in the Linux stack turned it on: i2c0 was
`disabled` in our DTB. With `touch_hv` enabled first in the power sequence (patches
`0020`+), the 0x44 contact frames flow immediately.

Patch series state (`patches/0020`-`0024`, kernel tree `a11-port` at `57e788b91`):

| Piece | State |
|---|---|
| Chestnut touch-HV regulator + i2c0/PMIC DTB | ✅ patch 0020 — THE fix |
| 0x44 contact decode | ✅ patches 0023/0024 — signed surface units (d9 range, e.g. x −224..6608), state byte = event mask (bit0 Touch) |
| Driver arming (c8=09, bf mode 1) built in | ✅ patch 0022 — bare insmod works; `arm=0` for raw A/B |
| Runtime diagnostics | ✅ `verbose=` / `read_now=` / `frame_dump=1` knobs |

Container rule (learned 2026-10-29 the hard way): the flashed container **must be the
C1F5E,4-personality image** (fw 0x0773, `dfrmtfw-d21-c1f5e-4.bin` copied over the DT-named
`...-3.bin`). The Apple C1F5E,3-era container ("original", fw 0x0753) boots the panel but runs
the wrong firmware generation: scan rate halves (14 vs 34 Hz), frames batch ~2 s apart, edge
ghosts multiply, and the pipeline dies after ~6 min. Verify with the d3 property read:
bytes [3..4] must read `07 73`.

Frame-decode ground truth (live-stream capture, `tools` in the session logs):

- 0x44 msg: `[0]=0x44 [1]=seq [16]=nfingers`, fingers at +24, 30 B each:
  +0 finger id, +1 state (bit0 Touch, bit1 Range, bit2 Position), +4/+6 abs_x/abs_y
  (le16, signed surface units), +12/+14 tool major/minor, +26 pressure.
- Real touches: state 1 (tap), 2 (range/hover), 7 (touch+range+position), 0 (lift).
- **Ghost contacts**: four FIXED positions at raw x = −224..−210 (= exactly `min_x`, the left
  sensor edge), plausible finger sizes, full touch lifecycle, bursts every ~20-200 s. iOS
  presumably filters them by bounds; open question whether they are a hardware/analog marginal
  (edge columns) or a missing runtime recalibration.

Open issues (in order):

1. Ghost contacts at the left sensor edge (clamped to screen x≈0 by the driver).
2. Frames batch ~2 s apart during sustained contact; short taps stream fine (1→2→7→0 in
   ~0.3 s). IRQ line silent between batches — controller-side assert cadence suspected.
3. Console-blanking side quests resolved: the display must be unblanked for fb work; blanking
   is NOT the death mechanism (verified by trace).

## Status (2026-10-29 late): 6-point multipoint tracking, ghost-free boot

A heavily-used session (26+ min, 3954+ frames, kernel `a11-port` at `223613ead`) showed what
this hardware does when the edge ghosts stay quiet:

- **Six independent real contacts tracked simultaneously** (0x44 records, positions drifting
  per-frame, per-finger pressure 28-97, tool sizes 440-5450).
- **Palm/hover discrimination for free**: large contacts (tool ≈5450) with pressure 0 and
  state without the Touch bit (st=4 = Position only) arrive as hover records — the driver's
  `state & 1` check suppresses them, which is exactly palm rejection.
- **Delivery fine-grained**: 76% of inter-frame gaps < 150 ms; the ~2.05-s batch cadence of
  earlier boots was absent.
- **One ghost frame in 3668.**
- **No pipeline death** in 26+ min (earlier boots died at 6-25 min — signature: controller
  goes silent, then firmware crashes with scan frozen and the IRQ line stuck low for a
  ~1.5 kHz storm of ~178k IRQs, then quiet).

Working theory: the left-edge ghost contacts (fixed positions at raw x = exactly `min_x`,
i.e. sensor column 0) are the common root cause — when they fire, delivery batches and the
pipeline eventually crashes; when they stay quiet, everything streams. Next: catch a
ghost-active boot with the trace running, and inspect the edge-channel calibration
(`orb-gap-cal`, `mtcl` blobs; check whether column 0 has a baseline at all).


