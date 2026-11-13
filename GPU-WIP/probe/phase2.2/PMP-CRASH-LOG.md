# The PMP crash log — our messages crash the firmware, and the log decodes them

Offline + boot #67 findings, 2026-11-13.  The PMP firmware (Thumb-2, linked
at 0x01000000) has **no hardening against malformed ep-32 messages**: certain
message shapes pass garbage into its transaction dispatcher and it dies with
a data abort.  The RTKit crash log it leaves behind names the faulting PC,
the register values and the last 16 mailbox messages — a **direct decoder of
the protocol**.

## 1. The crashes (one per boot, reproducible)

| boot | crash at | the last ep-32 message before death |
|---|---|---|
| #59 | 50.14 s | `0x0011000000950000` = cmd 1, dev 149 (bare cmds 1..10 + cmd-0 forms preceded) |
| #60 | 53.61 s | during the cmd-5 write sweep (20/20 acked first) |
| #64 | 112.12 s | at the 9d bare-cmd replay |
| #67 | 49.18 s | the deliberate replay of #59's tail (cmd 1 + dev 149) |

Boots #61/#62/#63/#65/#66 saw no crash print — reads (cmd 3) alone never
crashed it.  **The bank[20]/bank[40] toggles in #59/#64 happened AFTER the
crash** — they are the PMP dying/restarting, not a gate responding.  The
"once-per-boot" acks are likely the same artifact.

## 2. The crash log sections

The kernel's rtkit core only parsed Cver/Ctim/Cmbx.  `rtkit-crashlog.c` now
dumps every section raw and parses **CrgA** (the 32-bit exception regs — the
PMP is Thumb-2; upstream only knows the 64-bit Crg8).

Boot #67's crash log (kmsg at 49.18):

* **CrgA (0x180 bytes)** — 32-bit exception frame + stack snapshot.  The
  frame (layout derived from the values): `r0..r14` in words [0..14],
  `sp` [15] = `0x0101c8c0`, `lr` [16] = `0x01001857`, `pc` [17] =
  `0x0100d64c`, `cpsr` [18] = `0x2000003f` (**Thumb**, Sys mode) — then the
  stack (word [21] is the ASCII fragment `'TACK'`).
  **r0 = 4** — the garbage pointer that killed it.
* **Ccst (0x40)** — the call chain as 64-bit words:
  `pc 0x0100d64c`, `0x01001852`, `0x01010c56`, `0x010094d8` — the faulting
  function and its callers.
* **Cmbx** — the mailbox history: the last 16 (endpoint, message) pairs on
  ep 32.  Entries `0x0000000000000020  <message>` — 0x20 = the endpoint.
* **Rtbk (0x220)** — RTKit bookkeeping with thread names: the crash context
  is the **`rtk_ep_work`** thread (the endpoint work queue — i.e. the ep-32
  message processor itself), plus "power" and "main".

## 3. The fault, decoded

```
0x0100d640: push  {r4, r5, r6, r7, lr}
0x0100d64a: mov   r6, r0
0x0100d64c: ldr   r0, [r0, #20]      <== faulting PC; r0 = 4 -> read of 0x18
0x0100d64e: tst   r0, #28            (a flags check on the object at +20)
```

The caller (LR `0x01001856`):

```
0x0100184c: ldr   r0, [sp, #8]       ; the object pointer -- it was 4
0x0100184e: mov.w r1, #1296          ; 0x510
0x01001852: bl    0x01002678
```

`0x01002678` is an **address-translation helper** (`cbz r0,..; r3 = r0 -
region_base; far call; tail`) — the PMP resolves an incoming address/index
into an internal object, then `0x0100d640` dispatches on it.  With our
message the resolve produced the raw value **4**, which the dispatcher
dereferenced.

So the ep-32 path is: message → `rtk_ep_work` → a resolve step → the
transaction dispatcher at `0x0100d640`.  The resolve step is where the
8-entry runtime registry (0x01017284) lives — **our messages make it
produce the integer 4** (an error code? an unimplemented-function id?
"transaction type"?) which is then used as a pointer.

## 4. The next move: use the crash as an oracle

Vary ONE message field at a time; read `r0` (and crash/no-crash) out of the
crash log.  The value the resolver hands the dispatcher as a function of the
message fields IS the message format.  Planned sweeps (one boot):

1. `cmd 1 + dev 149` alone (no preamble) — does it crash?  what r0?
2. the same for cmd 0..15, dev 0 — map cmd -> r0.
3. dev 148/123/124/54 at cmd 1 — map dev -> r0.
4. with the v2 flag cleared (`msg = cmd << 48` only).

If some (cmd, dev) makes the resolver produce a *pointer* instead of 4,
that message shape is the one the firmware expects — send it and watch the
mailbox.

## 5. Boot #68: the SRAM window and the isolated crash shape

Two results that change the game:

* **The PMP's SRAM is AP-readable.**  `0x232500000` (128 KiB, inside the
  pmgr0 span) reads fine and holds LIVE firmware state: the registry
  struct at PA `0x232517284` = `{count 8, entries-ptr 0x01017264}`,
  exactly as offline.  But the *entries area* (PA `0x232517264`) holds
  Thumb-2 code bytes at runtime where the image file has zeros — **the
  runtime firmware differs from `pmp-t8015.bin`** (self-patched or
  relocated at load).  Crash-chain return address `0x0101882c` is zeros
  in the file too.  So: dump the SRAM for ground truth (boot #69).
* **The crash shape is isolated and the oracle is repeatable.**
  `cmd 1 + dev 149` is the ONLY crashing shape (cmd 0, 2..15 with dev
  149 alive; cmd 1 with dev 148/123/124/54 alive), it crashes with no
  preamble, and `apple_rtkit_reinit + boot + start_ep(32)` brings the
  PMP back (~16 s incl. timeouts) — after which the same message no
  longer crashes (once per firmware load).

The minimal crash (no preamble) dies at a DIFFERENT site than #67's
post-preamble crash:

* #68 PC `0x010086a2` = `ldrb r0, [r5]` — a byte-walk running into
  unmapped memory; chain `0x0101882c <- 0x010187f2 <- 0x01011894 <-
  0x01010c56 <- 0x010094d8` (Ccst, six deep).
* #67 PC `0x0100d64c` = `ldr r0, [r0, #20]`, r0 = 4; chain
  `0x01001852 -> 0x01002678 (translate) -> 0x0100d640`.

Same message, two crash sites, state-dependent — the message triggers a
fragile path, and which load falls over depends on prior state.

## 6. Boot #69: the runtime image, and what the crash was doing

`GPU-WIP/tools/extract-sram.py` rebuilds `pmp-runtime.bin` (the whole
128 KiB of SRAM at the moment of the dump) from the boot log.  Findings:

* **The code pages are byte-identical to the file image.**  All 2333
  runtime-vs-file diffs live in the data pages (0x14000-0x1e000): BSS,
  runtime-built tables and objects.  The offline RE of CODE is valid.
* **The registry is a magic-record list.**  Records starting with the
  sentinel `0xb0bed0ff` sit at `0x0101728c`, stride `0x18`
  (`{b0bed0ff, 0, 0x01017290, 0x01016c08, 5, 0x0101e340}`,
  `{b0bed0ff, 0x0101e1c0, 0xc, ...}`), and the word the struct points
  at (`0x01017264`) holds **`0x0101de70` at runtime — a list head into
  RAM**: `{1, 0x01017540, 0x01017480, 0x100, 0x20, 0x0101de20,
  0x0101de30, 0x0101b9f8, 0x5e50, 0x18, 0x10001, ...}`.
  Decoding that list = the registered device names/ids, i.e. the valid
  handles.
* **The minimal crash (cmd 1 + dev 149) is a strlen walk.**
  `0x010086a2: ldrb r0, [r5]; cmp r0, #0; bne` — the firmware walks a
  string (a device name?) whose pointer is garbage.  Chain (Ccst):
  `0x0101882c <- 0x010187f2 <- 0x01011894 <- 0x01010c56 <- 0x010094d8`
  (the first two are RAM addresses, not code).
* **The crash footprint is a gate-transaction table for device 149.**
  The SRAM delta (716 words) shows 15 pairs written at `0x01014330`:
  `{0x0095X643, 0x00600000}` for X = 0x0..0xe — device **0x95 = 149** at
  bits [23:16], an index at [15:12], value **0x643** at [11:0], and
  `0x00600000` (mode 3 + direction, of the clg command-word family).
  Plus stack slot `0x0101ee44 = 4` — the phantom pointer boot #67's
  dispatcher dereferenced.
* **cmd 1's handler builds a list of 15 gate operations for dev 149**
  (value 0x643, indices 0-14) and dies mid-walk.  15 operations for the
  GFX-KF — the firmware's own bring-up sequence for the Kingfisher!
* The reboot failed this time (`apple_rtkit_boot -> -62`): unlike #68,
  the PMP stayed dead after the crash.

So cmd 1 + dev 149 makes the PMP TRY to bring the Kingfisher up — it
builds 15 gate operations and crashes before finishing.  The next step
is decoding the device list (0x0101de70) and the cmd-1 handler offline,
then finding a message shape that completes the sequence instead of
crashing.

## 7. Offline decode session (post boot #69, 2026-11-13)

All offline, no boot.  Code addresses valid in `pmp-t8015.bin` (the code
pages are identical to the runtime image).

### 7.1 The firmware's C++ vtables

The method-pointer table spans `0x01013100..0x01013400+` (and beyond);
`0x0100a87d` is the abstract/default stub filling unused slots.  The
message classifier (`0x0100c02d`) is a vtable entry at `0x010132c4`.

### 7.2 The transaction dispatcher (0x0100dc60) — the type table

`obj[8]` is resolved through the split helper, then
`ubfx r6, #20, #4` on the resolved word picks the transaction type and a
`tbb` at `0x0100dc96` dispatches:

| type | target | note |
|---|---|---|
| 1 | `0x0100dca0` | `movs r0, #33; bl 0x0100FEDC` then common tail — a reject-ish path |
| 2 | `0x0100dcb0` | queue-index handling (`lsrs/uxth/strh [r10,#12]`) |
| 3 | `0x0100dcce` | — |
| 4 | `0x0100dda8` | — |
| 5,6,7 | `0x0100ddac` | the registry-lookup family |
| 8 | `0x0100dce4` | the registry walker |

### 7.3 The crash, fully explained

The `0x010086a2` loop is a **printf emit**: `r8` = the printer object,
`r2 = [r8]` = its putc, `blx r2` per character, `r11` = the precision
counter, `r5` = the string pointer.  **CrgA r5 = 0x73 (115)** — the
firmware called print("%s", 115): an integer passed as a string.  The
message it tried to log never made it out (no syslog prints ever reached
us in any boot).  cmd 1 + dev 149 → error path → logging bug → death
mid-walk, with the 15-op table half-written.

### 7.4 The 15-op table (the Kingfisher bring-up sequence)

Pairs at `0x01014330`, 15 entries: `{0x0095X643, 0x00600000}`,
X = 0x0..0xe:
* device **0x95 = 149** at bits [23:16]
* index at [15:12]
* value **0x643** at [11:0]
* `0x00600000` — mode 3 + direction, clg-command-word family

`0x01014000` (the table's page) is referenced from code at
`0x10004a8, 0x10004b4, 0x1006d38, 0x1006eb8, 0x100d364, 0x1010810` — the
table writer is among these.  Not fully decoded yet.

### 7.5 The firmware's strings (complete inventory, 285 strings)

The relevant ones: `pm_enqueue_message failed status %u` (0x01012b1c),
`MBI queue overflow:%s` (0x01012bb6), `Mbox:%s (h=%p %x=%x)`
(0x01012bde), `!clg: %08x` (0x01012c60), `Not implemented`
(0x01012c6b), `Invalid AP power: %d`, `RTKit: %s - Client: %s`,
`pmon-%s-%s`, `stk_fail`.  **No device names in the image** — the names
live in the runtime-built RAM objects (the 0xb0bed0ff records / the
0x0101de70 list).

### 7.6 What this means

The PMP *has* a built-in bring-up sequence for the Kingfisher (15 gate
operations).  cmd 1 asks it to run; it dies on a logging bug part-way.
The remaining question is what state the handler needs to complete —
boot #70 sweeps cmd 1 across the device ids with full watching, then
crashes deliberately for a fresh crashlog.
