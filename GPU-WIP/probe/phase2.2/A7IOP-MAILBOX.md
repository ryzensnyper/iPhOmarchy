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
