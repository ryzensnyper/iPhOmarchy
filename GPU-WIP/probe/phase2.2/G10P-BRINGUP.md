# The A11 (G10P) GFX bring-up, as Apple's own kext does it

All of this is from the `AppleA7IOP` kext in the D21 kernelcache, as recorded
in the knowledge base (`A11-GPU-FINDINGS.md` §9f, "Mailbox & init registers on
G10P"), plus what the hardware has told us (`GPU-WIP/probe/STATUS.md`).

## The window layout we measured

The `gfx-kf` node owns **two** 128 KiB windows, and Apple's kext puts
different blocks in each:

| block | window | offset | our address | observed |
|---|---|---|---|---|
| mailbox | `0x4d00000` | `+0x4000` | `0x204d04000` | live (`MAILBOX_SET 0x01001000`, `INBOX_CTRL 0x00010704`) |
| run bit | `0x4d00000` | `+0x2048` | `0x204d02048` | latches our write |
| timebase | `0x4d20000` | `+0x80c`, `+0x810`, `+0x818` | `0x204d2800c/10/18` | `+0x80c = 0x60000003` (bit 1 set) |
| config registers | `0x4d20000` | `+0x8130` (0x100 words) | `0x204d28130` | live (page-group masks) |
| DART | `0x4d20000` | `+0x8000` | `0x204d28000` | live (`0x4f`, `0x60000003`, …) |

(The knowledge base writes the mailbox offset as "IOP+0x4000"; the hardware
puts it in the `0x4d00000` window, and the timebase/config/DART offsets in the
`0x4d20000` window.  Both are what the measurements above show.)

## The sequence, in Apple's order

From the kext's `AppleA7IOPV2GFX::initialize()` path:

| # | action | kext site |
|---|---|---|
| 1 | **mask** all four mailbox IRQs: write `0x1111` to `MAILBOX_SET` (`+0x4000`, and the mirror pair `+0xc00`) | `0x756530` |
| 2 | **unmask** the A2I-empty interrupt: write `1` to `MAILBOX_CLR` (`+0x4004`, mirror `+0xc04`) | `0x756548` |
| 3 | on a mailbox error (both status bits set) write `0x1000` to the CLR pair | `0x7565a4` |
| 4 | **outbox enable**: `OUTBOX_CTRL (+0x4020) \|= 1` | `0x7565d8` |
| 5 | **timebase sync**: `+0x80c &= ~2`; read CNTVCT; copy 1 → `+0x810`/`+0x818`; copy 2 → `+0xc030`/`+0xc038`; `+0x80c \|= 2` | `0x755dc4`, `0x756850` |
| 6 | **GFX run**: `+0x2048 \|= 1` (read-modify-write of bit 0) | `0x756cfc`, `0x75b004` |
| 7 | **GFX config restore**: write 0x100 words at `+0x8130+`, then zero a 64-byte scratch and set `[this+0x195] = 1` | `0x75944c` |
| 8 | GFX-specific bit: `+0x4044 &= ~0x10`, then `\|= (arg ? 0x10 : 0)` | `0x7567c8` |

The mirror pair at `+0xc00` is "initialised by iOS but not used by Linux" — do
not touch it.

## What the firmware does next

* The RTBuddy firmware boots and **starts the RTKit conversation itself**
  (HELLO → EPMAP → the endpoint map), exactly like the PMP does.
* The host then starts the two AGX endpoints: `0x20` (`APPLE_EP_AGX_INIT`) and
  `0x21` (`APPLE_EP_AGX_DOORBELL`).
* The firmware then waits for the **init message**: type `0x81` in the high
  word's bits 23:16, the physical address of the init page in the low word —
  `APPLE_MSG_INIT | (win_dma + 0x98000)`, sent on endpoint `0x20`.  The
  firmware copies exactly `0x98` bytes from it.
* The init page (built by the tree's `pvr_apple_layout_build()`):

  | offset | content |
  |---|---|
  | `+0x18` | `fw_va(HEAP_X)` — the main context |
  | `+0x1c` | `fw_va(HEAP_T)` — the firmware context |
  | `+0x20` | `fw_va(HEAP_MAP_CTRL)` — the mapping-update ring |
  | `+0x8c` | the physical address of the descriptor page (`win_pa + 0x9c000`) |
  | `+0x94` | the descriptor count (1) |

* The firmware answers by writing a "ready" flag (the tree polls
  `heap + 0x14188`).

## Why the firmware did not start (boots #26…#33)

The sequence above was **never executed**.  Our diagnostic driver did the
window copy and the run bit, but not:

* the mailbox mask/unmask and the outbox enable,
* the **timebase sync** — an RTKit coprocessor cannot start without the host
  giving it the timebase,
* the config-register restore.

and, more fundamentally, it asked for the endpoint map
(`apple_rtkit_boot()`) *before* the firmware could answer it, because the
firmware never started in the first place.

Boot #34 runs the sequence above verbatim.
