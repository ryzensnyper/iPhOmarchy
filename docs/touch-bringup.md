# Touch bring-up (A11 / D21) — WORKING

**Status (2026-10-30): touch works.** Six-finger multitouch with pressure/tool and
palm/hover suppression over evdev; continuous idle/hover and drag streaming. Series state:
`patches/0001`-`0036` on kernel tree `a11-port`. The sections below record how it was
decoded and brought up, the measured wire laws, and the open items.

**Open, in order:**
1. **Still-contact refresh cadence** — stationary holds deliver in ~0.3-1 s bursts every
   ~1.9 s while active drag streams continuously; the suspect set is the three
   small-integer Boot Sequence pokes (`0x10003058`=6, `0x1000305c`=2, `0x10003518`=1).
2. **Palm rejection for pressed palms** (tool-size rule; resting palms already drop via
   the pressure filter).
3. **Boot-mode variance** — reloads roll healthy / phantom-transient / half-rate /
   dead modes; find the selector instead of re-rolling.

This was the gate for a usable graphical shell: the USB port is **device-mode only** (no
USB keyboard/mouse), so without touch a compositor is unreachable on the device. Software
rendering is fine (`labwc` on `simpledrm` with `WLR_RENDERER=pixman`, as henrikklee does on
iPad) — input was the blocker.

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

## Status (2026-10-30): boot variance SOLVED, idle delivery fixed by the Boot Sequence pokes; touch-path gate open

Patch series state (`patches/` `0026`-`0033`, kernel tree `a11-port` at `afadcefa7`, tag
`d21-gold`):

| Piece | State |
|---|---|
| Kext-faithful interrupt pull (`[EB][seq][00]`+0xAA filler, seq after consume) | ✅ patch 0026 |
| `read_now=`/`kick=` vs unload race fix (field-captured NULL oops) | ✅ patch 0027 |
| Boot Sequence pokes (`poke=`/`poke_after=` blob-path params) | ✅ patches 0028 — idle metronome → continuous 20-40 fps |
| HBPP register read (0x1c73) + `poke_readback=`/`regread=` | ✅ patch 0029 |
| `poll_hz=` runtime poller + hazard doc | ✅ patches 0030/0031 — DO NOT enable (see below) |
| Poke-retry experiment | ✅ patches 0032/0033 — retry REMOVED (made rejected-poke boots fully silent); `poke_delay_ms=50` settle is the fix |

**Boot-to-boot variance solved** (`poke_delay_ms=50`, default): the container's readiness
probe completes ~20 µs before the driver's first poke, so on some boots the first poke is
REJECTED (ack `0000`) and delivery degrades to the 1.9 s metronome. A rejected first poke is
pure timing — settle 50 ms before the poke lists and every probe-time poke is accepted
(verified: 0 rejections, 23.9 fps continuous, p50 25 ms). **Never retry a rejected poke**
(measured: the boot goes fully silent — worse than the metronome; a reload re-rolls).

**Container tail vs fwconfig discrepancy [4]**: the fwconfig Boot Sequence says poke[4] =
`10003458:1` but the container's five `0x331e` register-write records carry `10003518:1`.
Both boot healthy; the container bytes are treated as authoritative (the gold config uses
`10003518:1`). The container tail also carries the pokes as kext-style register writes —
the 10-30 conclusion that "the driver must replay them via `poke=`" was about REDUNDANCY:
the driver replays them after `poke_delay_ms`, which is what makes the acceptance reliable.

**`poll_hz>0` wedges the D21 controller** (patches 0030/0031): off-IRQ pulls return
all-zero, the stream collapses, and the poisoning SURVIVES rmmod + 45 s rails-off — only a
force-restart recovers. Same persistence class as `dma_min=`/`ip_delay=`. Never combine
either with the pokes. iOS never pulls without an IRQ, so no firmware path serves
off-schedule pulls.

**fw-mode register reads do not exist** (patch 0029): the 0x1c73 read-register command is
bootloader-only — in fw mode every read returns the pull-response echo. A poke value's
EFFECT is the only observable; `poke_readback=` verifies only via boot-log acks.

### The open problem: the touch-path delivery gate

Measured law on a healthy boot (labeled-gesture seqtest runs):

1. idle/hover: continuous, p50 = 25 ms
2. **sustained still contact: ~1.9 s metronome ticks** (1-2 frames per tick)
3. active drag: adapts, gaps tighten to 250-600 ms
4. short contacts (<2 s): continuous (p50 = 122 ms)

The gate is in the controller, below HL state (0x72 reads Active throughout) and below the
scan engine (0xf8 counters climb in every state). Prime suspects: the three unswept
small-integer pokes `0x10003058` (=6), `0x1000305c` (=2), `0x10003518` (=1) — sweep them
against the sustained-touch tick (the 0x10003060 sweep killed streaming at 0/0x40; it is a
threshold/enable, not the interval). Note: the 0xf8 report layout MUTATES with fw state
(header u16 `0007`/`0004`/`0000`) — do not hardcode offsets.

### Operating notes

- After any boot: `dmesg -n 1` (+ optionally unbind vtcon1) **before** starting any fb UI —
  the console rendering the kmsg flood cooked/froze a phone once.
- Multi-finger contact (e.g. picking the phone up) on a degraded (metronome) boot wedges
  delivery permanently; the phone must lie flat during tests.
- Full calibration set matters: `z2-shapeaccel.bin` was missing until 10-29/30 (zeroed
  208 B blob every boot); with all four blobs loaded, degraded boots showed 0 phantom
  records and denser hover (~17-40 fps).
- Health check (passive, ~15 s): capture kmsg, decode with `decode44-full.py`; healthy =
  hover st=4 records at p50 ≤ 50 ms, zero gaps > 500 ms after startup.


