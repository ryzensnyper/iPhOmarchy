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
| `0x0000..0x00ff` | all zero except `0x0018` | the identity register is the only live word in the first 256 bytes |

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

The **mailbox** page at IOP `+0x1000` reads zero and ignores writes, while
the rest of the window is alive — an unclocked page.  Apple's `AppleA7IOP`
kext says the mailbox registers are `MAILBOX_SET +0x1000`, `MAILBOX_CLR
+0x1004`, `INBOX_CTRL +0x1008`, TX `+0x1010`, `OUTBOX_CTRL +0x1020`, RX
`+0x1038`, and that it enables them by writing `0x1111` to `MAILBOX_SET`.
None of that works here, and the PMP gate message
(`(cmd << 20) | (dev << 12) | (gate id)`, command 1 = clock gate) draws no
reply and no effect.
