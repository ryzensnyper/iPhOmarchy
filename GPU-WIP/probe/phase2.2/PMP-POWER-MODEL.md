# The A11 power model, as the ADT actually describes it

Everything here is decoded from the device tree the phone ships, not guessed.
The raw blob is `adt/dt_raw.bin`; **`adt/adt.txt` is lossy** (it drops
`pmgr/perf-regs` and `pmgr/pwrgate-regs` entirely), so decode the raw blob.

Tooling that already knows the formats: m1n1's
`proxyclient/m1n1/adt.py` (structures, `load_adt()`, `pmgr_dev_get_offset()`)
and `proxyclient/tools/dump_pmgr.py` (the report this note summarises).
One-liner:

```python
import sys; sys.path.insert(0, "<m1n1>/proxyclient")
from m1n1 import adt as A
dt = A.load_adt(open("adt/dt_raw.bin", "rb").read())
pmgr = dt["/arm-io/pmgr"]
```

`D21` and `D22` ship the same PMGR (same `devices`, `ps-regs`, `perf-regs`).

## 1. Registers

`pmgr/reg` is 16 regs; reg[0] is the 16 MiB PMGR at `0x232000000`, reg[1] is
`pmgr_mini` at `0x235200000`.

### Power state registers — `pmgr/ps-regs`

11 entries of `{reg, offset, mask}`.  A **device** with `psreg=i`, `psidx=j`
has its PS register at `pmgr.reg[i] + offset + 8*j` (m1n1:
`pmgr_dev_get_offset()`; the alternative "ps-groups" mode does not exist on
this SoC because `ps-regs` is present).

```
 [ 0] reg 1 (0x235200000) + 0x80000  mask 0x00200c53
 [ 1] reg 0 (0x232000000) + 0x80000  mask 0x0000013f
 [ 2] reg 0 (0x232000000) + 0x80100  mask 0xfffffbff
 [ 3] reg 0 (0x232000000) + 0x80200  mask 0xdffffeff
 [ 4] reg 0 (0x232000000) + 0x80300  mask 0x002a04ff
 [ 5] reg 0 (0x232000000) + 0x80400  mask 0x00000001
 [ 6] reg 0 (0x232000000) + 0x84000  mask 0x0000007f
 [ 7] reg 0 (0x232000000) + 0x88000  mask 0x00000000
 [ 8] reg 1 (0x235200000) + 0x80110  mask 0x00000040
 [ 9] reg 0 (0x232000000) + 0x80830  mask 0x0000000f
 [10] reg 0 (0x232000000) + 0x88000  mask 0x0000003d
```

Field layout (m1n1 `pmgr.c`): bit 31 reset · bit 28 auto-enable · bits 27:24
`PS_AUTO` · bit 11 parent-off · bit 10 device-disable · bit 9 was-clock-gated
· bit 8 was-power-gated · bits 7:4 actual state · bits 3:0 target state.
`0xf` = active.

Bank 4 (`0x80300`), every device named — **`0x80338` is `ps_gfx`**:

| offset | device | id | device `perf_idx` |
|---|---|---|---|
| `0x80300` | MSR | 25 | 0x11 |
| `0x80308` | PMP | 54 | 0x12 |
| `0x80310` | PMS_SRAM | 55 | 0x13 |
| `0x80318` | PCIE | 56 | 0x14 |
| `0x80320` | PCIE_AUX | 57 | — |
| `0x80328` | ANS2 | 154 | 0x1c |
| `0x80330` | PCIE_DIRECT | 155 | 0x15 |
| **`0x80338`** | **GFX** | **124** | **0x16** |
| `0x80350` | ISP_SYS | 24 | — |
| `0x80388` | VDEC0 | 119 | 0x19 |
| `0x80398` | VENC_SYS | 27 | 0x1a |
| `0x803a8` | AVD_SYS | 158 | 0x1b |

### DVFS/clock registers — `pmgr/perf-regs` (raw ADT only)

3 blocks of `{reg, offset, size}` (the same 12-byte shape as `ps-regs`):

```
 block 0: reg 0 (0x232000000) + 0xb4000  size 0x8c  (140 entries)
 block 1: reg 1 (0x235200000) + 0xb4000  size 0x20  ( 32 entries)
 block 2: reg 0 (0x232000000) + 0xfc000  size 0x0a  ( 10 entries)
```

Two index namespaces index block 0:

* `pmgr/power-domains` (21 entries, `{unk, perf_idx, perf_block, id, flags,
  name}`) — the DVFS domains.  `GFX` is `id 8`, `perf_block 0`,
  `perf_idx 0x2c`.
* the device table's own `perf_idx`/`perf_block` — `GFX` is `0x16`.

The exact per-register address is **not settled**: `dump_pmgr.py` computes
`pmgr.reg[block] + 0x100 + perf_idx*0x10` (i.e. ignores `perf.offset`), the
`perf-regs` entry says `+ 0xb4000`, and the plausible stride is `0x10` (140
entries would run `0xb4100..0xb4d00`).  For GFX the candidates are
`0x2320003c0` and `0x2320b43c0`.  Boot #9 dumps both windows read-only.

### No power gates

`pmgr/pwrgate-regs` — the "separate clock/power gate array" that later SoCs
have (and that m1n1 decodes as `PMGRPWRGateRegs`) — **does not exist on
T8015**.  There is no third register space hiding the GPU's gate.

## 2. The GPU's gates are PMP-owned

`sgx` declares `power-gates = [148, 123]` and `clock-gates = [148, 123]`;
`gfx-kf` declares `[149]`.  Those ids are devices:

| id | name | `no_ps` | parent | register |
|---|---|---|---|---|
| 148 | GFX-SGX | yes | GFX | **none** |
| 149 | GFX-KF | yes | GFX | **none** |
| 123 | GFX-BUSY | yes | GFX | **none** |

`no_ps` is m1n1's `PMGR_FLAG_VIRTUAL` (flags bit 4); m1n1 skips such devices
because they have no address at all.  `GFX` (124) itself has **no parents**,
so nothing above it holds it down either.

The PMGR node explains who can act on them: `pmp = 1`,
`pmgr-dock-fifo-agent = 1`, `pmgr-dock-fifo-channel = 3`.  The PMGR is an
agent of the PMP's *dock FIFO*, i.e. the hardware forwards power-state
transitions to the PMP; `sgx` additionally sets `pmp-sw-interrupt = 1`.
A PMGR write can therefore only ever be a *request* — the three virtual gates
above are what the PMP has to move.

## 3. What is not usable

* `clock-ids` (`sgx` = `[265]`, `gfx-kf` = `[269]`, `spi1` = `[334]`) index
  **nothing** on this ADT.  `/arm-io` has `clock-frequencies` (81 zeros) but
  **no `clock-frequencies-regs`** (the property m1n1's report uses for
  "fixed clocks"), and the `pmgr` clock tables stop at id 21.  Do not expect
  to resolve a register from a clock id.
* `adt/adt.txt` must not be used for register work: it is missing
  `perf-regs`, and it prints the device table's `offset`/`group` fields
  (`{offset:24, group:8}`) which are *not* addresses in `ps-regs` mode.

## 4. The PMP firmware's own switches

The image (`a11-fw/out/pmp-t8015.bin`) is raw 32-bit ARM, linked at
`0x01000000` (MMU-mapped onto its physical SRAM at `0x232500000`), Thumb-2
after the vector table.  At file offset `0x17c68` there is a tunable table of
12-byte `{size, default, byte-reversed 4CC}` entries:

```
DBUG=0xaff  DART=0  DOCK=1  PWRG=0  CLKG=1  NRGD=1  NRGS=1
PMON=1  PMUT=1  SMPL=0  TCAP=0  TGPH=0x3e8  BDID=…  PBAT=…
```

So dock handling and **clock gating are on by default** in the firmware; they
do not wait for a DT property.  `pmp-power-gating` (`PWRG`) defaults to 0 and
is the one feature the AP-side kext (`ApplePMPFirmware`, kernelcache strings
`pmp-clock-gating`/`pmp-power-gating`/`pmp-dock-fifo`/`light-em-up`) can turn
on.

## 5. RTKit state machine, for the record

`apple_rtkit_boot()` (mainline) and m1n1's `rtkit_boot()` are the same
sequence; only the timeouts differ:

1. AP → `MGMT_SET_IOP_PWR_STATE(INIT = 0x220)`
2. IOP → `MGMT_HELLO` (min/max version; the PMP offers 12)
3. AP → `MGMT_HELLO_REPLY`
4. IOP → `MGMT_EPMAP`, AP → `MGMT_EPMAP_REPLY` (repeat until the LAST bit)
5. IOP → `MGMT_SET_IOP_PWR_STATE_ACK(ON = 0x20)` ← **boot #8 died here**
6. AP → `MGMT_SET_AP_PWR_STATE(ON)`, IOP → `MGMT_SET_AP_PWR_STATE_ACK`

mainline gives steps 4 and 5 **1000 ms each** and never reaches step 6 if
they expire; m1n1 waits for step 5 **without any timeout**.  The PMP
validates step 6's payload (`Invalid AP power: %d` is in the firmware), so an
AP that aborted at step 5 leaves the PMP without its "AP is on" declaration.
