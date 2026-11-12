# The PMGR bridge windows — and the GPU's own block (AGX_PMGR)

Status: offline finding (2026-11-12, after boot #11).  Nothing in this file has
been read from hardware yet; boot #12 is the read-only probe.

## 1. What the ADT says

`/arm-io/pmgr` (raw ADT `dt_raw.bin`, parsed with m1n1's `adt.py`):

| property | value |
|---|---|
| `#bridges` | `13` |
| `bridge-reg-index` | `19` |
| `optional-bridge-mask` | `0x800` (bit 11 → the SBR bridge is optional) |
| `bridge-counters` | 13 × `u32` (`0, 0x800000, 0x800000, 0x800000, 0x400000, …`) |
| `bridge-counter-version` | `1` |
| `reg` | 32 windows; `reg[0] = 0x32000000/0x1000000`, `reg[1] = 0x35200000/0x1000000`, … |

`bridge-reg-index = 19` is a **reg index**: bridge *b*'s register window is
`reg[19 + b]`.  There are 13 bridges and exactly 13 reg entries from index 19
to 31, which is the second half of the proof.

## 2. Which bridge belongs to which device

Every `pmgr/devices` entry carries a 16-bit group id (m1n1's `adt.py` calls the
field `unk3`, `Int32ul` at the end of the entry).  Only the *subsystem* entries
have a non-zero value:

| device | ADT id | group = bridge |
|---|---|---|
| MSR | 25 | 1 |
| JPG | 26 | 2 |
| VENC_SYS | 27 | 3 |
| VDEC0 | 119 | 4 |
| ISP_SYS | 24 | 5 |
| RTMUX | 16 | 6 |
| DISP0_BE | 29 | 7 |
| **GFX** | **124** | **8** |
| AVD_SYS | 158 | 9 |
| PCIE | 56 | 10 |
| SBR | 49 | 11 |

Bridge 11 = SBR is the one the `optional-bridge-mask = 0x800` bit selects —
consistent with the bit-per-bridge reading of that property.

## 3. Proof that `reg[19 + b]` is the bridge window

Three bridge windows coincide with register bases of real device nodes:

| group | bridge window | device node base |
|---|---|---|
| 5 (ISP_SYS) | `reg[24] = 0x0F000000` / `0x11000` | `isp` = `0x0F000000` / `0x3681000` ✔ |
| 9 (AVD_SYS) | `reg[28] = 0x28000000` / `0x9000` | `avd` = `0x28000000` / `0x2000000` ✔ |
| 3 (VENC_SYS) | `reg[22] = 0x23000000` / `0x9000` | `ave` = `0x23000000` / `0x10000` ✔ |

So the "bridge" is the AXI→Apple-Fabric port block that fronts that
subsystem.  If the port is down, the whole subsystem is unreachable from the
AP even though its power domain can read ACTIVE.

## 4. The GPU's bridge: `0x05000000`

GFX is group 8, so its window is

```
pmgr reg[27] = 0x05000000, size 0x9000
```

No node in the Linux D21 DT maps it (`pmgr` is mapped as `0x8c000` only), and
nothing in the kernel ever touches it.  In the kernelcache, `ApplePMGR`
contains a 94-entry table of block names (`0xfffffff006c9cde8`, stride `0x50`)
in this order:

```
PMGR, MINI, PMGR_SOC_EAST, PMGR_SOC_SOUTH, MPMGR_AON, MPMGR, AGX_PMGR,
PMP_EXT_SW_GEN, PTS_PTD, ACC_PWRCTL, …, DOCKFIFO, CPU_FABRIC, NRT_FABRIC,
RT_FABRIC, LIO_CLK_RST, … GFX_TVM, GPU_TRIG_CTL, PMGRClkGenSOC, …
```

`AGX_PMGR` is the GPU's own PMGR block, i.e. the `0x05000000` window.

## 5. What ApplePMGR does with it

`ApplePMGR::initDriver` (`0xfffffff0056525f0`…`0xfffffff005652b20`) reads
`#bridges`, `bridge-counter-version`, `optional-bridge-mask`,
`bridge-reg-index`, `bridge-counters`, `bridge-counter-configs`, allocates
`#dies × 0x40` bytes per bridge and then, per bridge `b` and die:

```
w28 = bridge-reg-index + b                     ; 0xfffffff005652960
x0  = getDeviceMemoryWithIndex(w28)            ; 0xfffffff005652990
…                                              ; vaddr at ofs 120
log "ApplePMGR: [Die %u] Bridge %u, virtual address … physical address …"
```

and, when the reg index is missing:

```
log "ApplePMGR: %s:%u Bridge %d has no mapping"
```

So the property is a plain reg-index base — we can reproduce the mapping
without any kext.

The same kext has GFX-specific accessors (assert strings in `__PRELINK_TEXT`):

```
UInt32 ApplePMGR::readGFXClkGenReg(UInt32, UInt32, UInt32)          @0xfffffff004de1873
void   ApplePMGR::writeGFXClkGenReg(UInt32, UInt32, UInt32, UInt32) @0xfffffff004de18ae
void   ApplePMGR::waitGFXClkGenReg(…, 6 args)                       @0xfffffff004de18f0
```

i.e. the GPU's clock generator is programmed through a dedicated register set
in this block (PLL/divider/enable), separate from `PMGRClkGenSOC`.
There are also `readANEClkGenReg` / `readPMGRClkGenSOCReg` variants, so the
layout is a family: `ClkGen` base + per-register offset + bitfield.

## 6. Why this explains everything so far

| observation | explanation |
|---|---|
| `ps_gfx` reads `0x1f0003ff` (ACTIVE) | the GPU's *power domain* really is up; the domain state says nothing about the fabric port or the GPU clock generator |
| every read inside the GPU block hangs (`RGX+0x18`, `IOP+0x4008`, `Fender+…`) | a disabled AXI2AF bridge does not respond to the fabric — the AP waits, the bus watchdog resets the phone |
| DVFS/perf windows read 0 | they are a different block; the GFX clock is not set through them |
| the PMP accepts our messages but nothing happens | `PMPEndpoint1` (ep 32) was never *started* (no `STARTEP`), and the PMP does not gate the fabric port on its own unless told to |
| iOS works | `ApplePMGR` maps and configures bridge 8 (`AGX_PMGR`) at start; iBoot leaves it in a state the kernel then adjusts |

## 7. Boot #12 plan (read-only, then act)

1. `apple_rtkit_start_ep(pmp, 32)` **before** sending anything to ep 32
   (an unstarted application endpoint is the likely reason boot #11's six
   messages produced no syslog reaction).
2. Map and dump `0x05000000` (GFX bridge / `AGX_PMGR`, `0x9000`) — first
   `0x80` bytes verbatim, then every non-zero word, cap ~40 lines.
3. Do the same for `0x19000000` (DISP0_BE bridge, group 7) as the
   known-good/clocked reference; it is a PMGR window too and the display is
   demonstrably running (`simplefb`).
4. Keep the `ps_gfx` retoggle and the `IOP+0x4008` read last: the read is
   still the single verdict on whether the block woke up.
5. Only then decide the write (expected: a `ClkGen` enable/divider pair, and
   possibly a bridge enable bit) from the two dumps — a blind write to a PMGR
   window that may contain other domains' clock registers is not acceptable.

## 8. Safety notes

* Both windows are **PMGR register blocks** (always-on fabric), not device
  MMIO: reads should not hang even when the port is down.
* Do not write anything outside `0x05000000`/`0x19000000` in this test; a
  wrong write in a shared PMGR window can take down DRAM/CPU clocks.
* `0x05000000` is 0x9000 long; never read past it.
