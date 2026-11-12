# Session handoff — A11 (G10P) GPU bring-up

*Rewritten 2026-11-12 after boot #49, immediately before a session compaction.
Everything below is committed and pushed; nothing important lives only in the
conversation.  The kernel tree is committed too.*

## 1. Where we are

Phase 2.2's stated goal — **Fender power + RGX identity** — is **met**:

| item | value | since |
|---|---|---|
| RGX identity | `CORE_ID (0x0018) = 0x7E1` → `{ID=0x0000, CONFIG=0x07E1}`, `n=0x07`, `c=0xE1` | boot #15, reproduced ever since |
| Fender power | the state register answers; the ack never sets | boot #15 |
| window copy | Fender `+0x200c` and IOP `+0x08` read back | boot #15 |
| IOP release | the run bit latches (`+0x2048`) | boot #15 |
| device information | `0x204d04000` — read-only; `+0x80 = 40` is the A10's `phys_bus_width` | boot #18, boot #40 |
| DART / IOMMU | `0x204d28000` — `dart_vm_size = 0x4f`, base `0x00020001`/`0x00100101`, page-group masks at `+0x8130` | boot #21 |
| firmware image | 381728 bytes = 0x5d320 (the KB's `gfx-t8015-const.bin[9:9+0x5d320]`) | boot #28 |
| PMP gate message | `(cmd << 20) \| (device << 12) \| (gate id)` — **both halves were wrong**, see §5 | boot #25, boot #46/47 |
| architecture | **AGX** (`AGXG10P`, `AGXFirmwareKextG10PRTBuddy`) | boot #26 |

**The one thing still missing: the RTBuddy (GFX IOP) firmware never starts.**
It never sends its RTKit HELLO, so `apple_rtkit_boot()` times out (-62), the
AGX endpoints cannot be started (-22), and the init message cannot be sent
(-22).  The channel that should carry the HELLO is the **GFX mailbox**.

**Since boot #49 that channel has been located** (offline, from Apple's own
kext — see §3): the G10P mailbox is at **+0x110** of the AGX register block,
which is the **Fender window at 0x204d00000** — so
**0x204d00110 (control), 0x204d00114 (status), 0x204d00800 (TX),
0x204d00830 (RX)**.  Boots #34/#35 and #43/#44 used the *M3Wrap base
class's* offsets (+0x08/+0x48/...), and **+0x110 was never read once in 19
boots**, so "the mailbox is dead" was never established.

**Boots #50 and #51 settled the location and then the cause:**

* boot #50: `+0x4008` reads `0x00010704`, the device-information page's
  third 32-bit field (the page is 8-byte stride) — so the **AGX register
  block is the Fender window** beyond doubt; the mailbox itself read zero.
* boot #51: the same read *after* the Fender power request, plus Apple's own
  enable sequence (a read-modify-write of **bit 0 of +0x114**) — still zero,
  and **the write did not stick**.  A register that ignores writes is a
  register whose domain is dark.

So the mailbox is in the right place and the block is powered; what is
missing is that the *mailbox's own* power/clock state was never raised.
Apple's kext reads **+0x1008 and +0x1020** from the AGX block and never
uses +0x1000 — and `AppleA7IOPV1` gets its mailbox power-state register
offset from the device-tree property **`ps-reg-offset`**.  Our driver has
been writing **+0x1000**, which merely echoes the value back.  **Boot #52
dumps the AGX block's pages 0 and 1 word by word and then tries +0x1008 and
+0x1020.**

## 2. The hardware map (measured, all AP addresses)

| what | address | notes |
|---|---|---|
| RGX core window | `0x204000000` (1 MiB) | the ADT's `sgx` node calls it 0x4000000; **CORE_ID is the only live word in the first 4 KiB** |
| gfx-kf region A ("IOP") | `0x204d20000` (128 KiB) | firmware window registers, DART at `+0x8000`, timebase at `+0x80c`, config at `+0x8130` |
| gfx-kf region B ("Fender") | `0x204d00000` (128 KiB) | power state `+0x1000`, window regs `+0x200c`, run bit `+0x2048`, device info `+0x4000` |
| the ADT's gfx-kf node | `reg = <0x4d20000 0x20000>, <0x4d00000 0x20000>` | the mailbox IRQs 259-262 belong here; `power-gates = 149`, `clock-gates = 149`, `force-timebase-sync` |
| the ADT's sgx node | `reg = <0x4000000 0x100000>, <0x4d00000 0x20000>` | `power-gates = 148, 123`; `has-kf = 1`; `meta-sw-interrupt = 0x32104020 <- 2, 0x321040a0 <- 2` |

**Traps — reading these hangs or resets the SoC (no panic, straight to DFU):**

* `0x204d040c0` and beyond (the hole past the device-info page),
* `0x204d10044` (in the Fender window's upper half),
* `0x204000000 + 0x00` (the RGX's first core register — only `+0x18` and `+0x20` are safe),
* the A7IOP shim aperture `0x2ee00000` (not reachable from the AP),
* `0x2ee04000`, `0x2ee08000` (never got to them).

## 3. The kext: the A11 uses a *different* class (the key find)

The kernelcache's personality dictionary binds the GFX IOP like this:

```xml
<key>AppleA7IOPV2-GFX</key>  IONameMatch: iop-gfx,{s8000,t8010,t8011}
<key>AppleA7IOPV4-GFX</key>  IONameMatch: iop-gfx,t8015      <-- the A11
```

So the A11 is **`AppleA7IOPV4GFX`**, derived from `AppleM3WrapV2` — not the V2
class our original bring-up spec was copied from.  **The V4 mailbox layout
(in the high word of the mapped registers):**

| offset | register |
|---|---|
| +0x08 | M3Wrap_CTRL |
| +0x48 | M3Wrap_IntOutIRQEn |
| +0x4c | M3Wrap_IntOutSts |
| +0x50 | INBOX_CTRL |
| +0x60 | TX (16 bytes) |
| +0x80 | OUTBOX_CTRL |
| +0xa0 | RX (16 bytes) |

There is **no SET/CLR pair**, so the `0x1111` mask, the `MAILBOX_CLR` unmask
and `OUTBOX_CTRL |= 1` of boots #34/#35 were writes to registers that do not
exist in this class.  (The status bits are the same as in the V2 class: bit
16 = full, bit 17 = empty, and `0xc0000` set means the invalid state.)

**Where the class lives:**

* the V4 GFX **vtable** is at `__PLK_DATA_CONST` **0xfffffff006ccc660** (found
  via the metaclass constructor at `0x575ad10`, which stores it); the M3Wrap
  base class's vtable extension is at `0xfffffff006ccb258`,
* the class asserts `_agxRegisterMap && _agxMappedRegs` (V4) and the base
  class has `_wrapRegisterMap`, `_wrapMappedRegs`, `_inboxRegisterMap`,
  `_inboxMappedRegs` — two maps means two apertures, and gfx-kf has two.

**SOLVED (2026-11-12, offline): the register map.**  Reproduce with
`GPU-WIP/tools/a7iop-v4-gfx.py`.

* The "register map" is **not** an offset table.  The accessor is two
  instructions — `0xfffffff00575b100`:
  `ldr x8,[x0,#256]` (`_agxMappedRegs`) / `ldr w0,[x8,w1,uxtw]` — so the
  offsets the kext passes around **are** the physical offsets in the mapped
  block.  `_agxRegisterMap` (member +0x170) is a descriptor struct, not a
  table.
* The class hierarchy, from the kext's own REQUIRE strings:
  `AppleIOP → AppleA7IOP → AppleA7IOPV1 → AppleA7IOPV2 → {V2GFX, V2Marconi,
  V2PMP} → AppleA7IOPV4 → AppleA7IOPV4GFX`, plus `AppleMxWrap →
  AppleM3WrapV2`, `AppleASCWrapV2/V4`, `AppleASCANS2`.
* **AppleA7IOPV4GFX overrides `getMailboxBulk`** (vtable slot +97,
  `0xfffffff00575ba0c`) and uses a *different* layout from the M3Wrap base:

  | offset | register | address on the A11 |
  |---|---|---|
  | **+0x110** | **CPU_CTRL** — bit 0 = enabled, 16 = TX full, 17 = RX empty | **0x204d00110** |
  | **+0x114** | **CPU_CTRL status** (0xc0000 = invalid) | **0x204d00114** |
  | **+0x800** | **TX data**, 16-byte words | **0x204d00800** |
  | **+0x830** | **RX data**, 16-byte words | **0x204d00830** |

* The AGX block is the **Fender window (0x204d00000)**: the kext reads the
  device-information page at +0x4008 and the power state at +0x1008 — exactly
  where we measured them.
* CPU_CTRL bit 16 = TX full, bit 17 = RX empty, bit 0 = "enabled".

## 4. What the apertures actually contain (boots #36–#45)

| place | contents |
|---|---|
| `0x4d04000` | the **read-only G10P device-information page**: `0x01001000`, `0x00010704`, `0x00090303`, `0x00020202`, `+0x48 = 0x0f`, `+0x4c = 0x2f`, `+0x60 = 0x2`, `+0x80 = 40`, `+0x84 = 64`, `+0x88 = 40`.  It ignores writes (except `+0x80`!) |
| `0x4d08000` | all zero |
| `0x4d00000 + 0x54` | the only live word in the Fender window's page 0 (`0x6`) |
| `0x4d10000` (Fender) | traps at `+0x44` |
| `0x4d20000` | the firmware window registers: `+0x00 = 0x101`, `+0x08` = window base, `+0x10`, `+0x24` = window size, `+0x38` = window enable, `+0x40 = 0x30000`, `+0x48 = 0x79` |
| `0x4d24000` | **dead**: reads zero and ignores every write (boot #40) — this is where the kext's "IOP + 0x4000" points |
| `0x4d28000` | the DART (`+0x8000` = `dart_vm_size`, `+0x8108/+0x810c` = base config, `+0x8130`… = page-group masks), timebase at `+0x80c` |
| `0x4d2c000` | empty apart from our own writes |
| `0x4d30000` | a **chip-ID block**: `+0x08/+0x0c = 0xffffffff`, `+0x10/+0x14` = a 64-bit serial that counts down between boots, `+0x30`, `+0x40` likewise |
| `0x04000000` | the RGX core window; only `+0x18` (CORE_ID) and `+0x20` may be read |

Both apertures were also **written** with both classes' enable sequences
(boots #43/#44): only the known pages take the write, so there is no
mailbox with a writable status register in either aperture.

## 5. The PMP's clock-gate message (decoded from its firmware)

`pmp-t8015.bin`, handler at **0x0100e920** (the `!clg: %08x` rejection
string is at 0x012c60).  It parses the **high** 32 bits of the 64-bit
message it receives:

```
  bits 0..11   the gate id       (payload bits 32..43)
  bits 12..19  the device        (payload bits 44..51)
  bits 20..    the command       (payload bits 52..63)
```

and rejects the message when bits 22..23 are set.  The value it writes to
the PMGR is chosen by the command: **bit 31 → `device << 12`, bit 30 →
`device << 20`, bits 20..21 != 0 → `device << 21`, otherwise nothing.**

The boot #25 sweep was wrong twice over: the command went into the **low**
word, and the command was 1 (whose bits 20..21 are zero → "do nothing").  A
correct message is `(cmd << 52) | (device << 44) | (gate << 32)`.

Boot #46 sent it on app endpoint 0x20 (wrong — that is the AGX init
endpoint; the RTKit layer refused).  Boot #47 sent 324 shapes as
**management** messages on endpoint 0 (the format matches a management
message: type in bits 59:52) and **the PMP never answered** — so either the
service is not on the management endpoint, or the command/device/gate values
are still wrong.

## 6. The PMGR picture (from the ADT)

| device | id | flags | its register |
|---|---|---|---|
| GFX | 124 | perf | PMGR window 0 + 0x80338 = our `ps_gfx` (psreg 4, psidx 7) |
| GFX-SGX | 148 | no_ps | window 1 + 0x80000 (nominal) |
| GFX-KF | 149 | no_ps | window 1 + 0x80000 (nominal) |
| GFX-BUSY | 123 | no_ps | window 1 + 0x80000 (nominal) |
| PMP | 54 | perf, critical, **on** | window 0 + 0x80308 |

The GFX's ps entry decodes as `clk 1, pwr 1, actual 0xf, target 0xf` and the
GPU core answers (CORE_ID ✓) — so the **core is alive** and it is the
**GFX-KF** (the Kingfisher: the mailbox IRQs and the Fender/IOP windows) that
is not.  The three `no_ps` devices have no power-state register, so their
gates are plain gate registers somewhere else.

**Boot #49 ruled out two candidates:** the `pmgr1 + 0x80000` bank has entries
only up to `+0x140` (nothing at the device-id offsets 0x3b8/0x4a0/0x4a8 ✓),
and `pmgr0 + 0x70000` is the **DVFS/voltage table** (0x4605 = 17925 µV etc.,
ten idle entries ✓), not a rail register.  (`pmgr0 + 0xa0000` is also a DVFS
table ✓ — the A12's two offsets are swapped relative to the A11 ✓.)

BadApple's A12 guide (`kieroid/badapple`, `docs/gpu.md`) says the A12's GPU
rails are a plain PMGR register that Linux writes directly — "clear bits 10
and 12 of `0x23b0a0000`" — because iBSS leaves GPU rails 2 (SRAM) and 4
(core) at 0.  The AGX apertures are at the *same addresses* on both chips
(the A12's hwdata B: "IO maps: Fender 0x204d00000, RGX 0x204000000" ✓), so
the A11 is probably the same story — we have not found its register yet.

## 7. The firmware's own view

* **IO map** (A11 `g10p.img` at 0x3759c, A10 `gfx-t8010-const.bin` at
  0x35565): the A11 sees `0x04d20000` size 0x20000 and `0x04000000` size
  0x200000; the A10 sees `0x01d20000` size 0x20000 and `0x01000000` size
  0x100000.  The A10's mailbox (0x1d24000) is *inside* its IOP window at
  +0x4000; on the A11 that page is dead, so the A11's mailbox is in the
  same window at a **different offset** — and it must be **dormant** (a
  dormant mailbox reads as zero, which is why every read-only sweep was
  empty).
* **AGX hwdata** (the host→firmware configuration), 53 entries of
  {firmware address, mask, buffer offset} in `__PLK_DATA_CONST`
  0xfffffff006f8ab88: offsets 0x20/0x24, 0x48/0x4c, 0x140/0x148,
  0x188…0x19c, 0x404…0x414, 0x500, 0x800…0x80c, 0x900…0x91c, 0xc10/0xc14,
  0xc30/0xc34, 0xe00 — including the timebase pair at 0x808/0x80c and the
  A10-pair at 0xc30/0xc34, the very offsets our driver writes.
* The firmware's **init handler** (the 0x81 message) is at img 0x19318; the
  init page is 0x98 bytes with X/T at +0x18/+0x1c (KB:
  `A11-GPU-G10P-LAYOUT.md`).

## 8. The open leads, ranked

1. ~~**The `AppleA7IOPV4GFX` register-map data**~~ — **DONE, 2026-11-12.**
   The offsets are +0x110/+0x114/+0x800/+0x830 in the Fender window (§3).
   *What is left is the write side: which bits to write to CPU_CTRL to
   enable the mailbox and unmask the RTKit interrupt, and whether the GFX
   class has an IRQ-enable register of its own (the M3Wrap base had
   +0x48/+0x4c; no +0x118/+0x11c access was seen).*
2. **Boot #50's result** — does CPU_CTRL at 0x204d00110 read anything?  If
   it is non-zero the mailbox is live and we can talk RTKit; if it is zero the
   Kingfisher is still dark and lead 2 (the gate register) is next.
3. **The AGX block's own power/clock registers** (+0x1008 / +0x1020) — boot
   #52 tries them.  This is Apple's `ps-reg-offset` register, and the
   kext's offsets are the only evidence for where it is.
4. **The GFX-KF's gate register** (§6).  The A12 writes its GPU's rails
   directly; find the A11's equivalent (the `no_ps` devices' gates) and
   write it.  The ADT's gfx-kf node uses the gate of device 149.
   The PMP is what writes it: its firmware's clock-gate handler is at
   **0x0100e92c** and parses the message's high word as
   {gate id bits 0..11, device bits 12..19, command bits 20..31}, writing
   `device << 12` (or `<< 20`, `<< 21`) — so the request is
   `(cmd << 52) | (device << 44) | (gate << 32)` with the **type in the low
   four bits of `cmd`** (the message's bits 52..55) and bits 54..55 clear.
   The PMP's management dispatch (0x0100ddc2) has **16 types**; boot #47
   swept 324 shapes and the PMP never even answered (its six periodic
   messages are the only replies we ever see), so the gate request is
   probably **not** a management message, or the gate id / the 0x202
   register selector is still wrong.
5. **The PMP's gate service endpoint** (§5).  It is reached through a
   computed dispatch (no function-pointer table entry), and the RTKit layer
   refuses to send on an endpoint that has not been started — so an endpoint
   sweep needs the STARTEP acknowledged, which 0x20 was not.
6. **The enable values.**  Only the kext knows what M3Wrap_CTRL and
   IntOutIRQEn must be; our guesses (1 and 0x1111) may enable nothing, and
   a write-protected block looks exactly like a dead page.
7. **The core window** (0x04000000): the firmware can reach it, so the
   mailbox may be there — but the RGX's registers trap, so it has to be
   probed one offset at a time.

## 9. How to build and boot

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

* The kernel tree is a git repo on branch **`gpu/phase2.2`**; the driver work
  is committed as **`a0ac7ce34bde`** (boot #52: the AGX block's pages 0 and 1
  and the kext's own power-state registers).
* The last built payload:
  **`0afc7c766a36d012298edd7807db217c046404e980a69754b049d43d6181b516`**
  (boot #52).
* The kernel log is streamed to `/tmp/opencode/phone-kmsg.log` by
  `GPU-WIP/tools/kmsg-host.py` (pid 412793; do **not** kill it).  Boot #N
  starts at the `GFX-STAGE 0/12` line.
* A boot counts only when the phone re-enumerates as `05ac:4144`; `RUN_EXIT=0`
  proves nothing (the upload can fail with `LIBUSB_ERROR_OTHER` and still
  exit 0 — check `orchard devices` and the log, not the exit code).
* One boot per explicit go; the phone must be in PongoOS first (after a boot
  it is in iOS and has to be restarted by hand).
* The driver is a *diagnostic* driver: it prints everything it reads, and
  each stage is one experiment.  Read `drivers/soc/apple/apple-t8015-gfx.c`
  before changing it — the comments record why each step is there.

## 10. The project's own driver

`drivers/gpu/drm/imagination/pvr_apple.c` + `pvr_apple_layout.c` are the
project's **A11/G10P** driver (not the A10's): it knows the bring-up
(`pvr_apple_fw_start()` sends `APPLE_MSG_INIT | (win_dma + 0x98000)` on
`APPLE_EP_AGX_INIT` = 0x20 and waits for the firmware's ready flag at
`heap + 0x14188`), the window layout (`WIN_INIT 0x98000`, `WIN_DESC 0x9c000`)
and the init-page fields.  Our diagnostic driver
(`drivers/soc/apple/apple-t8015-gfx.c`) compiles `pvr_apple_layout.c` into
itself (the DRM stack is a module, so its symbols are not linkable from a
built-in driver).

## 11. Where the knowledge is

| what | where |
|---|---|
| the boot log of every attempt | `GPU-WIP/probe/STATUS.md` (chronological, with verdicts) |
| the A11 register map we measured | `GPU-WIP/probe/phase2.2/G10P-REGISTERS.md` |
| the GFX bring-up spec | `GPU-WIP/probe/phase2.2/G10P-BRINGUP.md` |
| the mailbox map, and the V4 class | `GPU-WIP/probe/phase2.2/A7IOP-MAILBOX.md` |
| the A12 (BadApple/Cascadia) AGX driver as a reference | `GPU-WIP/probe/phase2.2/A12-REFERENCE.md` |
| the offline RE helpers (now in the repo) | `GPU-WIP/tools/` — see `tools/README.md` |
| the PMP firmware's clock-gate handler | `GPU-WIP/probe/STATUS.md` (boot #51 section) |
| **the V4 GFX register map (solved)** | `GPU-WIP/probe/phase2.2/A7IOP-MAILBOX.md`, reproduced by `GPU-WIP/tools/a7iop-v4-gfx.py` |
| the project's own earlier RE (huge) | `Known Good State/firmware/GPU/` — `A11-GPU-FINDINGS.md`, `A11-GPU-G10P-LAYOUT.md`, `A11-GPU-G10P-BOOTCHAIN.md`, `A11-GPU-G10P-STAGE2.md`, the extracted `AGXG10P__*.bin` segments, `agxg10p.asm` |

## 12. Conventions

* Never read or write GPU/Fender/GFX-IOP registers from userspace or
  `/dev/mem` — only in-kernel driver access.
* Keep `simplefb`/`simpledrm`; never touch the display/panel/adpdrm, Wi-Fi or
  other lanes; no storage writes without a go (the `gpu-diag` init path
  avoids storage writes).
* Keep `powervr` unloaded; never use `apple,t8010-gpu` in the DT.
* Push only to iPhOmarchy `GPU-WIP/`; the KB mirror at
  `/home/doug/Known Good State/` is **not** a git repo.
* No Apple binary blobs (PMP/GFX firmware) in the git repo — publish the
  extraction tools only.
* Do not blind-write new PMGR windows/registers without a prior read-only
  probe boot (boots #43/#44 did the read-only probe first ✓).
* One boot per explicit "go"; each rebuild needs approval.
