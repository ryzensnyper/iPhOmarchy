# G10P register map (what the A11 GPU answers today)

Everything here was read from hardware on the iPhone 8 Plus (D21, A11) with
the Phase 2.2 diagnostic driver.  Addresses are the AP aliases (ADT address +
`0x200000000`).

## The two gfx-kf windows (ADT `/arm-io/gfx-kf`)

| window | AP address | size | contents |
|---|---|---|---|
| IOP block | `0x204d20000` | `0x20000` | firmware window registers, DART block, mailbox page at `+0x1000` |
| Fender block | `0x204d00000` | `0x20000` | power state, firmware window registers, device-info block at `+0x4000` |

The ADT gives `gfx-kf` `reg = <0x4d20000 0x20000>, <0x4d00000 0x20000>`, the
mailbox IRQs `260, 259, 262, 261`, `power-gates = 0x95` (device 149) and
`clock-ids = 269`.

## RGX (the GPU core) — `0x204000000`

| offset | value | meaning |
|---|---|---|
| `0x0018` | `0x000007e1` | `ROGUE_CR_CORE_ID` = `{ID=0x0000, CONFIG=0x07e1}` → `n=0x07`, `c=0xe1` under the Rogue encoding |
| `0x0020` | `0x0` | `CORE_REVISION` / `CORE_ID__PBVNC` — not implemented on this core |
| `0x0000..0x0fff` | all zero except `0x0018` | **the whole first 4 KiB of the core window is sparse**: `CORE_ID` is the only live word |

So the A11 core does not implement the Rogue cluster/tile registers in its
core window: the cluster count and the geometry come from the
device-information block below (or from the firmware), not from the core.

## Device information — Fender block `0x204d04000`

| offset | value | note |
|---|---|---|
| `+0x00` | `0x01001000` | read-only (an enable write does not change it) |
| `+0x04` | `0x0` | |
| `+0x08` | `0x00010704` | shape of Apple's `INBOX_CTRL`: status bit 16 set, count field `0x07` |
| `+0x10` | `0x00090303` | bytes (9, 3, 3) |
| `+0x14` | `0x00020202` | bytes (2, 2, 2) |
| `+0x18` | `0x00000080` | |
| `+0x48` | `0x0000000f` | `15` |
| `+0x4c` | `0x0000002f` | `47` |
| `+0x60` | `0x00000002` | |
| `+0x80` | `0x00000028` | `40` — the A10's `phys_bus_width` |
| `+0x84` | `0x00000040` | `64` |
| `+0x88` | `0x00000028` | `40` — the A10's `virtual_address_space_bits` |
| `+0x8c` | `0x00000028` | `40` |

Reading `0x28` (= 40) in two places where the A10 driver hardcodes 40 says
this block is the **G10P device-information register set**, i.e. exactly what
`pvr_apple_device_info_init()` currently guesses for the A10
(`num_clusters = 6`, `phys_bus_width = 40`, `virtual_address_space_bits = 40`,
`tile_size_x/y = 32`, ISP samples `{1,5,7}`).  The A11's values have to be
taken from here.

`0x204d040c0` and beyond is a **hole**: reading it stalls the SoC, so the
block must not be scanned past `+0x40bf`.

## DART (the GPU's IOMMU) — IOP block `0x204d28000`

Found through the kext, whose code around these offsets references
`base + dart_vm_size`.

| offset | value | meaning |
|---|---|---|
| `+0x8000` | `0x0000004f` | the DART VM size register (`dart_vm_size`) |
| `+0x8108` | `0x00020001` | DART base configuration |
| `+0x810c` | `0x00100101` | DART base configuration |
| `+0x8130..` | per-group masks | see below |

The masks are the DART page tables: 64-byte groups, each group ending with a
configuration word — `0x00020000` for the groups at `+0x8130..+0x81b0` and
`0x00100100` for the groups at `+0x81b0..`.  The mask words are mostly ones
with holes, i.e. "valid" bits with invalid entries cleared:

```
+0x8130: f7bf7fff fd3fedff fffbffef 00020000
+0x8140: fdff7f7b eff7ff67 bedfffe1 00020000
+0x8150: ffffffff e6bcb7ff df7fdbfe 00020000
+0x8160: fe39fe7e 66fbf7bf bbeedfff 00020000
+0x8170: 1bfffbf4 ffdfffff 229dbff5 00020000
+0x8180: 7efffecd fffef7f5 0addffff 00020000
+0x8190: fffeffff fefffbff beffdff7 00020000
+0x81a0: afcafdbd fe133dff fd3ffff7 00020000
+0x81b0: 000c000c 00100000 00000000 00100100
+0x81c0: 9fff66df f7ffdfff fd7fff1f 00100100
+0x81d0: 9bfb35b7 ffff7eee fff07bdf 00100100
+0x81e0: ffb2fabf fffdfc3e ff5fffdd 00100100
+0x81f0: f7fedfdd 77fffd9f fd3dfeee 00100100
```

This is what the DRM driver needs to build the GPU's page tables.

## IOP block, the rest of the live registers

| offset | value |
|---|---|
| `+0x00` | `0x00000101` |
| `+0x08` | `0x0e100000` (the firmware window base we write) |
| `+0x10` | `0x00000008` (window base upper) |
| `+0x24` | `0x00100000` (window size) |
| `+0x38` | `0x00000001` (window enable) |
| `+0x40` | `0x000f0401` |
| `+0x48` | `0x0000004f` |
| `+0x800` | `0x00000060` |
| `+0x804` | `0x00180018` |
| `+0x80c` | `0x60000003` |

## Fender block, the rest of the live registers

| offset | value |
|---|---|
| `+0x1000` | `0x00000001` (the power state we request) |
| `+0x1010` | `0x0` (the power *ack* never sets on the A11) |
| `+0x1014` | `0x00000002` |
| `+0x200c` | `0x0e100000` (firmware window base) |
| `+0x2010` | `0x00000008` |
| `+0x201c` | `0x00100000` (window size) |
| `+0x2048` | `0x00000001` (run bit) |

## Still open

The **mailbox** is still not found (2026-11-12, after boot #49).  What is
now known:

* `0x204d04000` is the **read-only G10P device-information page** — not a
  mailbox.  It answers reads and ignores writes, except that `+0x80` took a
  write in boot #44.  The values are real: `+0x80 = 40` is the A10's
  `phys_bus_width`, `+0x84 = 64`, `+0x88 = 40` its
  `virtual_address_space_bits`.
* `0x204d24000` (the AppleA7IOP kext's "IOP + 0x4000") is a **dead page**:
  it reads zero and ignores every write.
* The **Fender window** holds only that device-info page and a lone
  `+0x54 = 0x6`; `fender+0x10044` **hangs the SoC**.
* The **IOP window** holds the firmware window registers, the DART
  (`+0x8000`), a chip-ID block at `+0x10000` and nothing else.
* The **core window** (`0x204000000`) only answers at `+0x18` (CORE_ID) and
  `+0x20`; `+0x00` traps the SoC.

So the mailbox is either dormant (its status registers read zero until the
host enables it, which is why every read-only sweep was empty) or it lives
in a part of the address space we cannot read safely.

## The PMGR banks (boot #48/#49)

| bank | contents |
|---|---|
| `pmgr0 + 0x80300` | the power-state bank, 8-byte stride: the GFX is psidx 7 = `0x80338` = our `ps_gfx`, decoded `clk 1, pwr 1, actual 0xf, target 0xf` |
| `pmgr1 + 0x80000` | 33 entries up to `+0x140`; **not** indexed by device id (nothing at 123/148/149 × 8) |
| `pmgr0 + 0x70000` | the **DVFS/voltage table** (0x4605 = 17925 µV, ten idle entries) |
| `pmgr0 + 0xa0000` | also a DVFS table (0xbb8ffc05 …) |

The A12's guide puts the GPU's *rail register* at PMGR + 0xa0000 and its
DVFS table at PMGR + 0x70000 — on the A11 those two offsets are swapped or
the rail register lives elsewhere entirely.  The GPU's core is alive
(CORE_ID ✓) while the **GFX-KF** — which owns the mailbox IRQs — is not,
and it is a `no_ps` device, so its gate is a plain gate register we have
not found yet.

## The G10P mailbox (from Apple's own kext, 2026-11-12)

The A11's GFX IOP is driven by `AppleA7IOPV4GFX`, and **its mailbox is not at
the M3Wrap offsets** (`+0x08`/`+0x48`/`+0x50`/`+0x80`) that boots #34/#35 and
#43/#44 used.  AppleA7IOPV4GFX overrides `getMailboxBulk` and uses:

| offset | register | address on the A11 |
|---|---|---|
| **+0x110** | **CPU_CTRL** (bit 0 = enabled, bit 16 = TX full, bit 17 = RX empty) | **0x204d00110** |
| **+0x114** | **CPU_CTRL status** (0xc0000 = invalid) | **0x204d00114** |
| **+0x800** | **TX data**, 16-byte words | **0x204d00800** |
| **+0x830** | **RX data**, 16-byte words | **0x204d00830** |

The AGX register block is the **Fender window (0x204d00000)**: the kext reads
the device-information page at +0x4008/+0x4020/+0x4040 (we measured that page
at 0x204d04000) and the power state at +0x1008/+0x1020 (we measured it at
0x204d01000).

**+0x110 was never read in any of the 19 boots**, so "the mailbox is dead" was
never actually established.  See `A7IOP-MAILBOX.md` for the full derivation
and `GPU-WIP/tools/a7iop-v4-gfx.py` to reproduce it.

Boots #50–#58 then read it properly: **it is zero, and Apple's enable write
(a read-modify-write of bit 0 of +0x114) does not stick** — the Kingfisher
is dark, and only the PMP can ungate it.

## The AGX apertures, restated

| window | AP address | size | contents |
|---|---|---|---|
| core (RGX) | `0x204000000` | 1 MiB | CORE_ID at +0x18 only; +0x00 traps |
| gfx-kf region A ("IOP") | `0x204d20000` | 128 KiB | window regs, DART +0x8000, timebase +0x80c, config +0x8130, chip ID +0x10000 |
| gfx-kf region B ("Fender") | `0x204d00000` | 128 KiB | power state +0x1000, window regs +0x200c, run bit +0x2048, device info +0x4000, +0x54 = 6; +0x10044 traps |
