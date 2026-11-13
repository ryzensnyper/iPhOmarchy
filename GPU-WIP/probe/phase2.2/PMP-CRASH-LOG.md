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
