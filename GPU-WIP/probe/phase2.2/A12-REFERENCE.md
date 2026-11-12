# The A12 reference: BadApple / Project Cascadia

`github.com/dr1408/Project-Cascadia` (branch `a12-xr`) carries a working
Linux AGX driver for the A12 (T8020, "G11P"): `devices/a12/linux/patches/
linux-0020-agx.patch` (a full `drivers/gpu/drm/agx/`), plus
`devices/a12/GPU.md` and the m1n1 "GPU handoff" patch
`devices/a12/m1n1/ipad8/0011-j171-gpu-handoff.patch`.

It is **not** the A11's ABI, but it is the closest thing to a reference for
"how does an AGX GPU get started from Linux".

## What it confirms

| item | A12 (Cascadia) | A11 (us) |
|---|---|---|
| RTKit endpoints | `EP_MSGS 0x20`, `EP_INTS 0x21` | 0x20 / 0x21 ✓ |
| init message | `MSG_INIT (0x81ULL << 48)` | 0x81 << 48 ✓ |
| doorbell | `MSG_DOORBELL (0x83ULL << 48) \| channel` | — |
| mem-desc entry | `{u64 va, u32 pa >> 12, u32 0, u16 16K pages, u16 flags}` | the KB's finding ✓ |
| boot order | RTKit boot → endpoints → InitData → wait for ACK | ✓ |

## What is different (and what it tells us)

* **The firmware is not copied by the driver.**  On the A12 the bootloader
  loads the GFX firmware; m1n1 only *reserves* the segments it finds in the
  live ADT (`segment-ranges` on `/arm-io/gfx-asc`) and republishes them to
  Linux as `apple,segment-ranges`.  The driver then tells the GPU where the
  firmware is.  We currently copy the image ourselves into a DMA buffer and
  point the window at it — worth revisiting.
* **The init block is a different ABI.**  The A12's InitData is built from
  `FUN_00025954` with region B/C pointers at `init + 3*8` / `init + 4*8`, an
  MMU format at `init + 0x30`, and the descriptor table at `init + 0x13*8`.
  The A11's page is 0x98 bytes with X/T at +0x18/+0x1c (our `G10P-LAYOUT.md`),
  so the A12's offsets cannot be copied across.
* **The aperture sizes match ours**: the A12's hwdata B maps the fender and
  the sgx core as two 0x20000 windows, exactly like the A11's `gfx-kf`
  (`0x4d20000` and `0x4d00000`, both 0x20000).
* The A12's GFX mailbox is an **ASC** mailbox (`/arm-io/gfx-asc`), not an
  A7IOP one — the A11's is an A7IOP-style mailbox (the `AppleA7IOPV4GFX`
  class), so the ASC register layout does not apply to us either.

## Files worth mining

* `devices/a12/linux/patches/linux-0020-agx.patch` — `agx_fw.c` (firmware
  boot, init block, the compute queue), `agx_drv.c` (probe, the sgx/fender
  resources, the ASC mailbox), `agx-21b91-layout.c` (the init serializers).
* `devices/a12/m1n1/ipad8/0011-j171-gpu-handoff.patch` — how the firmware
  segments are reserved and handed over.
* `devices/a13/tools/gpu/` — `pmgr-dump.py`, `pmgr-regions.txt`,
  `pmp-devtable.py`, `volman-codes.py`: the PMGR/PMP tooling.
