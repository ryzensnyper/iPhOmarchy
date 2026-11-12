# Session handoff — A11 (G10P) GPU bring-up

*Written 2026-11-12, after boot #35, immediately before a session compaction.
Everything below is already committed; nothing is only in the conversation.*

## Where we are

Phase 2.2's stated goal — **Fender power + RGX identity** — is **met**:

| item | value | since |
|---|---|---|
| RGX identity | `CORE_ID (0x0018) = 0x7E1` → `{ID=0x0000, CONFIG=0x07E1}`, `n=7`, `c=0xE1` | boot #15, reproduced ever since |
| Fender power | `state 1 -> 0x1` in 10 ms (the ack bit is *not* the A10's bit 4) | boot #15 |
| window copy | Fender `+0x200c` and IOP `+0x08` read back | boot #15 |
| IOP release | run bit latches (`+0x2048`) | boot #15 |
| device information | `0x204d04000` — bus width `0x28` = 40, geometry bytes (9,3,3) / (2,2,2) | boot #18 |
| DART / IOMMU | `0x204d28000` — `dart_vm_size = 0x4f`, base `0x00020001`/`0x00100101`, page-group masks | boot #21 |
| firmware image | 381728 bytes = 0x5d320 (the KB's `gfx-t8015-const.bin[9:9+0x5d320]`) | boot #28 |
| PMP gate message | `(cmd << 20) \| (dev << 12) \| (gate id)`, cmd 1 = clock gate | boot #24 |
| architecture | **AGX** (`AGXG10P`, `AGXFirmwareKextG10PRTBuddy`); the A11's Fender is "Kingfisher" | boot #26 |

**The one thing still missing: the RTBuddy (GFX IOP) firmware does not start.**
It never sends its RTKit HELLO, so `apple_rtkit_boot()` times out (-62), the AGX
endpoints cannot be started (-22), and the init message cannot be sent (-22).

## The blocker, precisely

The **GFX mailbox** is the channel to that firmware.  We found it: it is at
**`0x204d04000`** — the `0x4d00000` window + `0x4000` — because the live
registers there carry exactly the mailbox's names and semantics
(`MAILBOX_SET 0x01001000`, `MAILBOX_CLR 0x0`, `INBOX_CTRL 0x00010704`,
`OUTBOX_CTRL 0x0`).

* Our DT had it at `0x204d24000` — **a hole**: it reads zero and ignores
  writes.  Fixed: `t8015.dtsi` → `gpu_mbox: mbox@204d04000`.
* The in-tree `apple_mbox_a7iop_hw` map already matches that block exactly.
* **Boot #35's new finding: the block at `0x204d04000` ignores our writes.**
  `MAILBOX_SET` still reads `0x01001000` after `0x1111` was written, `MAILBOX_CLR`
  still `0` after `1`, `OUTBOX_CTRL` still `0` after `|= 1`.  The timebase
  registers in the *other* window (`0x204d28010`/`0x204d28018`) **do** take
  writes, so the mapping and the window are right.

So either `0x204d04000` is a read-only status block that only looks like the
mailbox, or the mailbox's writable registers live elsewhere in the `0x4d00000`
window.

## The bring-up we now run (boots #34/#35)

From the `AppleA7IOP` kext's `AppleA7IOPV2GFX::initialize()`, in Apple's order
(full spec: `GPU-WIP/probe/phase2.2/G10P-BRINGUP.md`):

| # | step | our address |
|---|---|---|
| 1 | mask all four mailbox IRQs: `0x1111` → `MAILBOX_SET` | `0x204d04000` |
| 2 | unmask the A2I-empty interrupt: `1` → `MAILBOX_CLR` | `0x204d04004` |
| 3 | outbox enable: `OUTBOX_CTRL \|= 1` | `0x204d04020` |
| 4 | **timebase sync**: `+0x80c &= ~2`, CNTVCT → `+0x810`/`+0x818` (and `+0xc030`/`+0xc038`), `+0x80c \|= 2` | `0x204d2800c/10/18` |
| 5 | window copy, release the IOP: `+0x2048 \|= 1` | `0x204d02048` |
| 6 | `apple_rtkit_boot()`, `start_ep(0x20)`, `start_ep(0x21)` | mailbox |
| 7 | init message `0x81 << 48 \| (win_dma + 0x98000)` on ep 0x20; init data built by `pvr_apple_layout_build()` | window |
| 8 | config restore: write 0x100 words at `+0x8130` | `0x204d28130` |

## The mailbox livelock (fixed)

`drivers/soc/apple/mailbox.c` polled

```c
while (!(mbox_ctrl & mbox->hw->control_empty)) { ... }
```

forever, because the A11 mailbox reports *neither* empty nor full (the invalid
state Apple's kext asserts on) — the handler spun in IRQ context, the kernel
starved and the phone rebooted (boots #29/#30).  Fixed: the poll is bounded,
and the receive interrupt is masked **at the interrupt controller** while the
state is invalid (the mailbox's own mask register does not work on this block)
and unmasked again once it becomes valid.  The enable/disable is paired through
`recv_irq_masked` (an earlier version produced an `__enable_irq` imbalance
flood).

## Next steps

1. **Find the mailbox's writable registers.**  Sweep the `0x4d00000` window for
   registers that change when written; re-read `0x204d04000` after writing
   elsewhere to confirm whether it is read-only status.  (The kext's
   `AppleA7IOP` offsets are `+0x4000` SET/CLR, `+0x4008` INBOX_CTRL,
   `+0x4020` OUTBOX_CTRL, `+0x4038` RX, `+0x4040` IDLE_STATUS, `+0x4044` the
   GFX bit — and the mirror pair at `+0xc00`.)
2. **The config restore**: the kext *writes* 0x100 words at `+0x8130`
   (`0x204d28130`); we only read them.
3. **The AGX config RAM**: `AGXFender::writeConfigRAMCommand32(uint16_t, uint32_t,
   uint8_t)` — the A11 may not start the GPU with a run bit at all.  The code is
   in the KB's `AGXG10P__TEXT_EXEC.bin` (404 KiB of arm64 code) plus
   `agxg10p.asm` and `tools/g10p-*`.
4. **`0x204d04000` revisited**: the values fit the mailbox names suspiciously
   well, so if (1) fails, test whether the *kext's* window base is
   `0x4d00000` vs `0x4d20000` for those blocks (the KB says "IOP+0x4000" but
   our hardware puts the block in the `0x4d00000` window, while the timebase
   and the config registers are in `0x4d20000`).

## How to build and boot

```sh
# build (the phone must be in PongoOS: 05ac:4141)
cd /home/doug/orchard
./bin/orchard build /home/doug/omarchy-iphone/d21-desktop-boot --device d21 \
  --kernel-tree /home/doug/projects/OrchardLinux/trees/d21-touchgood \
  --pongo "/home/doug/Known Good State/loaders/Pongo.bin"

# boot the built payload
./bin/orchard run /home/doug/omarchy-iphone/d21-desktop-boot --device d21 \
  --no-build -y
```

* The kernel tree is a git repo on branch **`gpu/phase2.2`**; the driver work is
  committed as **`3af7971b5f1a`**.
* The last built payload: **`e13d0199af67daa7f0ee339efc54bf2fc9d116172855bc706e835f9602658f2e`**
  (boot #35 — the bring-up + the livelock fix).
* The kernel log is streamed to `/tmp/opencode/phone-kmsg.log` by
  `GPU-WIP/tools/kmsg-host.py` (pid 412793; do **not** kill it).  Boot #N starts
  at the `GFX-STAGE 0/12` line.
* A boot counts only when the phone re-enumerates as `05ac:4144`; `RUN_EXIT=0`
  proves nothing (the upload can fail with `LIBUSB_ERROR_OTHER` and still exit
  0 — check `orchard devices` and the log, not the exit code).
* One boot per explicit go; the phone must be in PongoOS first (after a boot
  it is in iOS and has to be restarted by hand).

## The kernel tree's own driver

`drivers/gpu/drm/imagination/pvr_apple.c` + `pvr_apple_layout.c` are the
project's **A11/G10P** driver (not the A10's): they already know the bring-up
(`pvr_apple_fw_start()` sends `APPLE_MSG_INIT | (win_dma + 0x98000)` on
`APPLE_EP_AGX_INIT` = 0x20 and waits for the firmware's ready flag at
`heap + 0x14188`), the window layout (`WIN_INIT 0x98000`, `WIN_DESC 0x9c000`),
and the init-page fields.  Our diagnostic driver
(`drivers/soc/apple/apple-t8015-gfx.c`) is the Phase 2.2 instrument; it now
compiles `pvr_apple_layout.c` into itself (the DRM stack is a module, so its
symbols are not linkable from a built-in driver).

## Where the knowledge is

| what | where |
|---|---|
| the boot log of every attempt | `GPU-WIP/probe/STATUS.md` (chronological, with verdicts) |
| the A11 register map we measured | `GPU-WIP/probe/phase2.2/G10P-REGISTERS.md` |
| the GFX bring-up spec | `GPU-WIP/probe/phase2.2/G10P-BRINGUP.md` |
| the mailbox map from Apple's kext | `GPU-WIP/probe/phase2.2/A7IOP-MAILBOX.md` |
| tools | `GPU-WIP/tools/` — `kmsg-host.py`, `a7iop-mailbox-re.py` (the mailbox map extractor), `pmp-fw-dis.py` (Thumb-2 PMP firmware via capstone) |
| the project's own earlier RE (huge) | `Known Good State/firmware/GPU/` — `A11-GPU-FINDINGS.md`, `A11-GPU-G10P-LAYOUT.md`, `A11-GPU-G10P-BOOTCHAIN.md`, `A11-GPU-G10P-STAGE2.md`, the extracted `AGXG10P__*.bin` segments, `agxg10p.asm`, `tools/` |
| host-side helpers | `/tmp/opencode/` — `kcdis.py` (arm64 in the kernelcache), `xref.py`, `pmp-dis.py`, `d21ap-kernelcache.macho` |
