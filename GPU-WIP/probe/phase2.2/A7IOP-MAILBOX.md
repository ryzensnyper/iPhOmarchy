# The AppleA7IOP mailbox (G10P GPU IOP) — register map from Apple's own kext

Source: the iOS **D21 (A11) kernelcache** (`/tmp/opencode/d21ap-kernelcache.macho`),
kext **`AppleA7IOP`**.  Nothing here is guessed: every offset and value was read
out of the binary with `GPU-WIP/tools/a7iop-mailbox-re.py`.

* kext code: `__PLK_TEXT_EXEC`, cluster `0xfffffff005754000..0xfffffff005759000`
* kext strings: `__PRELINK_TEXT` around `0xfffffff004e21000..0xfffffff004e28000`
* log format string: `0xfffffff004e22136`, referenced from `0xfffffff005755a74`

## Register map

All offsets are relative to the mailbox window base.

| offset | name (Apple's log label) | how it is used |
|---|---|---|
| `+0x1000` | `MAILBOX_SET` | write-1-to-set mask; the enable write is `0x1111` |
| `+0x1004` | `MAILBOX_CLR` | write-1-to-clear mask |
| `+0x1008` | `INBOX_CTRL` | status in bits 16..18 (`ubfx #17`, `ubfx #16`) |
| `+0x1010` | TX data | 64-bit message written by the AP (`str x8, [x9, #0x1010]`) |
| `+0x1020` | `OUTBOX_CTRL` | bit 0 is set by the AP to start the outbox |
| `+0x1038` | RX data | 64-bit message read by the AP (`ldr x8, [x8, #0x1038]`) |
| `+0x0028` | `CPU_CTRL` | bit 4 is set/cleared by the AP |
| `+0x000c`, `+0x0020`, `+0x0030`, `+0x0038`, `+0x0b88` | — | low registers of the same block |

The whole mailbox register set therefore fits inside **one 64-byte block** at
`base+0x1000` (`+0x1000 .. +0x103f`).

## Enable sequence (from the kext's own helpers)

| helper | action |
|---|---|
| `0xfffffff005755788` | write **`0x1111`** to `MAILBOX_SET (+0x1000)` |
| `0xfffffff005755798` | write **`1`** to `MAILBOX_SET` or `MAILBOX_CLR` (selected by `csel` on the argument) |
| `0xfffffff0057557e4` | write **`0x1000`** to `MAILBOX_SET` or `MAILBOX_CLR` |
| `0xfffffff005755804` | set **bit 0** of `OUTBOX_CTRL (+0x1020)` |
| `0xfffffff005755734` | read `INBOX_CTRL`, return bit 17 only if bits 17:16 are clear |

## Device-tree properties and boot-args the kext expects

| name | kind |
|---|---|
| `pc-sample-offset` | DT property |
| `ps-reg-offset` | DT property (the mailbox's own power-state register offset) |
| `debug-ps-clock-gate` | DT property |
| `ignore-gating` | boot-arg |
| `force-timebase-sync` | boot-arg (also present as a property on `gfx-kf`) |
| `post-retry-freq` | boot-arg |
| `a7iop_enable_timeout` | boot-arg |
| `ignore-mailboxes` | boot-arg |

`ps-reg-offset` is why the mailbox has a *power* gate of its own: the kext
waits for a power-state register before it talks to the mailbox.  The A11's
values for these are **not** in the ADT (they live in the iBoot device tree),
so they have to be found by probing.

## What the ADT says about the A11 GFX IOP

`/arm-io/gfx-kf` (`compatible = "iop-gfx,t8015"`, `role = "GFX"`):

| property | value |
|---|---|
| `reg` | `0x4d20000` size `0x20000`, `0x4d00000` size `0x20000` |
| `interrupts` | `260, 259, 262, 261` — the four mailbox IRQs |
| `clock-ids` | `269` |
| `power-gates` / `clock-gates` | `0x95` (device 149) |
| `force-timebase-sync` | present |

So the mailbox is **not** a separate device window on the A11: it lives inside
the two 128 KiB `gfx-kf` windows (the IOP block `0x4d20000` and the Fender
block `0x4d00000`), and `gfx-kf` is the node that owns the mailbox IRQs.

## Consequence for the Linux driver

The tree's `apple_mbox_a7iop_hw` map is

```
a2i_control 0x08   a2i_send 0x10   i2a_control 0x20   i2a_recv 0x38
```

which is **exactly Apple's map minus `0x1000`**.  Two possibilities, and they
are the whole of boot #17:

1. the Linux map is right and Apple's kext maps the window 4 KiB lower
   (`base-0x1000`), or
2. the Linux map is off by `0x1000` and the real mailbox registers are at
   `base+0x1000` — in which case boot #16's probe of `0x204d24000+0x00..0x3c`
   read the wrong 64 bytes entirely, and the all-zero result means nothing.

Boot #15's Fender read-back proves that writes *do* stick in that region, so
"the block is dead" was never established — only "the offsets we used are not
the mailbox".

## Boot #17 — sweep instead of guess

Read every 64-byte chunk of both `gfx-kf` windows (`0x204d00000` and
`0x204d20000`, 128 KiB each), log the ones that are not zero, and then try
the `0x1111` enable write on every page that looks alive, re-reading the
64-byte block afterwards.  If the mailbox is where Apple's map says, the
64-byte block at `page+0x1000` shows SET/CLR/INBOX_CTRL/TX/OUTBOX_CTRL/RX and
the enable write changes it.

## Still open

* The A11 values of `ps-reg-offset` / `pc-sample-offset` (iBoot device tree,
  not the ADT) — needed if the mailbox turns out to need its own power gate.
* Whether the `0x1111` enable is a mailbox enable at all or a *power-state*
  write (the same set/clear pattern exists for the sensors:
  `sensor-offset-CTL0-set` / `sensor-offset-CTL0-clr`).

## The A11 uses a *different* class: AppleA7IOPV4GFX (2026-11-12)

Everything above was reverse-engineered from **`AppleA7IOPV2GFX`** — the
`AppleA7IOP` kext's class for `iop-gfx,s8000`, `iop-gfx,t8010` and
`iop-gfx,t8011`.  **The A11 (t8015) is not one of those.**  The kernelcache's
personality dictionary says:

```xml
<key>AppleA7IOPV2-GFX</key>
  <key>IOClass</key><string>AppleA7IOPV2GFX</string>
  <key>IONameMatch</key><array>
    <string>iop-gfx,s8000</string><string>iop-gfx,t8010</string>
    <string>iop-gfx,t8011</string></array>
<key>AppleA7IOPV4-GFX</key>
  <key>IOClass</key><string>AppleA7IOPV4GFX</string>
  <key>IONameMatch</key><array><string>iop-gfx,t8015</string></array>
<key>AppleA7IOPV4PMP</key>            <!-- iop-pmp,t8015 -->
```

So the A11's GFX IOP is driven by **`AppleA7IOPV4GFX`**, a different
implementation with a different mailbox.

### The V4 mailbox layout

`AppleM3WrapV2::getMailboxBulk()` (the class the V4 GFX derives from) reads
five registers through the vtable's `readRegister(offset)` call and logs them
as:

```
M3Wrap_CTRL: 0x%08x
M3Wrap_IntOutIRQEn: 0x%08x
M3Wrap_IntOutSts: 0x%08x
INBOX_CTRL: 0x%08x
OUTBOX_CTRL: 0x%08x
```

In the disassembly (`__PLK_TEXT_EXEC` 0xfffffff00575aab4) the five offsets it
passes to `readRegister()` are **0x08, 0x48, 0x4c, 0x50, 0x80**, and the
send/receive helpers copy 16 bytes at **+0x60** (TX) and **+0xa0** (RX) from
the mapped base (`[this + 0x100]`, the same member the V2 class used for the
IOP base).  So the V4 mailbox block is:

| offset | register |
|---|---|
| +0x08 | M3Wrap_CTRL |
| +0x48 | M3Wrap_IntOutIRQEn |
| +0x4c | M3Wrap_IntOutSts |
| +0x50 | INBOX_CTRL |
| +0x60 | TX (16 bytes) |
| +0x80 | OUTBOX_CTRL |
| +0xa0 | RX (16 bytes) |

The status bits are the same as in the V2 class: `INBOX_CTRL`/`OUTBOX_CTRL`
carry bit 16 (full) and bit 17 (empty), and Apple's code asserts that
`0xc0000` is never set (`_getInboxEmpty()` at 0xfffffff0057564dc does
`tst w0, #0xc0000` and calls the error path at 0x575cec8 when it is).

**Our bring-up was modelled on the wrong class.**  The `0x1111` mask write, the
`MAILBOX_CLR` unmask and the `OUTBOX_CTRL |= 1` of boots #34/#35 are the V2
sequence; the V4 class has `M3Wrap_IntOutIRQEn`/`M3Wrap_IntOutSts` instead of
the SET/CLR pair.

### Where the mailbox is on the A11

The ADT has **no separate mailbox node** for the GFX (unlike the A10, where
`mbox@201d24000` is its own node).  The mailbox interrupts 259-262 belong to
`/arm-io/gfx-kf`, whose two regions are `0x4d20000` (0x20000) and `0x4d00000`
(0x20000) — so the mailbox has to live inside one of them.

On this chip every *other* mailbox sits at **(node base + 0x8000)**:

| node | base | mailbox |
|---|---|---|
| pmp | 0x32300000 | 0x32308000 |
| smc | 0x36800000 | 0x36808000 |
| ans | 0x57000000 | 0x57008000 |

For the GFX that gives 0x4d28000 (which is the **DART**) or 0x4d08000
(boot #36: **all zeros**).  So the GFX does not follow that pattern, and boot
#36 found no mailbox in the pages it probed:

| base | boot #36 |
|---|---|
| 0x4d00000 | all zero except **+0x54 = 0x6** |
| 0x4d04000 | the read-only device-info page (SET 0x01001000, INBOX 0x00010704, +0x48 = 0x0f, +0x4c = 0x2f, +0x60 = 0x2, +0x80 = 0x28, +0x84 = 0x40) |
| 0x4d08000 | all zero |
| 0x4d20000 | window registers (+0x00 = 0x101, +0x38 = 1, +0x40 = 0x30000, +0x48 = 0x79) |
| 0x4d24000 | all zero |

Boot #37 therefore sweeps all 32 pages of both apertures at the fifteen
offsets of both layouts.

### What the ADT says about the GFX

`/arm-io/gfx-kf`: `power-gates = 149`, `clock-gates = 149`, `clock-ids = 269`,
`force-timebase-sync`, `iop-version = 1`, `role = GFX`.
`/arm-io/sgx`: `reg = 0x4000000 (0x100000), 0x4d00000 (0x20000)`,
`power-gates = 148, 123`, `clock-gates = 148, 123`, `has-kf = 1`, and
`meta-sw-interrupt` = `0x32104020 <- 2`, `0x321040a0 <- 2`, `0x8` — a
**software interrupt** to the GPU's "meta" processor, i.e. a way to wake the
coprocessor that does not involve the mailbox at all.

### Where the V4 class lives (for further RE)

| what | address |
|---|---|
| the `AppleA7IOPV4GFX` vtable | `__PLK_DATA_CONST` **0xfffffff006ccc660** |
| the metaclass constructor that stores it | `__PLK_TEXT_EXEC` 0xfffffff00575ad10 |
| the M3Wrap base class's vtable | `__PLK_DATA_CONST` 0xfffffff006ccb258 |
| `AppleM3WrapV2::getMailboxBulk()` (reads the five registers) | 0xfffffff00575aab4 |
| the send/receive helpers (base+0x60 / base+0xa0) | 0xfffffff00575aa0c / 0xfffffff00575a9f8 |

The class's two register maps (`_agxRegisterMap` + `_wrapRegisterMap`) are
the next thing to find: their data would give the *physical* offsets, and
`initialize()` would say which of the two apertures is the wrapper's.

---

# SOLVED: the AppleA7IOPV4GFX register map (2026-11-12, offline)

Reproduce with `GPU-WIP/tools/a7iop-v4-gfx.py` (offline, reads the D21
kernelcache only).  Everything below was read out of the binary; nothing is
guessed.

## The "register map" is not an offset table

This is the surprise, and it ends the guessing.  The class's register accessor
is two instructions (`__PLK_TEXT_EXEC`):

```
0xfffffff00575b100:  ldr  x8, [x0, #256]      ; the mapped register block
0xfffffff00575b104:  ldr  w0, [x8, w1, uxtw]   ; ... at the given byte offset
0xfffffff00575b108:  ret
```

(the same accessor exists for the base class at `0xfffffff00575bbc4`).  So the
"offset" that the kext passes around **is the physical offset inside the
mapped block** — there is no indirection table to look up.  `_agxRegisterMap`
(instance member **+0x170**) is a *descriptor* struct, not an offset table:
the kext only reads two fields of it (`+0x28` and `+0x44`).

The offsets reach the accessor through the metaclass dispatch slot at
`metaclass + 0x640` (selector 1600), i.e. `ldr x8,[x0]; ldr x8,[x8,#1600];
mov w1,#<offset>; blr x8`.

## The class hierarchy (from the kext's own REQUIRE strings)

```
AppleIOP
└── AppleA7IOP                  (_akfRegisterMap, _autoBootRegisterMap)
    └── AppleA7IOPV1            (_getInboxEmpty, _getOutboxEmpty, _mapFirmware)
        └── AppleA7IOPV2
            ├── AppleA7IOPV2GFX        (A10)
            ├── AppleA7IOPV2Marconi    (_wrapper/_inbox/_outbox/_aop maps)
            └── AppleA7IOPV2PMP        (_pmsCSRRegisterMap)
                └── AppleA7IOPV4
                    └── AppleA7IOPV4GFX    <-- the A11 (iop-gfx,t8015)
AppleMxWrap                        (_wrapRegisterMap, _wrapMappedRegs)
└── AppleM3WrapV2                 (getMailboxBulk at 0xfffffff00575aab4)
AppleASCWrapV2 / AppleASCWrapV4   (_coreRegisterMap)
AppleASCANS2                      (_ans2CpuMap)
```

Source files: `AppleA7IOPV4GFX.cpp`, `AppleMxWrap.cpp`, `AppleM3WrapV2.cpp`,
`AppleA7IOPV1.cpp` … all under
`/Library/Caches/com.apple.xbs/Sources/AppleA7IOP/`.

## The G10P mailbox: the V4 GFX class does NOT use the M3Wrap layout

`AppleA7IOPV4GFX` **overrides** `getMailboxBulk` (vtable slot +97, function
`0xfffffff00575ba0c`) and the send/receive helpers (slots +115/+116).  The
base `AppleM3WrapV2::getMailboxBulk` reads offsets 0x08/0x48/0x4c/0x50/0x80 —
but the GFX class replaces that with a completely different set:

| offset | register | evidence |
|---|---|---|
| **+0x110** | **CPU_CTRL** — the mailbox control register | read at 0x575b788, 0x575b974, 0x575b998, 0x575ba44 |
| **+0x114** | **CPU_CTRL status** | read at 0x575b744, 0x575b9c4 |
| **+0x800** | **TX data**, 16-byte words | written by `postMailbox`: 0x575b94c `add x10,x10,#2048; stp x8,x9,[x10]` |
| **+0x830** | **RX data**, 16-byte words | read by `getMailboxBulk`: 0x575b938 `add x8,x8,#2096; ldp x8,x9,[x8]` |

Status bits in CPU_CTRL (+0x110), from the GFX's own accessors:

| bit | meaning | code |
|---|---|---|
| 0 | "enabled" | 0x575b77c: `readReg(0x110) & 1` |
| 16 | TX full | 0x575b968: `ubfx w0,w0,#16,#1` |
| 17 | RX empty | 0x575b98c: `ubfx w0,w0,#17,#1` |

and `0xc0000` (bits 16|17 both set) is the "invalid" state the kext asserts
against (`_getInboxEmpty`).

## Which aperture is the AGX block?

Three independent correlations put the AGX register block at **the Fender
window, 0x204d00000**:

| what the kext reads | kext offset | what we measured on the phone |
|---|---|---|
| the device-information page | +0x4008, +0x4020, +0x4040 | `0x204d04000` — the read-only G10P device-info page |
| the power state | +0x1008, +0x1020 | `0x204d01000` — the Fender power-state register |
| the AGX info | +0xb88 | — |

So:

| what | address |
|---|---|
| **mailbox control** | **0x204d00110** |
| **mailbox status** | **0x204d00114** |
| **mailbox TX** | **0x204d00800** |
| **mailbox RX** | **0x204d00830** |

## What this means for boots #34/#35 and #43/#44

* The `0x1111` mask write, the `MAILBOX_CLR` unmask and `OUTBOX_CTRL |= 1`
  (boots #34/#35) were the **V2 class's** sequence — wrong registers.
* Boot #43/#44's "V4 enable sequence" wrote at **+0x08** (M3Wrap_CTRL) and
  **+0x48** (IntOutIRQEn) — those are the *M3Wrap base class*'s offsets.  The
  GFX class's control register is at **+0x110**, and +0x114 is its status.
* **+0x110 was never read in any of the 19 boots.**  Every "the mailbox is
  dead" conclusion so far was based on the wrong offsets (and on a dormant
  mailbox reading zero anyway).

## Still open after this

* The **write** side: which bits to write to CPU_CTRL (+0x110) to enable the
  mailbox and to unmask the RTKit interrupt.  The kext's write accessor was
  not isolated (the 32-bit stores use a different code shape than the reads).
* Whether the GFX class also needs an IRQ-enable register of its own (the
  M3Wrap base had +0x48/+0x4c; the GFX overrides `getMailboxBulk` but no
  +0x118/+0x11c access was seen).
