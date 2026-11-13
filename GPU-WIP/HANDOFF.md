# Session handoff — A11 (G10P) GPU bring-up

*Rewritten 2026-11-12 after boot #58, immediately before a session compaction.
Everything below is committed and pushed; nothing important lives only in the
conversation.  The kernel tree is committed too.*

---

## 0. How to resume (read this first)

The goal is to boot the GFX IOP's firmware (the AGX/RTBuddy) on the iPhone 8
Plus so the GPU can be driven.  Phase 2.2's stated goal — **Fender power +
RGX identity** — was met long ago (boot #15).  What is still missing is the
**mailbox**: without it the IOP firmware never sends its RTKit HELLO, so
`apple_rtkit_boot()` times out (-62) and no AGX endpoint can be started.

**The mailbox has been located** (boot #50/#51, from Apple's own kext) and it
is **dark** — its registers read zero and ignore writes, because the
Kingfisher (the IOP) is not powered.  **The blocker is the power gate**, and
the gate is written by the **PMP**, in the PMP's own address space, which the
AP cannot write directly (boot #58).

So the next session's job is: **get the PMP to ungate the GFX-KF**, or find
another way to wake the IOP.

**The PMP v2 channel on endpoint 32 is fully live and understood at the
message level** (boots #59-#63, tree `3400f64a6f76`):

```
msg = (1 << 52) | (cmd << 48) | (domain << 42) | ((arg >> 12) << 16)
ack = (cmd+1) << 48 | device-echo << 32 | value
```

cmds 1/3/5 respond; drive at ≥200 ms/message or the queue drops; cmd 3
is a read (returns a 32-bit value, ignores the payload, echoes the
device at bits 32..39); cmd 5 acks and changes nothing visible.

**The blocker**: the firmware's clg handler resolves its target through
an **eight-entry runtime registry** (`0x01017284`: count at +0, entries
pointer at +4 = 0x01017264; index = the handle's high 16 bits; entries
are C++ objects, vtable at obj+8; the getter/invoker is 0x0100a23c).
The registry is **EMPTY in the firmware image** — populated at runtime
by the PMP's device drivers — so the valid handles (idx 0..7 × id) are
not decodable from the image, and every gate request so far (device
values 123/124/148/149, or 0..7) has failed the resolve silently.

**Boot #64 (tree `ca9c2729edb8`)**: the bare-cmd acks reproduce exactly
(cmds 1/3/5 ack once per boot, 2/4/6 never); the registry-handle reads
(idx 0..7 × id {0,1,0x95,0x97}) read all-ones; and the bank[20]+bank[40]
toggle fired cleanly inside the mgmt type-3 phase — ON at
(type 3, dev 5, gate 149, payload 1), OFF at (dev 6, gate 0, payload 0).
The toggle has appeared in #59/#62/#63/#64 and only during mgmt phases.
The mailbox stayed dark throughout.

**Ranked next moves**:

1. **Boot #68: the crash oracle.**  The PMP firmware crashes on malformed
   ep-32 messages and leaves a CrgA register dump; the resolver hands the
   dispatcher `r0 = 4` for our current shape.  Sweep one field at a time
   (cmd 0..15 × dev {0, 54, 123, 124, 148, 149} × the v2 flag on/off),
   300 ms apart, each followed by a 700 ms settle; read the crash/no-crash
   and the r0 value out of the crash log.  Any (cmd, dev) that yields a
   *pointer* instead of 4 is the shape the firmware expects.
2. **Offline: decode the resolver** (`0x01002678` → its far call) and the
   dispatcher (`0x0100d640`, `tst r0, #28` on obj+20) to learn what the
   r0 values mean (error codes? transaction types?) without more boots.
3. **Offline: who populates the eight registry entries at runtime** (13
   code sites reference the struct at 0x01017284).
4. The untried `meta-sw-interrupt` lead (`/arm-io/sgx`,
   `0x233104020`/`0x2331040a0`, write 2 then 8).
5. The PMP's mgmt type-6 `SET_IOP_PWR_STATE` with the GFX identity.

See `probe/STATUS.md` boots #59-#67 and `probe/phase2.2/PMP-CRASH-LOG.md`
for the full data.See `probe/STATUS.md` boots #59-#64 for the full data.  The v2 message shape is now decoded from ApplePMP.kext's
own send path (`ApplePMP::_sendPMCommand`'s construction at
0xfffffff00610b868), which is better evidence than the kext vtables:

```
msg    = (1 << 52) | (cmd << 48) | (domain << 42) | ((arg >> 12) << 16)
ack    = (cmd+1) << 44 | domain << 40 | device << 32 | payload
         (ApplePMP.cpp: pm_msg_get_cmd(ack_msg) == command + 1)
```

The boot sweeps: all sixteen `cmd`s, the device forms (`arg = dev << 28`
puts the device at ack bits 32..39), and the clock-gate word
`{value[11:0], device[19:12], mode[21:20]}` in the placement the
management handler decoded — watching the GFX mailbox's CPU_CTRL, the
GFX ps entry (0x232080338) and gate-bank entry 0 (0x235280000) after
every message.  It runs at stage 3b, early, so the RTKit boot that
follows runs against a live mailbox if one of them wakes the Kingfisher;
it repeats at 9d.

Two new offline facts since the last handoff (both committed):

* **GFX-SGX (148), GFX-KF (149) and GFX-BUSY (123) all have
  `psreg 0, psidx 0`** in the ADT — their ps register is **entry 0 of
  the gate bank at 0x235280000** (boot #58 read it as 0x1f0000ff), while
  the parent GFX (124) is on at `ps_gfx` (0x232080338).
* the management endpoint's type-3 handler bails **silently** if the
  handle it resolves (`obj+52`) is not in the firmware's registry —
  which is why 336 requests never wrote anything: our device ids do not
  index the PMP's function registry.

§8.2 explains why the AP cannot ungate anything itself (the PMGR is a
dock-FIFO agent of the PMP).  §8.3 has the remaining leads, led by the
ADT's `meta-sw-interrupt`, which has never been tried.

---

## 1. Where we are

| item | value | since |
|---|---|---|
| RGX identity | `CORE_ID (0x0018) = 0x7E1` → `{ID=0x0000, CONFIG=0x07E1}`, `n=0x07`, `c=0xE1` | boot #15, every boot since |
| Fender power | the state register answers; the ack never sets | boot #15 |
| window copy | Fender `+0x200c` and IOP `+0x08` read back | boot #15 |
| IOP release | the run bit latches (`+0x2048`) | boot #15 |
| device information | `0x204d04000` — read-only, 8-byte stride; `+0x80 = 40` is the A10's `phys_bus_width` | boot #18/#40, corrected boot #55 |
| DART / IOMMU | `0x204d28000` — `dart_vm_size = 0x4f`, base `0x00020001`/`0x00100101` | boot #21 |
| firmware image | 381728 bytes = 0x5d320 (the KB's `gfx-t8015-const.bin[9:9+0x5d320]`) | boot #28 |
| architecture | **AGX** (`AGXG10P`, `AGXFirmwareKextG10PRTBuddy`) | boot #26 |
| **the G10P mailbox** | **0x204d00110** (control), **+0x114** (status), **+0x800** (TX), **+0x830** (RX) | boot #50/#51 |
| **the AGX register block** | **the Fender window, 0x204d00000** | boot #50 (proved by `+0x4008 = 0x00010704`) |
| **the PMP's gate write** | `*(device<<12 + 0x202) = (old & ~0x8960) \| (msg==1 ? 0x2000 : 0)` — it clears **bit 6** | boot #57 (offline) |
| the PMP answers us | reply = `0x40000000000000 \| payload` (an **echo**, not a status) | boot #53/#57 |

**What still fails:** the RTBuddy firmware never starts.  It never sends its
RTKit HELLO → `apple_rtkit_boot()` = -62 → `start_ep(0x20/0x21)` = -22 → the
AGX init message cannot be sent.

---

## 2. The hardware map (measured; all AP addresses)

| what | address | notes |
|---|---|---|
| RGX core window | `0x204000000` (1 MiB) | **CORE_ID is the only live word in the first 4 KiB** |
| gfx-kf region A ("IOP") | `0x204d20000` (128 KiB) | the IOP's own registers: window regs, DART at `+0x8000`, timebase at `+0x80c`, config at `+0x8130` |
| gfx-kf region B ("Fender") | `0x204d00000` (128 KiB) | **the AGX register block**: the mailbox at `+0x110`, the device-info page at `+0x4000`, the power state at `+0x1000` |
| the ADT's gfx-kf node | `reg = <0x4d20000 0x20000>, <0x4d00000 0x20000>` | the mailbox IRQs 259-262 belong here; `power-gates = 149`, `clock-gates = 149`, `force-timebase-sync` |
| the ADT's sgx node | `reg = <0x4000000 0x100000>, 0x4d00000 0x20000>` | `power-gates = 148, 123`; `has-kf = 1`; `meta-sw-interrupt` = `0x32104020 <- 2`, `0x321040a0 <- 2`, `0x8` |

**Traps — reading these hangs or resets the SoC (no panic, straight to DFU):**

* `0x204d040c0` and beyond (the hole past the device-info page),
* `0x204d10044` (the Fender window's upper half),
* `0x204000000 + 0x00` (the RGX's first core register — only `+0x18`, `+0x20` are safe),
* **anything past a PMGR window's end** — the PMGR's two windows are
  `0x232000000` and `0x235200000` (32 MiB apart, *not* 1 MiB apart; boot
  #54 took an SError by assuming otherwise),
* the A7IOP shim aperture `0x2ee00000` (not reachable from the AP).

---

## 3. The kext: the A11 uses a *different* class

The kernelcache's personality dictionary binds the GFX IOP like this:

```xml
<key>AppleA7IOPV2-GFX</key>  IONameMatch: iop-gfx,{s8000,t8010,t8011}
<key>AppleA7IOPV4-GFX</key>  IONameMatch: iop-gfx,t8015      <-- the A11
```

So the A11 is **`AppleA7IOPV4GFX`** (source
`/Library/Caches/com.apple.xbs/Sources/AppleA7IOP/AppleA7IOPV4GFX.cpp`),
**not** the V2 class our original bring-up spec was copied from.

### SOLVED: the register map

The "register map" is **not** an offset table.  The class's accessor is two
instructions (`__PLK_TEXT_EXEC` 0xfffffff00575b100):

```
ldr  x8, [x0, #256]      ; the mapped AGX register block (_agxMappedRegs)
ldr  w0, [x8, w1, uxtw]   ; ...at the given byte offset
ret
```

so the offsets the kext passes around **are** the physical offsets in the
mapped block.  (`_agxRegisterMap`, member +0x170, is a descriptor struct,
not a table.)  Reproduce all of this with `GPU-WIP/tools/a7iop-v4-gfx.py`.

### The G10P mailbox layout

`AppleA7IOPV4GFX` **overrides** `getMailboxBulk` (vtable slot +97,
`0xfffffff00575ba0c`) and does *not* use the M3Wrap base class's layout:

| offset | register | address on the A11 | evidence |
|---|---|---|---|
| **+0x110** | **CPU_CTRL** — bit 0 = enabled, 16 = TX full, 17 = RX empty | **0x204d00110** | read at 0x575b788/0x575b974/0x575b998/0x575ba44 |
| **+0x114** | **status / enable** — the host does a read-modify-write of **bit 0** | **0x204d00114** | 0x575b72c (slot +124) |
| **+0x800** | **TX data**, 16-byte words | **0x204d00800** | 0x575b94c: `add x10,x10,#2048; stp x8,x9,[x10]` |
| **+0x830** | **RX data**, 16-byte words | **0x204d00830** | 0x575b938: `add x8,x8,#2096; ldp x8,x9,[x8]` |

`0xc0000` (bits 16|17) is the "invalid" state the kext asserts against.
The message size is 16 bytes (`0x575b960: mov w0,#16`) and the control word
is a **ring queue**: bits 8-10 = TX write pointer, bits 12-14 = RX read
pointer, 8 entries deep (`0x575b8f4` decodes them).

The **M3Wrap base class** (`AppleMxWrap`/`AppleM3WrapV2`, the class used by
the M-series IOPs) uses a different set — 0x08 CTRL, 0x48 IntOutIRQEn, 0x4c
IntOutSts, 0x50 INBOX_CTRL, 0x60 TX, 0x80 OUTBOX_CTRL, 0xa0 RX — and **every
earlier boot used those instead** (boots #34/#35's `0x1111` mask, #43/#44's
"V4 enable sequence").  **+0x110 was never read once in 19 boots.**

The class hierarchy, from the kext's own REQUIRE strings:
`AppleIOP → AppleA7IOP → AppleA7IOPV1 → AppleA7IOPV2 → {V2GFX, V2Marconi,
V2PMP} → AppleA7IOPV4 → AppleA7IOPV4GFX`, plus `AppleMxWrap →
AppleM3WrapV2`, `AppleASCWrapV2/V4`, `AppleASCANS2`, `AppleA7IOPNub`.

### Which aperture is the AGX block?

Three independent correlations say **the Fender window, 0x204d00000**: the
kext reads the device-information page at +0x4008 and the power state at
+0x1008, which is exactly where we measured them; and boot #50 read
`+0x4008 = 0x00010704`, the page's third 32-bit field (the page is
**8-byte stride**, not 4).

---

## 4. What the apertures actually contain (boots #36–#58)

| place | contents |
|---|---|
| `0x4d00000` (Fender) | **only three live registers in pages 0+1**: `+0x54 = 0x6`, `+0x1000 = 1` (our own power request), `+0x1014 = 2`.  The mailbox at `+0x110` is **0** and ignores writes. |
| `0x4d04000` | the **read-only G10P device-information page** (8-byte stride): `+0x00 = 0x01001000`, `+0x08 = 0x00010704`, `+0x10 = 0x00090303`, `+0x18 = 0x00020202`, `+0x48 = 0x0f`, `+0x4c = 0x2f`, `+0x60 = 0x2`, `+0x80 = 40`, `+0x84 = 64` |
| `0x4d08000` | all zero |
| `0x4d10000` (Fender) | traps at `+0x44` |
| `0x4d20000` (IOP) | window registers: `+0x08` = window base (our own write), `+0x28 = 0x00100000`, `+0x48 = 0x4f`, `+0x800` = `00000060 00180018 00000000 60000003` |
| `0x4d24000` | **dead**: reads zero and ignores every write |
| `0x4d28000` | the DART (`+0x8000` = `dart_vm_size`, `+0x8108/+0x810c` = base config, `+0x8130`… = page-group masks), timebase at `+0x80c` |
| `0x4d30000` | a **chip-ID block**: `+0x08/+0x0c = 0xffffffff`, `+0x10/+0x14` = a 64-bit serial that counts down between boots |
| `0x04000000` | the RGX core window; only `+0x18` (CORE_ID) and `+0x20` may be read |

---

## 5. The PMP's protocol (decoded from `pmp-t8015.bin`)

> The addresses below are correct only with the *fixed* disassembler:
> llvm-mc prints one line per **instruction**, so addresses have to be
> accumulated from the encoding lengths, not from the byte offset.
> `GPU-WIP/tools/pmpdis.py` does it right; the old `pmpdis2.sh` was 12 bytes
> out, which is why earlier notes had the handler at 0x0100e920 (it is at
> **0x0100e92c**).

* the management dispatch is at **0x0100ddc2**: `ubfx r0, r3, #20, #4` — the
  **type is the message's bits 52..55** (four bits, **16 types**) — and a
  `tbb` jump table at 0x0100dde8.  Type **11 (0xb)** is SET_AP_PWR_STATE
  (the one that works), type **3** is the **clock-gate handler**
  (0x0100e92c, where the `!clg: %08x` string lives).
* the handler decodes the message's **high** word:
  bits 0..11 = the gate id (`sbfx`), 12..19 = the device (`ubfx`), 20..31 =
  the command; **bits 22..23 must be clear** or it prints "!clg".
* the value it writes is `device << 12` (or `<< 20`, `<< 21`) depending on
  the command's bits.
* the actual write (0x0100c142) is:

```
ldr   r1, [r5, #8]        ; the base = device << 12
ldr   r2, [r1, r0]        ; the register at base + 0x202
bic   r2, r2, #0x8960     ; clear bits 5, 6, 11, 12
addeq r2, r2, #0x2000     ; set bit 13 if the message == 1
str   r2, [r1, r0]
```

  **so the PMP clears bit 6 — the "gated" bit — of a per-device gate
  register at `(device << 12) + 0x202`, in the PMP's own address space.**
* the PMP answers a management request with **type + 1** and the payload
  **`0x40000000000000 | <the request's payload>`** — an **echo**, not a
  status (boot #57 proved this: 21 different payloads gave 21 different
  echoes, all in the same shape).

---

## 6. The PMGR picture

| device | id | flags | its register |
|---|---|---|---|
| GFX | 124 | perf | window 0 + 0x80338 = our `ps_gfx` (psreg 4, psidx 7) |
| GFX-SGX | 148 | no_ps | — |
| GFX-KF | 149 | no_ps | — (the ADT's gfx-kf node uses **its** gate) |
| GFX-BUSY | 123 | no_ps | — |
| PMP | 54 | perf, critical, **on** | window 0 + 0x80308 |

The GFX's ps entry decodes as `clk 1, pwr 1, actual 0xf, target 0xf` and the
GPU core answers CORE_ID, so the **core is alive** and it is the
**GFX-KF** (the Kingfisher: the mailbox IRQs 259-262, the Fender/IOP
windows) that is dark.

The ADT's `pmgr/ps-regs[0]` = `{reg 1, offset 0x80000, mask 0x00200c53}` —
the **gate bank** in PMGR window 1 (`0x235280000`).  It has 41 live entries
(8-byte stride); **twelve of them read 0x244** (bits 6, 9, 10) — the
"gated" ones.  The mask is the *PMP's* write mask: **the AP cannot write
this bank** (boot #58: every write read back unchanged).

**Boot #49's other findings:** `pmgr0+0x70000` and `pmgr0+0xa0000` are both
**DVFS/voltage tables** (0x4605 = 17925 µV etc.), not rail registers;
`pmgr1+0x80000` has entries only up to +0x140 and is **not** indexed by
device id.

---

## 7. The firmware's own view

* **IO map** (A11 `g10p.img` at 0x3759c, A10 `gfx-t8010-const.bin` at
  0x35565): the A11 sees `0x04d20000` size 0x20000 and `0x04000000` size
  0x200000; the A10 sees `0x01d20000` size 0x20000 and `0x01000000` size
  0x100000.  The same table in the *kernelcache* is at
  `__PRELINK_TEXT` 0xfffffff005069f44.
* **AGX hwdata** (the host→firmware configuration), 53 entries of
  {firmware address, mask, buffer offset}, including the timebase pair
  0x808/0x80c and the A10-pair 0xc30/0xc34.
* the firmware's **init handler** (the 0x81 message) is at img 0x19318; the
  init page is 0x98 bytes with X/T at +0x18/+0x1c.

---

## 8. The open leads, ranked

### 8.1 THE gate call goes to endpoint 32, not to management (the big one)

`GPU-WIP/probe/phase2.2/PMP-FUNCTION-CALL.md` (written earlier in this
session, still the best document in the repo) has it, and boot #57
confirms it:

* the PMP advertises **endpoint 32** — `RTKit: received endpoint bitmap
  0x1 with base 0x1 (last)` → endpoint 32, i.e. `PMPEndpoint1`, the first
  *application* endpoint.  **Our driver never starts it**: `rtkit.c`'s
  EPMAP handler only starts endpoints 0..8 (mgmt, crashlog, syslog,
  debug, ioreport, oslog), and the RTKit layer refuses to send on an
  unstarted endpoint.
* the ADT's `/arm-io` node carries `function-clock_gate = 30:clkG()` and
  `function-power_gate = 30:pwrG()` — **provider 0x30**, the clock/power
  gate provider, with **no arguments** (the device id comes from the
  caller).  Other examples in the ADT show the same shape:
  `30:TCLK(8, 100, 32768)`, `30:ARST(70)`, `30:Wait(126, 0, 0)`,
  `75:pKW4('rBK3', 0x5020000)`.
* the ApplePMGR kext has the matching classes —
  `ApplePMGRFunctionClockGate` (vtable 0xfffffff006c9edb8) and
  `ApplePMGRFunctionPowerGate` (vtable 0xfffffff006c9eef0) — both built
  with provider **0x30**, on top of
  `ApplePMGRFunctionPMPInterrupt` (vtable **0xfffffff006ca0010**, kext slots
  -1, 0 and **+12 = 0xfffffff005674354**), whose
  `_callFunctionPMPv2()` is what turns a `function-<name>` call into a
  message on the PMP v2 interface.
* **So the gate request is an RTKit message to endpoint 32 carrying a
  "call function" payload.**  Everything we have sent so far went to the
  *management* endpoint (0), which is why the PMP only ever echoed it.

**Boot #59 does all three** (committed as `6586463337d4` in the tree):
`apple_t8015_pmp_start_ep(32)`, then the sweep above, then the mailbox.
The v2 message layout is decoded from `ApplePMP::_sendPMCommand`
(ApplePMP.kext at __PRELINK_TEXT 0xfffffff0050e0e00, size 0x1b9b; its
REQUIRE strings name the pm_msg accessors — see the update to §0).  The
ApplePMGRFunction* vtable slots turned out to be OSMetaClass
constructors, not the call function; the real evidence is the send path
itself.

### 8.2 Why the AP cannot ungate anything (explains boot #58)

`PMP-POWER-MODEL.md` §2: the PMGR node has `pmp = 1`,
`pmgr-dock-fifo-agent = 1`, `pmgr-dock-fifo-channel = 3`, and `sgx` sets
`pmp-sw-interrupt = 1` — **the PMGR is an agent of the PMP's dock FIFO, so
the hardware forwards power-state transitions to the PMP.  A PMGR write can
only ever be a *request*.**  The three GPU gates (`GFX-SGX` 148,
`GFX-BUSY` 123, `GFX-KF` 149) are "virtual" (`no_ps`) devices that the
PMP has to move.  That is exactly what boot #58 measured: the AP's writes
to the gate bank were silently dropped.

`PMP-POWER-MODEL.md` §4 also records the PMP firmware's **tunable table**
(file 0x17c68): `DOCK=1 CLKG=1 PWRG=0` — **dock handling and clock gating
are on by default; *power* gating is off by default**, and it is the
AP-side `ApplePMPFirmware` kext (kernelcache strings `pmp-clock-gating` /
`pmp-power-gating` / `pmp-dock-fifo` / `light-em-up`) that can turn it on.
So `pwrG` may be a no-op until that tunable is set, while `clkG` should
work — **try the clock gate first**.

### 8.3 The remaining leads

1. **The ADT's `meta-sw-interrupt` (never tried).**  `/arm-io/sgx` has
   `meta-sw-interrupt = 0x32104020 <- 2, 0x321040a0 <- 2, 0x8` — a software
   interrupt to the GPU's *meta* processor, i.e. **a way to wake the
   coprocessor that does not involve the mailbox at all**.  In the AP's
   space that is `0x233104020` / `0x2331040a0`.  Cheap, safe, untried.
2. **The PMP's `SET_IOP_PWR_STATE` (type 6, never tried).**  The PMP's
   dispatch has type 6 → 0x0100ddde; the driver's
   `apple_rtkit_set_iop_power_state()` sends `(6 << 52) | state` with the
   state in bits 15:0, but that is for the *PMP's own* channel.  Sending
   it with the **GFX IOP's identity** in the payload may be what raises the
   Kingfisher.  (Decode the type-6 handler at 0x0100ddde offline: it shows
   which payload field carries the IOP.)
3. **The PMP's management type-3 handler** is decoded (§5) but the *device*
   field is still unexplained: `device << 12` is used as an address base in
   the PMP's space (its own PMGR descriptor is `base 0x32000000, size
   0xd8000`), so the device may not be the PMGR device id.  We swept the
   device {149, 148, 123, 124}, the gate id 0..255, the command
   {0x03, 0x23, 0x43, 0x83, 0xc3, 0x40000003, 0x80000003} and 21 payloads;
   the reply is an echo, so nothing could be learned from it.
   Note the handler's `ldrb.w r0, [r4, #56]` — **the gate id's low byte
   must be zero** to take the normal path — and the payload's low 5 bits
   select a "gate class" (31 and 16 are special).
4. **The AGX block's +0x1014 = 2.**  One live register we have never
   explained; it may be a state or a revision.
5. **The core window (0x04000000).**  The firmware can reach it, so the
   mailbox may be there — but the RGX's registers trap, so it has to be
   probed one offset at a time.

---

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
  is committed as **`6586463337d4`** (boot #59: the PMP v2 call on
  endpoint 32; before it, `d63057aea2f9` = boot #58).
* The last *booted* payload (boot #58):
  **`00696796dbc95d90f4ecbb4266175da83c4bf242cb6cb2580204bd1900af8ead`**;
  boot #59 is not built yet.
* The kernel log is streamed to `/tmp/opencode/phone-kmsg.log` by
  `GPU-WIP/tools/kmsg-host.py` (pid 412793; do **not** kill it).  Boot #N
  starts at the `GFX-STAGE 0/12` line.  Per-boot extracts are in
  `/tmp/opencode/bootNN.log` (ephemeral — re-extract with the sed in §11).
* A boot counts only when the phone re-enumerates as `05ac:4144`; `RUN_EXIT=0`
  proves nothing (the upload can fail with `LIBUSB_ERROR_OTHER` and still
  exit 0 — check `orchard devices` and the log, not the exit code).
* One boot per explicit go; the phone must be in PongoOS first (after a boot
  it is in Linux and has to be restarted by hand).
* The driver is a *diagnostic* driver: it prints everything it reads, and
  each stage is one experiment.  Read
  `drivers/soc/apple/apple-t8015-gfx.c` before changing it — the comments
  record why each step is there.

---

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

---

## 11. Where the knowledge is

| what | where |
|---|---|
| the boot log of every attempt | `GPU-WIP/probe/STATUS.md` (chronological, with verdicts) |
| the A11 register map we measured | `GPU-WIP/probe/phase2.2/G10P-REGISTERS.md` |
| the GFX bring-up spec | `GPU-WIP/probe/phase2.2/G10P-BRINGUP.md` |
| **the mailbox map and the V4 class (solved)** | `GPU-WIP/probe/phase2.2/A7IOP-MAILBOX.md` |
| the A12 (BadApple/Cascadia) AGX driver as a reference | `GPU-WIP/probe/phase2.2/A12-REFERENCE.md` |
| the offline RE helpers (now in the repo) | `GPU-WIP/tools/` — see `tools/README.md` |
| **the V4 GFX register map (reproducible)** | `GPU-WIP/tools/a7iop-v4-gfx.py` |
| **the PMP disassembly (fixed)** | `GPU-WIP/tools/pmpdis.py` — correct addresses; `pmpdis2.sh` is 12 bytes out |
| the project's own earlier RE (huge) | `Known Good State/firmware/GPU/` — `A11-GPU-FINDINGS.md`, `A11-GPU-G10P-LAYOUT.md`, `A11-GPU-G10P-BOOTCHAIN.md`, `A11-GPU-G10P-STAGE2.md`, the extracted `AGXG10P__*.bin` segments, `agxg10p.asm` |

Re-extracting a boot's log:

```sh
cd /tmp/opencode
L=$(grep -n "GFX-STAGE 0/12" phone-kmsg.log | tail -1 | cut -d: -f1)
sed -n "${L},\$p" phone-kmsg.log | \
  sed 's/^<[0-9]>\[ *\([0-9.]*\)\] /\1 /' > bootNN.log
```

---

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
  probe boot, and remember that the **PMGR's windows are 32 MiB apart**
  (`0x232000000`, `0x235200000`); reading past a window's end takes an
  SError and reboots the phone.
* One boot per explicit "go"; each rebuild needs approval.
