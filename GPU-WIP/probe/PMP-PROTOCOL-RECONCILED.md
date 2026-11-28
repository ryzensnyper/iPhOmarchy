# The PMP protocol, reconciled with iOS (offline, 2026-11-28)

The "contradiction" in the A11 GPU work: iOS's `ApplePMP::_sendPMCommand` only sends
commands 4 and 6, but the PMP firmware's message dispatcher drops every key above 0x10,
so commands 4/6 can never arrive. Both observations are right. They are two
different message types.

All addresses: PMP firmware `pmp-t8015.bin` (md5 `9737473b4846681dc3f292b62ba6df03`,
linked at 0x01000000, Thumb-2) and the iOS 16.7.16 kernelcache
`kernelcache.release.iPhone10,2_5` (20H392). No Apple bytes are reproduced here.

## Endpoint 32 has two receive paths, split by the type field (confirmed)

`0x01012f72`: `0x0100a544(0x20, 0x01002511, ctx)` registers endpoint 32's receive
handler, `0x01002510`. It tests `msg[55:52]`:

| type (`msg[55:52]`) | goes to | handles |
|---|---|---|
| **2** | the type bits are cleared, the message is queued on `pm_work` and dispatched by `0x01003734`: `key = msg[51:44]`, key > 0x10 is dropped | keys 00, 02, 04, 06, 08, 0a, 0c, 0e, 0f, 10 |
| anything else | `0x01010e3c` only wakes the task at `0x01001468`, which pulls the message (`0x0100a7a8(0x20, …)`) and switches on `msg[51:48]` | commands **1, 3, 5** only; everything else is dropped |

The type-1/0 task explains the boot ledger: cmds 1/3/5 ack, 2/4/6 never do.

## What iOS actually sends (confirmed)

`ApplePMPControlFunction` (vtable at `0xfffffff006e98ea0`, call slot 16 =
`0xfffffff00610d1b8`) gates the request dispatcher `0xfffffff00610b140`: a switch on a
request code 0..0x15. The PMGR reaches it through the ADT's `pmgr`
`function-pmp_control = <&iop-pmp-nub> PMPC`.

* Requests **7 / 8** → `_sendPMCommand(4 / 6)` (`0xfffffff00610b7a8`): **type 1**,
  `cmd << 48 | arg << 42 | pfn << 16 | 1 << 52`. The firmware has no handler for type-1
  commands 4/6, so on this PMP these requests do nothing. There is no evidence the A11
  uses them.
* Every other request goes to **one type-2 sender** at `0xfffffff00610b94c`:

  ```
  msg = 1 << 53                      type 2
      | key   (8 bits)  << 44        checked < 0x11 before sending
      | index (4 bits)  << 40        bounded by [pmp + 0xc4]
      | id    (8 bits)  << 32        bounded by [pmp + 0xd8]
      | value (16 bits) << 16
      | size  (16 bits)
  ```

  That is the firmware dispatcher's layout field for field: index = `msg[43:40]`
  (`fp`), value = `msg[31:16]` (`r4`), size = `msg[15:0]` (`r3`).

Request → key, as far as decoded:

| request | key | note |
|---|---|---|
| 0 | 0x00 | two arguments |
| 1 | 0x02 | |
| 0xd | **0x04** | looks up a name in the driver's domain list (`[pmp+0xc8]`, count `[pmp+0xc4]`), sends key 4 with that index and the requested state |
| 0xb | none | returns the cached state `[pmp+0xd0][i]` |
| 0xe, 0xf, 0x10, 0x11 | 0x0e, 0x08, 0x0a, 0x0c | |
| 0xc | 0x0f | |

## What this changes in the ledger

* **Boots #147–#149 tested the wrong path.** Their "key" messages had no type-2 bit
  (e.g. `key 04 msg 0000400000000000`), so the endpoint-32 handler gave them to the
  type-1/0 task, which read them as command 0 and dropped them. #149's "gate word
  forced open, still silent" says nothing about the key-4/6 handlers, because those
  messages never reached them.
* The **gate word** is real: keys 4/6/8/10 exit unless `[0x0101edc0 + 0x28] != 0`.
  It is the PMP's **power state (0..3)**, and key 0x02 sets it (see below).
* **Key 4 is probably performance voting, not a power gate.** It clamps the value to a
  per-domain maximum (`record + 4`, 32-byte records at `[cfg + 0x1c]`, count at
  `[cfg + 0x18]`), stores it in a 48-byte-per-domain table at `0x0101e950`, then
  applies the change (`0x0100483c(1 << index)`). The apply loop runs over 4 domains.
  It looks like DVFS state voting (`_setDVFSStates`), not switching GFX-KF on.
* **Key 0x0c registers something** (allocations, two task registrations through
  `0x01010d48`, a handle lookup through `0x0100432c`; it needs size ≥ 0x20). It is a
  candidate for the setup iOS does before the other keys work.
* **The GPU has a third channel to the PMP:** the ADT `sgx` node carries
  `pmp-sw-interrupt = 1`, `pmp-sync-sw-interrupt = 0` and
  `meta-sw-interrupt = {0x232104020, 0x2321040a0, 8}`. iOS's
  `ApplePMGRFunctionPMPInterrupt::_callFunctionPMP` (v1) is the client.

## The gate word is the PMP power state, set by key 0x02 (confirmed)

Dispatcher jump table (`tbh` at `0x01003786`, key 0..0x10):

| key | handler | | key | handler |
|---|---|---|---|---|
| 00 | `0x37f8` | | 0a | `0x3934` |
| 02 | `0x3808` | | 0c | `0x3972` |
| 04 | `0x382a` | | 0e | `0x37ac` (shared with 08) |
| 06 | `0x38a0` | | 0f | `0x3a76` |
| 08 | `0x37ac` | | 10 | `0x3ada` |
| odd keys 01..0d | `0x3bc6` (dropped) | | | |

* **Key 0x02** (`0x3808`): if `value = msg[31:16]` is < 4, it calls `0x010045b4(&value)`.
  That function runs the transition from the current state `[0x0101edc0+0x28]` to
  the new one, then **stores the new state into the gate word** (`0x0100460a`). Unless
  the new state is 1, it then applies all four domains (`0x0100483c(0xf)`).
  * 0 → 1/2: `0x010046e8` (loop over the domain table, count `[cfg+0x11c]`, calling
    each domain's callbacks), then `0x010047a4` (posts deferred work).
  * 1/2 → 0 or 3: `0x01004614` / `0x01004628` (the reverse loop).
* The only other writer is the internal hook `0x01004418`. On event 0x21 it saves the
  state to `+0x44`, sets it to 0, and later restores it (through `0x01004598`, deferred).
  A sleep/save path, not a setup path.
* **iOS request 1 is key 0x02**: `key 2, index 0, id 0, value = caller's argument,
  size 0`. Key 2 ≤ 0xd, so iOS waits for the reply on slot 0. On the wire, that is

  ```
  0x0020_2000_000V_0000      (V = state 1..3)
  ```

  Which state iOS asks for is not decoded (the caller goes through the PMGR's
  `PMPC` function). 2 is the safe guess: it runs the domain bring-up and the apply.
  1 skips the apply.
* Request 0 is key 0x00 with (value, size) from the caller. Its handler (`0x37f8`)
  stores two bytes (`+2` = value, `+3` = size low byte) in the `0x0101ed40` object
  and replies. It is probably a version/config exchange.

So boots #147–#149 failed twice over: no type bit, and the state was never set,
so the gate word stayed 0 and keys 4/6/8/10 would have exited anyway.

## The ready reply (iOS side, partial)

Gated action `0xfffffff00610eda4` (wrapper `0x…ed7c`) answers the PMP once:
* it requires `[this+0x88] == 1` and that byte `+0x8d` is clear;
* it sends `msg = arg (low 32 bits) | ([this+0xb8] & 0xff) << 56 | 1 << 53`, a
  **type-2** message with a tag in bits 63:56;
* it sets `+0x8d` and wakes the gate.

The old agent's memory-init reply was type 1 (`0x2010…`), which this firmware's
type-0/1 task does accept for commands 1/3/5. It's worth checking that the tag and
type match before the next boot.

`ApplePMP::_powerStateHandlerGated` (`0xfffffff00610b068`) moves the driver state at
`[this+0x88]`: 3 → 2 on wake, → 3 on sleep (checking that no request is waiting on
any of the `[this+0xc4]` slots at `[this+0x180]`). Requests return `0xe00002d7` in state 3.

## The GPU's other PMP channels are not the power path (confirmed)

* **`meta-sw-interrupt` = `{0x232104020, 0x2321040a0, 8}`** decodes to **AIC + 0x4020 / + 0x40a0**,
  the AIC1 SW_SET and SW_CLR words for IRQs 256..287. Bit 3 is **IRQ 259**, the
  second of **gfx-kf**'s interrupts `[260, 259, 262, 261]`. AGX copies the 20 bytes into
  its firmware-init structure (`0xfffffff006b544c0`, `+0x3a00..+0x3a10`). It is a
  doorbell into the Kingfisher for the running GPU firmware, not a way to power it.
* **`pmp-sw-interrupt = 1`** only sets a flag (`+0x8f0 = 1`) in the same GPU firmware config
  (`0xfffffff006b7d6d4`).
* **`ApplePMGRFunctionPMPInterrupt::_callFunctionPMP`** (`0xfffffff005674418`) serves the
  `CIRQ` (cmd 0x11) and `BIRQ` (cmd 0x10) functions. It maps two PMGR registers for the
  client and posts a PMP dashboard command. The ADT's only users are
  `BIRQ` bandwidth-request interrupts (display/ISP); nothing in `sgx` or `gfx-kf` uses it.

So iOS powers the Kingfisher through the ordinary PMGR power-state path, with the
PMP **managing** domains only after key 0x02 has moved it out of state 0.

## Next

1. One boot (on an explicit "ready"), replaying the iOS order with bit 53 set:
   the ready handshake as today, then **key 0x02 value 2**
   (`0x0020200000020000`), reading the reply. Then, if the reply comes, try the GFX-KF
   power-up the normal way and read its PS register. No other new messages.
2. If the reply doesn't come: decode what iOS passes to request 1 (the PMGR's `PMPC`
   callers) and the ready-reply tag `[this+0xb8]`, offline.

## Boot #152 (2026-11-28, kernel 2371d917, debugfs-driven, one ramboot)

Setup: the debug driver defers the firmware load (the D21 has no `apple/pmp-t8015.bin`
in the initramfs or rootfs, so stock boots never start the PMP at all), polls the
slow RTKit handshake (wake -62, forced `SET_AP_PWR_STATE(ON)`, running after 3 s), then
exposes `/sys/kernel/debug/pmp-b/{state,tx32,tx0,startep,wake,gate,sram}`.

| step | sent (ep 32) | PMP reply | effect |
|---|---|---|---|
| ready | (PMP sends `0x0`) | | |
| old memory init | `201000080c1e0000` (type 1, **cmd 0**) | none | dropped; object at `0x1EDC0` stays 0 |
| key 02 before init | `0020200000020000` | none | gate word 0 |
| iOS ready reply | `2010000000000000` | none | |
| **memory init, cmd 1** | **`201100080c1e0000`** | **`0002000000000000`** (ack) | post-init runs: `0x1EDC0 = 01019a18`, cfg `[0x1ed9c] = 010123a8` |
| **key 02 value 2** | **`0020200000020000`** | **`0020300000020000`** (key+1, echo) | **gate word = 2** |
| PS write gates 124, 149 | (PMGR `0x80000+id*8`) | | read back 0 |

* **The memory-init message is cmd 1** (`msg[51:48] = 1`). The type-0/1 task's cmd-1
  case (`0x010014ac`) maps the buffer (`0x0100d814`: lo = `msg[31:0]`, hi = `msg[51:32]`,
  page-aligned, size 0xf000), builds its tables, and acks with
  `send(0x20, 0x0002000000000000)` at `0x010024ba`. The cmd-0 form the old driver sent
  is dropped. #148's ack is unexplained; don't rely on it.
* **Key 02 works** once the init has run: a type-2 reply with key + 1, and the PMP power
  state moves to 2. The gate word is open without any SRAM poke.
* **The gate writes were aimed at nothing.** `0x80000 + id*8` is wrong above ~id 100
  (ids 120..125 all read 0; the DT's gfx state is at `0x80338`, the ADT's `GFX` psidx 7).
  More importantly, the ADT marks **GFX-SGX (id 148), GFX-KF (id 149) and GFX-BUSY (123)
  `no_ps = True`**: they have no power-state register at all. They're virtual
  PMP-managed devices.
* iOS's path for those is `ApplePMGR::_pmpWriteDashBoardSetVirtualDeviceState`
  (`0xfffffff005669eec`): it updates a per-domain bitmask (24-byte records at `[ctx+0x28]`,
  bit = device byte +1, word chosen by device type 0x21..0x25), packs six "highest set
  bit" nibbles plus bit 61 into a 64-bit value, and writes it with `0x…f9b44` into an
  8-byte **dashboard slot at `+0x10000 + slot*8`** of a mapped block.

Next (offline, phone kept booted in this state): which block holds the dashboard,
the GFX-KF slot and bit, and whether a doorbell follows the write. Then write it from
this same boot.

### Dashboard decode (offline + live reads, same boot)

* `0x…f9b44(ctx, desc, slot, value)` → `0x…e3700(pmgr, region 8, 0x10000 + slot*8, value)`:
  an 8-byte store into PMGR **logical region 8**.
* The PMGR region template (`__PLK_DATA_CONST` `0xfffffff006c9cde8`, 0x56 × 0x50 bytes, name pointer
  at +0) names region 8 **`PTS_PTD`** and region 7 **`PMP_EXT_SW_GEN`** (the latter is what
  `_callFunctionPMP` uses, at offset `0xb8000 + idx*4 - 0x74`). The generic mapper only maps
  regions 0..2 to ADT reg 0..2 (PMGR `0x232000000`, MINI `0x235200000`, SOC_EAST `0x208e20000`);
  the T8015 subclass maps the rest through a virtual call not yet found.
* The PMP firmware declares 16 AP windows (`{u64 addr, u64 size}` descriptors). The only one
  big enough for slots is **`0x232068000`, size 0x8000**, i.e. `PTS_PTD = 0x232058000` if it is
  the dashboard. Its descriptor (`0x01016c90`) goes into the firmware object `0x0101e5b8` (`+0x14`),
  part of the post-init config chain.
* Live read of `0x232068000` (`/dev/mem`, `STRICT_DEVMEM` off): slot 0 = `0x0ddd`, slots 1..5 = 0,
  then 8-byte words with bit-61-style high nibbles (`66866666_66666661`, `08080000_31066666`, …).
  Not confirmed as the dashboard.

Open: (a) the GFX-KF slot and bit (`0x…da0b4` device record bytes +1..+3 and the per-device
slot table at `ctx + 0x36154`), (b) whether the PMP reads the window on its own or needs a
doorbell (`PMP_EXT_SW_GEN`).

### The dashboard is a PMP-v2 path; on the A11 the GPU's parent is a plain PMGR power state

* `SetVirtualDeviceState`'s tables (`ctx+0x3594c` record index, `ctx+0x36154` slot) are filled by
  `ApplePMGR::_initPMPv2` from the `soc-device` / `ptd-ranges` properties (124-byte entries).
  The D21 ADT has neither: **the dashboard is PMP v2 only** and isn't how an A11 powers GFX-KF.
* GFX-KF's raw ADT `devices` record: `10 00 00 95 7c …` (flags 0x10 = `no_ps`, id 149, parent
  0x7c = 124). Its parent **GFX (124) has a real power state: psidx 7, the DT's `ps_gfx` at
  PMGR `0x80338`**, live value `0x0f000300` (off; genpd `gfx` off-0, no consumer). Every earlier
  attempt wrote `0x80000 + 124*8 = 0x803e0`, an empty register.
* After the cmd-1 memory init the PMP fills the shared buffer (`+0x4000`): rails `SOC`
  (VMIN 0x99, VNOM 0xea) and `DCS` (VMIN 0x80, VNOM 0xc4, VMAX 0x13e), then 11 clients
  `CPU ECPU PCPU GPU ISP DISP VENC VDEC JPEG MSR SEP` (24-byte records).
* The firmware's matching 11-entry device table (`cfg 0x0101e5b8`, count `+0x11c` = 11, 80-byte
  records at `0x01012418`, handle at +0xa): CPU/ECPU/PCPU types 1..3, **GPU type 4, handle 0**,
  then ISP 24, DISP 28, VENC 27, VDEC 176, JPEG 144, MSR 25, SEP 127 (PMGR device ids).
  * Keys 0x08/0x0e act on a client by handle (`0x0100432c`); handle 0 is "not found", so the GPU
    client isn't AP-addressable. Its DVFS vote must come from the GPU firmware (the
    `pmp-sw-interrupt` / `meta-sw-interrupt` doorbells).
  * Key 0x04 votes on the 2 rails (descriptor `0x01016c90`: count 2, records `0x01016c50`), not GPU.
  * Type-1 cmd 3 = read a value by handle (replies cmd 4); cmd 5 = ping (replies cmd 6).

Proposed next test (same boot, needs a go): turn **`ps_gfx` (`0x80338`)** on the normal way
(target 0xf), read it back, then read the GFX-KF ASC at `0x204d20000` (CPU_CONTROL +0x44) and
the AGX block at `0x204d00000`. GFX-KF has no state register of its own; if it's powered with its
parent, the ASC becomes readable and its firmware can be booted with RTKit.

### ps_gfx test (same boot #152)

* `ps_gfx` (`0x80338`): `0x0f000300` → write `0x1f00000f` → **`0x1f0003ff` (target and actual 0xf, ON)**.
  First time the GFX parent domain has been powered. No SError, no oops.
* After it: the GFX-KF ASC reads (`0x204d20040`: `00030000 00000000 00000079`, `+0x8000 = 0x79`), the
  AGX block reads (`0x204d04008 = 0x00010704`). But the G10P mailbox is still dark
  (`0x204d00110/114/800/830` all 0), as in #47..#58. The PMP sent nothing and its SRAM didn't change.
* So the parent alone isn't enough. The children (SGX 148, KF 149, BUSY 123) still need something:
  clock gate 149 / `clock-ids [265]`, a reset release, or the PMP acting on them.

## Re-reading the GFX-KF start against the working A10 driver (offline, 11-28)

Orchard's `pvr_apple_t8010.c` boots this firmware family on the A10 with **one** power domain
(`ps_gfx`) and no PMP at all:

1. `ps_gfx` on (genpd);
2. the firmware window, written twice: Fender `+0x200c` (4-byte stride) and IOP `+0x08` (8-byte
   stride) = `{pa_lo, pa_hi, 0, 0, size, 0}`, then IOP `+0x38 = 1`;
3. `FENDER_RUN` (Fender `+0x2048`) bit 0;
4. RTKit boot over the gfx-kf mailbox, then endpoints 0x20/0x21, then the Fender power state
   (`+0x1000`, request 0x10 | state, poll the low 5 bits).

What the old A11 driver (`GPU-WIP/probe/gfx_iop_t8015.c`) actually did:
* the window's AP address was never written (`/* writel((uintptr_t)??, … AP_LO) */`), so the
  window pointed at 0;
* the start was `fender + 0x2048` (marked GUESS), with `ps_gfx` never on (it wrote `0x803e0`);
* it polled the mailbox at `0x204d00110/114` (generic ASC offsets, in the Fender block).

A11 differences, from the ADT and the other T8015 IOPs:
* gfx-kf's IOP block (`0x204d20000`, 0x20000) is a T8015 ASC like PMP/AOP/SMC/ANS. Their mailboxes are
  all at **block + 0x8000** with the T8015 layout (`apple,t8015-asc-mailbox`: control
  `+0x108`/`+0x10c`, send `+0x800`, recv `+0x830`), so **gfx-kf's mailbox should be `0x204d28000`**,
  with interrupts `[260, 259, 262, 261]` (the same order as the PMP's).
* On AOP the same remap fields (`+0x08` PA, `+0x18` IOVA, `+0x28` size, `+0x38` enable) are
  followed by **CPU_CONTROL `+0x44` bit 4 (RUN)**. GFX-KF `+0x44` read 0 after `ps_gfx` came on,
  i.e. powered and not started. On the A11 the start is either `FENDER_RUN` or the ASC RUN bit; try
  `FENDER_RUN` first (as on A10) and check `+0x44`.
* Firmware: image `gfx-t8015-const.bin[9 : 9+0x5d320]`, runtime 0x8f000 zero-padded, 16 KiB
  aligned, at IOP address 0 (KB `A11-GPU-G10P-LAYOUT.md`).

So the PMP is probably not on the GPU's boot path at all (it does DVFS through the GPU firmware's
doorbells later). The cmd-1 / key-02 findings still matter for a working PMP, but GFX-KF should
boot like the A10's.

Next test (needs a go). First, reads only, in the current boot: `0x204d28108/0x10c` (mailbox
control), Fender `+0x1000` and `+0x2048`, IOP `+0x08..+0x44`. Then one ramboot with a debug
kernel: a gfx-kf `t8015-asc-mailbox` node at `0x204d28000` and a probe that runs the A10
sequence with a real window address, exposed through debugfs like the PMP one.

## GFX-KF boots: RTKit up on the A11 (same boot #152, 11-28)

Userspace driver over `/dev/mem` (local debug tool `gfxkf.py`, kept in `~/iPhone 8 Plus Workings/gpu-gfxkf/`;
the window is a 2 MiB hugetlbfs page, PA from `/proc/self/pagemap`, caches cleaned with EL0 `dc civac`).
Firmware `gfx-t8015.bin` (0x5d320, the `__const+9` image) in RAM only.

**Working sequence (the A10's, plus a domain reset):**
1. `ps_gfx` (PMGR `0x80338`) on; then a **reset pulse**: `DEV_DISABLE` (bit 10), `RESET` (bit 31), 2 ms,
   release in reverse (never write back the W1C bits 8–9). `1f0000ff → 9f0004ff → 1f0000ff`.
2. Firmware at window offset 0, zeroed to the end; window = `{pa_lo, pa_hi, 0, 0, 0x100000, 0}` in
   **both** Fender `+0x200c` (4-byte stride) and IOP `0x204d20000 + 0x08` (8-byte stride), IOP `+0x38 = 1`.
3. **`FENDER_RUN`** (Fender `0x204d02048` bit 0). The firmware answers at once:

| RX | meaning | TX |
|---|---|---|
| `00100000000c000c` | HELLO v12 | `00200000000c000c` |
| `0080000000000003` | EPMAP base 0: ep 0, 1 | `0080000000000001` |
| `0088000100000003` | EPMAP base 1 (last): ep 0x20, 0x21 | `0088000100000000` + STARTEP 1 |
| `0010200000000000` (ep1) | crashlog buffer 0x2000 | `001020000008f000` (window + 0x8f000) |
| `0070000000000020` | IOP power ACK ON | `00b0000000000020` → ACK `00b…20` |

   Then STARTEP 0x20 / 0x21 were accepted (no reply, no crash). The firmware now waits for the
   init message on ep 0x20 (A10: `0x81 << 48 | init page PA`).

* **Mailbox:** `0x204d28000`, the T8015 ASC layout (control `+0x108`/`+0x10c`, send `+0x800/808`,
  recv `+0x830/838`). `+0x4000` mirrors it.
* **Fender power** (`+0x1000`, request `0x10 | state`) works from the AP: state 1 at the first poll.
  The reset pulse returns it to 0.
* **No PMP involvement** in the boot: the gfx-kf IOP and the GPU are under `ps_gfx` only.

**What failed first, and why:** the ASC `CPU_CONTROL` RUN bit (`+0x44` bit 4) without a reset does start
the core, but it stalls in early init (no HELLO, only IRQs 69/71 unmasked). `FENDER_RUN` is the real start.
**Don't read IOP `+0x81c` from the AP:** it's the IOP's own AIC event register, and a read acknowledges an event.

**Next:**
1. The G10P init layout (KB `A11-GPU-G10P-LAYOUT.md`: it's a different build, so A10 offsets don't
   carry over). Then send `0x81 << 48 | init`.
2. In the kernel: an `apple,t8015-gpu` variant of `pvr_apple_t8010` with `reg-names` rgx `0x204000000`,
   fender `0x204d00000`, iop `0x204d20000`; a `t8015-asc-mailbox` at `0x204d28000` (IRQs 260, 259, 262, 261);
   `ps_gfx` plus a reset before the boot.

## Init message prep (offline, 11-28)

The G10P layout re-author from 11-06 (`~/linux`, commit `bbdbdb19353e` on `gpu/phase2.1`/`gpu/phase2.2`:
`pvr_apple_layout.c/.h`, compile-validated only) builds unchanged as a host program
(`build.c` with a 3-header shim). It writes the init page at window `0x98000` and the descriptor at
`0x9c000`, clear of the image/BSS (`<0x8f000`) and the RTKit crashlog buffer (`0x8f000`).

**Bug in that commit:** `FENDER_PA 0x04d00000` / `RGX_PA 0x04000000` are the ADT's arm-io-relative
values. The IO table needs full PAs (`0x204d00000`, `0x204000000`): the A10 file uses `0x201d00000`,
and the G10P firmware's own page table maps the full PA `0x232108000`. Fixed in the userspace copy;
the kernel commit still needs it.

Test plan (needs a go, same boot):
1. `gfxinit.py alloc`: a 4 MiB heap in one 32 MiB huge page, and a zeroed GPU-root page at
   window-page + 1 MiB.
2. Run `build WIN_PA HEAP_PA ROOT` on the host and copy the two images over.
3. `gfxinit.py init`:
   * check the window region is empty, load it, then Fender power 1;
   * send `0x81 << 48 | (win_pa + 0x98000)` on ep 0x20;
   * serve RTKit (crashlog included), poll `T+0xb188` (heap `0x14188`), then list every heap word
     the firmware changed.

### Init test result (same boot #152, 11-28)

Heap PA `0x850000000` (one 32 MiB huge page), GPU root `0x844700000` (zeroed), images from the host builder
(with the full Fender/RGX PAs). Fender power 1, then `TX ep0x20 0081000844698000`.
* The mailbox took it (A2I drained), and there was no crash and no crashlog.
* **But the init page was never copied**: the firmware's init global `0x8e158` is still zero, `[0x8e420]` /
  `[0x8e424]` are 0, and no heap word changed; `T+0xb188` stayed 0.
* Why: in `main` (`0x1cb42`) the order is: platform init, `cpsie i`, `0x1cd42`, `0x29190`, `0x1cd94`, then
  **create task `agx_background`** (`0x27654`, name `0x30c1f`, priority 0xf; the handle goes to `INIT+0xa0`),
  then `0x19318` (the init handler: `rtk_recv(0x20, …, -1)`, check type 0x81, memcpy 0x98).
  * `INIT+0xa0` was never written.
  * No stack frame returns into `0x1cb75`/`0x1cb85`/`0x19341`.
  * The only live reference to `"agx_background"` is an argument frame (`0x33f14`) deep inside the task create.
  * The create allocates `alloc(4, 0x5c)`, then `alloc(1, 0x150)` (`0x26e8c` → pool `0x26a10` → `0x27d20`).
  * So **`main` is stuck creating `agx_background`**, before it ever waits for the init message. The init
    layout isn't tested yet.
* `0x2f40c` is the firmware's panic (it starts with `cpsid i`). `0x37000` is the firmware's VA region table
  (`{class, start, end}`: 0 `0x200000–0x2000000`, 3 `0x80000000–0x89000000`, 2 `0x89200000–0x8b200000`,
  4 `0x8b400000–0x8c400000`, 5 `0x90000000–0xb0000000`, 1 `0xc0000000–0xe0000000`), followed by the AIC page
  mapping `0x232108000`. VA `0x1f0000` is the page-table self-map (L3 `0x38000` maps itself), not a window
  overrun.

Next (offline): why `alloc(1, 0x150)` / the pool lock at `0x26a10`/`0x27d20` blocks. Candidates: the class
backing for type 1, a lock held by the IRQ path, or a host-provided buffer that never arrived.

### Correction, and the likely cause (offline, 11-28)

**Firmware-RAM dumps are not live state.** The firmware maps its own RAM write-back cacheable (PTE `0x483`,
AttrIndx 0; MAIR0 `0x4ff404ff` gives attr 0 = `0xff`), so a DRAM read shows only what the IOP has evicted.
The "main is stuck creating `agx_background`" reading came from such stale frames and is withdrawn; the
allocator mutex (`0x8e798`) reads free. Trust only host memory the firmware maps uncached (the heap), plus
mailbox traffic.

**IO table at `P+0x640` (kext `0xfffffff006b70c40`):** 24 entries of 0x18 bytes,
`{u64 pa, u32 fw_va (firmware-written), u32 size, u32 size, u32 flag}`, filled from a provider array
(stride 0x98: flag `+0x5a0`, PA `+0x5a8`, size `+0x628`).
* The firmware's mapper `0x1b634` (the code at `0x1bb40..` is part of it) maps each entry with attr
  **`0x21b` when flag ≠ 0** (device) and **`0x209` when flag = 0** (normal memory). It stores the VA at `+0x8`.
* **Entry 0 is host RAM:** fw `0x15cf2` maps `entry0.pa + 0x110000` and does
  `memcpy(that page, fw 0x32000, 0xd58)`. That's the firmware publishing its config, the opposite direction
  to what §4d.5 says. So entry 0 must be RAM larger than 0x111000.
* The 11-06 builder put **Fender in entry 0**, so the firmware wrote its config to **`0x204e10000`** (unknown
  MMIO) right after the init copy. That fits "init consumed, then silence". It also wrote `+0x10 = 0`, where the
  kext writes the size.

Retry (needs a go): entry 0 = `{window PA, 0x200000, flag 0}` (the 2 MiB page; `+0x110000` is free),
`+0x10 = size` in every entry. Do a clean restart first (`fullinit.sh`: PMGR reset, `FENDER_RUN`, handshake,
STARTEP, init). After it, check the heap, `T+0xb188`, and the window page `+0x110000` (the firmware writes
that one cached, so it may lag).

### Retry with the fixed IO table (same boot #152)

Clean restart (PMGR reset, `FENDER_RUN`, handshake, STARTEP 0x20/0x21, all as before), Fender power 1,
`TX ep0x20 0081000844698000`. The outcome was the same as the first try:
* the message was consumed;
* no reply, no crashlog;
* no heap change, `T+0xb188` = 0;
* the window page `+0x110000` is empty.

The heap is mapped uncached by the firmware (attr index 6, Device in the boot MAIR). The IO mapper `0x1b634`,
which `main` runs right after init, would store each VA into `P+0x648…`, and it didn't. So **`main` never
reached `0x1b634`**.

### Offline: where the message goes, cache flush, panic trigger

1. **Routing.** `rtk_recv(handle, &msg, timeout)`: handle = `{table : 16, ep : 16}`, table at `[0x371a4]`.
   `0x28df4(t, ep)` accepts ep `0..0xc` and `0x20..[t+0x10]`, with slot = ep − 0x13 for ep ≥ 0xd, and returns
   `[t+0x18][slot]`. A missing or unready endpoint makes `rtk_recv` return an error, and the init handler
   (`0x19318`) then panics ("Unable to grab init data from host"). There was no panic, so ep 0x20 is
   registered and the message was delivered. Most likely the handler copied the init page (cached, so we
   can't see it) and stalled before `0x1b634`. Its work in that span:
   * map the descriptor page and the heap;
   * map RGX `P+0x688` (attr `0x21b`);
   * `0x15cf2` (entry0 + 0x110000 config copy);
   * then `main`'s `0x1b442`, `0x1c984`, `0x1c0ae`.

   Any RGX/Fender register access with the core in power state 1 is a candidate for the stall.
2. **Cache flush:** the firmware has **no set/way cache maintenance at all**, only 74 by-address cleans (shared
   buffers). A sleep request won't expose its RAM.
3. **Panic trigger:** the management handler (`0x2bd54`, `tbb` on the type) handles type 0xb
   (`SET_AP_PWR_STATE`). If the requested state equals the current one, it **panics with
   `"Invalid AP power: %d"`** (`0x2be1e`). Re-sending the standard `SET_AP_PWR_STATE(ON)` while already ON is a
   deterministic, planned panic. The crashlog format of this RTKit (2062.142.1) isn't decoded yet: no `C…` tags
   were found by constant scan.

### Fender state 2 retry and the planned panic (same boot #152)

* The ADT `sgx` has `gpu-num-perf-states = 2`. A clean restart with **Fender power 2** before init (reached at the
  first poll) then the 0x81 init gave the same result: consumed, then silence, no heap change.
* Then the planned panic, `TX ep0 00b0000000000020` (AP power ON while already ON). There was **no panic and no
  reply**, and A2I stayed `00109a01` (not empty) for good.
* So the **coprocessor stops servicing its mailbox after the 0x81 init**. Before init every management message was
  consumed (STARTEP drained A2I). The IOP is hung or spinning with interrupts off inside the init path,
  before the IO mapper (`0x1b634`).
* What runs in that span: the init copy, `map(desc page win+0x9c000)`, `map(heap 0x850000000, 4 MiB, 0x41b)`,
  `map(RGX P+0x688, 0x21b)`, `0x15cf2` (`map(entry0 + 0x110000)` and the 0xd58 copy), `main`'s
  `0x1b442`/`0x1c984`/`0x1c0ae`. A bus stall from an access the fabric doesn't complete fits best.
* Candidates, next offline:
  * an **RGX register access** (the ID/config reads) while the core isn't really up (the AP itself hangs
    reading Fender with the domain off, PROBE §8);
  * an IOP access to **DRAM outside its reachable range** (heap at `0x850000000`, while the window
    `0x844600000` is known to work);
  * an IOP-side MMU fault with no handler.

### Root cause and the first successful init (same boot #152)

**The cause was the heap descriptor's firmware VA.** `FW_VA_HEAP 0x100000` came over from the A10 layout (the KB
marked it "firmware-build specific, must be re-derived"). On G10P a 4 MiB mapping there covers the page-table
self-map at `0x1f0000` and the start of the firmware's own class-0 allocation range (`0x200000–0x2000000`). The
L3 page writer (`0x25f64`, granule 12) overwrites a PTE **without an already-mapped check**, so the init handler's
descriptor loop (`0x1943a`, IRQs off) replaced live firmware mappings and the IOP hung for good: no panic, no
crashlog, mailbox no longer serviced.

Supporting facts:
* The panic path (`0x2f40c` → `0x2db1c`) does report: it writes an `EHLC` record into the ep1 crashlog buffer,
  mapped uncached (attr `0x202` → `0x401b`), and sends the AP `ep1 0x001010000008f000`. It returns silently only
  without a crashlog buffer or nested five deep. So the earlier silence was a real hang.
* The mapper's legal VAs: TTBR0 `0 .. 0x2000000` (class 0 owns `0x200000+`) and TTBR1 `0x80000000+`.
  Moving the heap to `0x10000000` gave a clean, logged panic:
  `Unable to map VA_10000000 to PA_850000000 num_pages:1024 $:0, status:0x8000000B`.
  * Call stack `0x19964 ← 0x1cb80 ← 0x2575e`.
  * Crashlog sections, tags byte-reversed in memory: `Cstr Cver Ctim CrgA Ccst Cmbx Cktr`.
* Free TTBR1 gaps between the classes:
  * `0x89000000` (2 MiB), `0x8b200000` (2 MiB);
  * `0x8c400000–0x90000000`;
  * `0xb0000000–0xc0000000`.

**With `FW_VA_HEAP 0xb0000000`** (otherwise the run2 images: fixed IO table, Fender power 2): `TX ep0x20
0081000844698000` → **`T+0xb188 == 1` within 2 ms**, no panic, A2I drains.
* The IO mapper wrote the VAs: `P+0x648 = 0xc2200000`, `P+0x678 = 0xc2041000`, `P+0x6c0 = 0xc2001000`,
  `P+0x6d8 = 0xc2000000` (low bits `0xc2` = flags).
* Also changed: heap `0x2f010 = 4`, `0x35000 = 1`.
* `0x15cf2` copied its config to window+0x110000 (62 non-zero bytes).

Kernel commit `bbdbdb19353e` needs, besides the earlier PA, entry 0 and `+0x10` fixes, **`FW_VA_HEAP` in a TTBR1 gap**
(`0xb0000000` tested) and the same for `FW_VA_HEAP2` if used.

### After ready: the doorbell path (offline, 11-28)

* `main` registers the ep 0x21 callback `0x1d812` (`0x291e0(0x21, 0x1d813, 0)`, stored at the endpoint's
  `+0x28/+0x2c`). ep 0x21 is never read with `rtk_recv`.
* The callback switches on `(hi >> 16) & 0x3f`:
  * **3 = kick.** `lo & 3` sets pending bit 0–2 in the 64-bit word `0x8e1f0`; `lo & 3 == 3` is ignored.
    `(lo >> 2) & 7` (≠ 4) bumps a counter byte at `0x69128+n`.
  * **4** sets bit 31 of the same word.
  * **5** matches `(lo, hi & 0xfff)` against the mapping-ring control PA, then sets `scheduler+4 = 1` and bit 1
    of `0x8e2b8`.
  * **Anything else** panics: "Unknown msg type!".
  * So the driver's `0x83 << 48` (lo 0) is a valid kick of class 0.
* The background loop (`0x1d8f8`):
  * sets bits 0–2 once at start, then on each wake swaps the word to 0 and drains the mapping ring (`0x1999c`);
  * dispatches through the table at `0x2fc4c`, 10 × `{mask lo, mask hi, fn, a0, a1}`;
  * bits 0/1/2 → `0x210a0(0/1/2)`, the host-ring scheduler; bits 24–29 → `0x1e4c2`/`0x1eca8` (internal
    events), bit 30 → `0x1f4be`.
* `0x210a0` calls `0x1c290` (the GPU page-table-root consumer), then reads the `+0x20` index of every ring object
  through X (`[0x8e420]`).
* The init's firmware writes: `HEAP_POWER_ENGINE+0x10 = 4`, `HEAP_FW_CONFIG+0 = 1`.

Next device step (planned, not run): one **null kick** on the initialised firmware, `TX ep0x21
0083000000000000`, with no job queued. Expect: no panic, A2I drains, and heap changes only from the scheduler pass.

### First doorbell kick (same boot #152)

* With the run4 images, the null kick `TX ep0x21 0083000000000000` **faulted** 2 ms later. The crashlog had no
  panic string; `CrgA` showed pc `0x19af2`, lr `0x1c59d`, a NULL load. The scheduler's GPU-MMU setup (`0x19abe`,
  called from `0x1c598`) reads **`T+0x914c`**: `{u32 fw VA of a u64 root-PA array, u32 masks[3]}`.
  * For context 0 and each masked context it writes the index to RGX `+0x17030` and the root PFN to `+0x17038`.
  * Other users: `0x1a01e`/`0x1a0cc` map `root[c]` (one 4K page) and `0x21a6e`. All of them only read it, so the
    host must fill it.
* Fix: `HEAP_MMU_CTX 0x88000`, holding `root[0] = gpu_root`, and `T+0x914c = fw_va(HEAP_MMU_CTX)`.
  Kernel `gpu/phase2.2` commit "Give the A11 G10P firmware its GPU context roots", local.
* Clean restart, init (READY in 2 ms), then the same null kick: **taken without a fault**, A2I drains. The
  scheduler ran the power-up path:
  * X power-state struct (`X+0x69a8`): `+0x4 = 1`, `+0x1c = 0xabcdabcd`;
  * `T+0xb1bc` 1 → 0;
  * `HEAP_POWER_ENGINE`: `+0x38 = 1`, `+0x40b4 = 1`, `+0x40d8 = +0x4100 = 0x37ba732b` (looks like a timestamp),
    `+0x4190 = 1`.

Next: a real job (compute first). The driver's `pvr_apple_layout_write_compute_job()` path through the ring producer,
then a kick, on a GPU VM whose root page maps the job's buffers.

## Boot #153: the kernel driver boots the G10P firmware (11-28)

Kernel: local branch `gpu/t8015-g10p` on OrchardLinux/linux `6e58c497`, commits
`f2374c12a556` ("drm/imagination: Boot the A11 (T8015) G10P GFX firmware") and `4d3180815bbd` ("arm64: dts:
apple: t8015: Add the GPU"), payload `d21-desktop-main`.
* The new T8015 chip in the shared Apple driver boots like the A10, after a PMGR reset of `ps_gfx` (reset
  controller).
* The G10P layout is `pvr_apple_g10p_layout.c`; a host build of it is byte-identical to the images tested from
  userspace.
* No jobs: its events and mmu_flush hooks do nothing.

Result:
* At boot, powervr autoloaded and failed cleanly: `apple/gfx-t8015.bin` not found, no hardware touched.
* Firmware pushed to `/run/gfxfw/apple/`, `firmware_class.path=/run/gfxfw`, `modprobe powervr exp_hw_support=1`:
  `RTKit: Initializing (protocol version 12)` → `GFX firmware initialized (window 0x80a400000, heap 0x80a800000)` →
  `[drm] Initialized powervr 1.0.0 for 204000000.gpu on minor 1`, `/dev/dri/renderD128`. No oops.
* RGX ID registers with the core on (Fender 2, run 1): `CORE_ID (+0x18) = 0x7e1`; `PBVNC`/`CORE_REVISION`
  (`+0x20`) = 0, and nothing else non-zero in `+0x00..0xff`. So powervr reads an all-zero BVNC ("unknown hardware").
  The chip needs its own `read_gpu_id`, or the ID from another source.
* To do: debugfs `apple_jobs` "done" reads heap word 0 (`0xb0000000`, i.e. X+0) because this chip leaves the stamp
  offsets at 0. Cosmetic until G10P stamps are mapped.

## Boot #153, continued: read_gpu_id and the first compute job (11-28)

* `035ab29bb167` read_gpu_id: CORE_ID must be `0x7e1`; reports driver-assigned BVNC 14.10.6.2 (listed supported).
  Reloaded on #153: loads without `exp_hw_support`, no "unknown hardware".
* `6e6d617ae9cd` compute hooks (G10P writer, stamps, ring-2 producer, 16 slots); `prepare_job` refuses non-compute
  jobs and any job needing a VM switch (G10P root update/TLB generation unknown; `switch_vm` would add 0x400000 to
  heap word 0 = X+0). `90ef92156ee4` DEBUG: debugfs `apple_null_compute` (kernel VM, stream `0x200000` =
  terminate-only, ctx state `0x201800`).
* The phone had idle-suspended (omarchy-powerd, s2idle); systemd IS present, `/bin/systemctl` just not on SSH PATH.
  Masked `sleep.target suspend.target` (runtime).
* Null job: runtime PM had powered the GPU off; the trigger restarted the firmware through the driver (restart path
  works). Ring 2 consumer/sync/producer 0 → 1, `T+0xb1bc` 1 → 0 (power-up), **no stamp in 2 s** (-ETIMEDOUT), no
  fault, no crashlog.
* Heap after: work entry `{+8 0xb0063000, +c 2, +10 1}`, queue/command/microsequence/CDM args as written, but the
  firmware wrote **nothing** to the queue state (`0x64000`, only the host's `+0x50 = 0x100`), the scheduling pool
  (`0x84000`), the CDM register block (`0x69000`) or the stamps. So it consumed the ring-2 entry without reaching the
  queue. Next (offline): the ring-entry handler (fw `0x21286` → `0x1bdec` and its consumer) to see what it needs from
  the 20-byte record / queue before it dispatches.

### Offline: why the job was dropped (11-28)

* Scheduler `0x210a0`: rings in priority triples (3p geometry, 3p+1 fragment, 3p+2 compute); snapshot each producer,
  flush entries (`0x1bdec(entries, 0x20, 0x100, sync, prod)`), sync = prod, then walk consumer → producer.
* **G10P work entry (32 B, `entries + idx << 5`)**: `+0x00` u32 engine (geometry leg needs 0, fragment 1, compute 2 at
  `0x21752`); `+0x04` queue fw VA; `+0x08` head (→ queue `+0x18`, queue-state `+0x30`); `+0x0c` u8 slot (bit index,
  `0x147de`); `+0x10` flag (zero → requires queue `+0x20` or `+0x38` non-zero). Wrong engine → `0x216c2`: consumer++
  only. **That is what happened**: we wrote the other A10 revision's record (queue +8, engine +0xc, head +0x10), so
  `+0x00` read 0 on the compute ring.
* A10 `g9p.img` (`0x1fc82..0x1fd90`) has the same entry fields with a 20-byte stride. Its queue's run-block pointer is
  `+0x80`/`+0x78`; G10P's is **`+0x84`/`+0x7c`**: the firmware does `*(u8 *)(queue[+0x84] + 2) = 4`, after cleaning
  0x20 B there. Ours was NULL (the inherited pointer sat at +0x88).
* `0x147de(queue, slot, engine)` → `0x14bcc`: queue `+0x00` state (`+0x50` ring size), `+0x04` command ring,
  `+0x10/+0x14/+0x18` read/prev/head. Command `+0x00` type via tbb (0–9): type 0 cleans 0x5b0, 1 0x900, 2 0x630,
  **3 (compute) 0x2c0**, then `0x12582(cmd, u8 cmd[+0x278], cmd[+0x274], queue, 2, idx)`; `cmd[+0x274]` is a token
  whose bits 8–14 index the 128 × 0x2c scheduling pool. Ours = seq, which gives pool index 0 while seq < 256.
* Commit `2d00a8de3d83` "Use the G10P work-ring entry format": entry writer, queue `+0x84` → own zeroed block at
  `HEAP_QUEUE+0x800`; TA/3D moved too (unused).
* Still unverified: the microsequence (`cmd+0x1e8`) and the stamp. The kernel waits on `STAMP+4` (the A10's host
  stamp at `cmd+0x26c`); the microsequence Finalize writes `STAMP+0`. The test script prints both.

### Second null job (boot #153, entry fix `2d00a8de3d83`)

* Entry accepted: ring 2 sync 0 → 1 but consumer stayed 0; **the firmware crashed** (no panic string: CPU exception).
  `CrgA` (2 header words, r0–r12, sp, lr, pc, cpsr): pc `0x19d02`, lr `0x27d2f`, r4 = queue `0xb0063000`,
  r10 = pool `0xb0084000`. Crashlog: Workings `gpu-gfxkf/crashlog-compute1-null-T9148.bin`.
* `0x19cd4(ctx)`: `ldr r9, [[T+0x9148], ctx, lsl #2]`, NULL → fault. Then XORs it with `[X+0x100][ctx]` (the
  firmware's copy); if they differ it invalidates, and `diff >> 22` non-zero means a full flush. **T+0x9148 = per-context
  TLB-generation u32 array (host-provided)**, next to the T+0x914c root-PA array. That is the A10 driver's
  `mmu_gen += 0x400000`.
* `de821bf0665a`: `HEAP_MMU_GEN 0x88800`, `T+0x9148` → it, `layout.mmu_gen` = context 0's word; the
  T8015 no-op mmu_flush is dropped (the generic flush bumps it by 0x400000).
* Other T+0x91xx uses checked: `+0x9140` is NULL-checked (cbz); the 0x9134 uses are byte flags. No other obvious
  unset pointers.

### Third null job (TLB generations `de821bf0665a`)

* Past the scheduler; crash in the compute start: pc `0x6c46`, lr `0x74f1`, r4 = ctx state `0xb006a000`.
  Crashlog: `gpu-gfxkf/crashlog-compute2-null-ctxlist.bin`.
* Op records at `0x2f870` (16 B: `{0xc207, 0x28fd, 0x73e3, 0}` = start for geometry/fragment/compute, …).
  Dispatcher `0x12b2c`: `fn(queue, pool_entry[+8] & ~0x1f = cmd, pool_entry[+0xc], pool_entry)`.
* `0x73e2(queue, cmd)`: type 3 → cleans 0x74 B at `cmd[+0x14]` (ctx state), then
  `0x6bf4(2, queue[+0x08], ctx_state, cmd[+0x284])`: if `ctx[+0x60]` is set, return; else
  `TAILQ_LAST(queue[+0x08])` and insert the ctx (links `ctx+0x64` next / `+0x68` prev), `ctx[+0x60] = 1`.
  **queue +0x08 = TAILQ head {first, last}**, empty = `{NULL, &first}`; ours was 0.
* `60d698e5a898`: each queue gets an empty head at queue page `+0x900`.

### Fourth null job (context lists `60d698e5a898`): no crash, not run

* Ring 2 consumer 1; the firmware stays up; no stamp in 2 s (-ETIMEDOUT), no fault.
* The firmware wrote: queue `+0x10 = +0x14 = +0x18 = 1` (command taken), `+0x50 = 1`, `+0x7c = 1`; run block
  `{+0 0x40000, +4 0x14, +0xc 0x10000}`; queue state `+0x30 = 1`; context list `{ctx, &ctx+0x64}`, ctx `+0x60 = 1`,
  `+0x68 = &head`; **pool entry 0** `{+0 1, +4 0xc00000, +8 cmd | 0x12, +0x18 = +0x1c = useq 0xb0053400}`;
  X power `+0x28 = 1`.
* So the command reached the pool with its microsequence (cmd+0x1e8 read correctly), but the microsequence cursor
  (pool +0x1c) is still at its start: StartCompute never ran. CDM block, unit states (`X+0xe8` array) and stamps are
  untouched. Next (offline): what dispatches a pool entry to the engine (who reads pool +0x1c and the opcode table),
  and what gates it: state 0xc00000 bits, unit mask `queue+0x44`, unit state records, GPU power.

### Offline: the microsequence is wrong for G10P (11-28)

* The interpreter ("SKU commands") is at `0xda4e`: cursor `r4 = pool_entry[+0x1c]`, word `w = [r4]`,
  **opcode = `w & 0x3f`**, `tbh` over 1..0x2c (table `0xda62`). Generic advance `r4 += (w >> 4) & ~7`. Invalid ops
  → `0x10c1a` → panic "Unknown SKU command type %u" (`0x30588`).
* Our A10-derived stream (11 StartCompute, `0x100` WaitIRQ, 12 FinalizeCompute, 2 End) means something else here:
  * **op 11 (`0xdc42`) = 32-bit register poll**: `RGX[w >> 12] & [op+4] == [op+8]`, retried until a yield. Our
    word `11` polls RGX+0 for mask `0xb0069000` / value `0xb0053500`, forever. **That is the "queued, never runs"
    state** of the fourth null job.
  * op 12 = 64-bit poll (two regs, mask/value pairs, 0x10 B);
  * **op 2 is invalid** (panic), as are 0 (our WaitIRQ `0x100`), 18–20 and 40.
* Survey of the handlers (`rgx` = loads the RGX base `[0x8e128]`):
  * 1 and 3 call `0x27e5c`, adv 4;
  * 4–6, 8–10 = RGX register ops, adv 8;
  * 14–17 and 21–23 = memory ops;
  * 24, 25 and 43 call scheduler helpers;
  * 26 and 27 = RGX;
  * 30 and 31 = memory;
  * 32–34, 36, 38, 39, 41, 42 and 44 = large RGX ops with many fields: the engine start/finalize candidates.
  * No `0x480`/`0x498` immediates: register writes go through table offsets.
* Kext: AGXG10P `__TEXT` `0xfffffff00553ca40` (file 0x1104a40), `__TEXT_EXEC` `0xfffffff006b4d000` (file
  0x16105c0), `__DATA_CONST` `0xfffffff006fcb640`. Its only SKU strings are `AGXSKUEncoder::encodeTimeStamp` and
  `SKUBufferAllocator::allocateBlock`, so the encoder is in there but mostly unnamed.
* Next: identify the compute start / wait / finalize / end ops. Options: (a) decode ops 32–44 in the firmware
  (fields → CDM registers, the stamp write); (b) the kext's AGXSKUEncoder methods (xref encodeTimeStamp, then its
  neighbours) for the exact words the kext emits for a compute job.

### Kext (option 2): the compute SKU stream the AGXG10P kext emits (11-28)

Kext disassembly: `AGXG10P__TEXT_EXEC.bin` at `0xfffffff006b4d000` (offsets below are from that base). SKU
encoders append at `stream[+0x68]` (cursor), `stream[+0x5c]` = the stream's GPU address base. Every SKU emit in the
kext (opcode, size): 0x2c/0x30, 0x2b/0x20, **geometry** 0x24/0x74, 0x25/0x48, 0x26/0x48, 0x27/0x34, wait `0x201`;
**compute** 0x29/0x48, 0x2a/0x2c, wait `0x101`; **fragment** 0x22/0x60, 0x23/0x34, wait `0x801`; 0x1f/0x10 (with
flags `0x9000_0000`/`0x1000_0000`); timestamp 0x19/0x20; end `0x4000_0018`/4.

**Compute builder `+0x432e4(this, cmd, ctx, cmd_obj, arg4)`** (C = cmd's GPU VA, from `this->[+0x10]->[+0x440]`
`vtable+0x200` = GPU-address-of):
1. `+0x58930(stream, arg4, cmd[+0x284])` (stream preamble);
2. optional `{0x9000001f, ctx[+0x494], cmd[+0x284], C}` (16 B);
3. **`0x29` (0x48 B)**: `+0x04 C+0x18`, `+0x08 C+0x68`, `+0x0c A = va(dev[+0x2a0])`, `+0x10 B = va(this[+0x90])`,
   `+0x14 cmd[+0x10]`, `+0x18 ctx[+0x58]->vfn0x118()`, `+0x1c ctx[+0x248]->[+4]`, `+0x20 ctx[+0x52c]`,
   `+0x24 cmd[+0x27c]`, `+0x28 ctx[+0x510] != 0`, `+0x2c C+0x1f0`, `+0x30 0`, `+0x34 cmd[+0x284]`, `+0x38 C+0x2bc`,
   `+0x3c` u64 `cmd[+0x4]`, `+0x44 va(ctx[+0x240]) + 0x6c`;
4. timestamp `0x80000019` (start; `+0x58c10`, compute case: cmd `+0x28c..+0x2b4`);
5. `this->vfn0x160()` → `+0x436c4` emits **`0x101`** (wait: opcode 1, `1 << 8`);
6. optional `{0x1000001f, ...}`;
7. timestamp `0x19` (end);
8. **`0x2a` (0x2c B)**: `+0x04 A`, `+0x08 B`, `+0x0c cmd[+0x10]`, `+0x10 C+0x1f0`, `+0x14 0`, `+0x18 cmd[+0x284]`,
   `+0x1c` u64 `cmd[+0x270]`, `+0x24` a stream-relative address (after this op), `+0x28 C+0x2bc`;
9. **end `0x40000018`** (`+0x58b34`): size → `cmd[+0x1ec]` (64-aligned), stream address → `cmd[+0x1e8]`.

So the compute command (type 3, 0x2c0 B) carries the job's state: `+0x1f0` (the CDM register block, since
`+0x1e8/+0x1ec` are useq/size), `+0x18`, `+0x68`, `+0x270`, `+0x27c`, `+0x284`, `+0x2bc`. A = a device-global
buffer, B = the channel's (this+0x90) object, ctx+0x240 the context's. Firmware handlers: op 0x29 = `0xed3a`,
0x2a = `0xee48`, 0x18 = `0x10820` (calls `0x13814`), 0x19 = `0xdd8e`, 0x1f = `0xdfb4`, 1 = `0xdaba`.
Next: what those objects are (A, B, ctx+0x240), and the command fields (the kext's compute-command builder and the
firmware's 0x29/0x2a handlers), then rewrite `write_microsequence()`.

### Kext: the compute-command filler (found, not yet decoded)

* Function at kext `+0x15030..+0x153e4` (prologue `+0x15040`) fills the compute command (x21 = cmd): `+0x1e0`,
  `+0x1f0 = 0`, `+0x1f8/+0x200` (u64), `+0x228/+0x230`, `+0x238/+0x240`, `+0x248/+0x250`, `+0x258`, `+0x264`,
  `+0x268` (u16), `+0x26b` (u8), `+0x26c`, `+0x270`, `+0x27c`, `+0x280`, `+0x284`, `+0x288`, `+0x294`, `+0x298`
  (call results), `+0x2bc = 0`. Next: trace the sources of each store (CDM registers vs. context/stamp addresses),
  then rewrite `write_compute_command()` and `write_microsequence()` for G10P.
* Phone: hung at some point after the 4th null job (boot #153 over); user rebooted it to PongoOS. The next test
  needs a fresh boot on the user's "ready".

### Kext + firmware: the G10P compute job, implemented (`d695e5e6b56f`, 11-29)

* Filler `+0x15040(channel, job)` writes the command at `job[+0x3f8]`: `+0 = 3`; `+4` u64 = global job counter;
  `+0x10 = job[+0x530]`; `+0x14 = va(job[+0x240])` (context state); `+0x1d0/+0x1d8/+0x1e0` = per-unit buffer base,
  stride, flags; `+0x1f0 = 0`; `+0x1f8..+0x264` = `job[+0x410..+0x49c]` registers; `+0x26c`/`+0x270` = per-slot
  stamp addresses in two device buffers (`dev[+0x2080]+[+0x430]`, `dev[+0x2088]+[+0x434]`); `+0x274`/`+0x278` =
  token / slot; `+0x27c = channel[+0x38]`; `+0x284 = job[+0x100]`; `+0x2bc = 0`.
* `+0x43594(this, cmd, job)`: `cmd+0x68 = job[+0x460]`, `cmd+0x70 = job[+0x408]`,
  `cmd+0x78+8i = (job[+0x4a0] + i*job[+0x4a8]) | job[+0x4ac] << 1 | 1` (or 0). `job.copy_from(user)` at
  `+0x15a40`: `job[+0x408] = user[+0x00]` (the encoder/control-stream pointer), `job[+0x460] = user[+0x58]` (16 B).
* Firmware op 0x29 (`0xed3a`):
  * skip if `[C+0x2bc]` is set, or if the u64 seq is not below `[op+0x44]` (= ctx state `+0x6c`, the cancel
    threshold);
  * `RGX+0x10200 = cmd[+0x10] << 8 | x & 0x3f`; `RGX+0x14020 = u64 [C+0x68]`; `RGX+0x14000 = u64 [C+0x70]`;
  * per unit i < `[0x8dbd8]`: `RGX+0x11000 = i`, `RGX+0x118d0 = [C+0x78+8i]`;
  * `[C+0x1f0] != 0` → `0x104e0`; else `RGX+0x10180 = 1` (kick);
  * unit record `A + idx*24`: `+0 = 0`, `+0xc = 1`, `+0x10 = B`. **A = the X+0xe8 unit-state array.**
* Op 0x2a (`0xee48` → `0xf892`): `RGX+0x18030 = 0xf`, poll `RGX+0x18038` bit 0; clear the unit record; save
  `cmd[+0x270]`/`[+0x274]` into the engine state; set doorbell pending bit 2 (`0x8e1f0 |= 4`); call `0x27e5c`.
  Completion therefore goes through the scheduler's retire path, not finalize.
* Implemented: command + stream as above, A = `HEAP_UNIT_STATE_2`, B = `HEAP_UNIT_SHARED`, ctx cancel = ~0,
  stream → `C+0x70`, `C+0x68 = 0`, per-unit 0. Assumptions to check on hardware: `RGX+0x14000` = control stream
  (+0x14020 unknown); the stamp words that retire writes.

### Fifth null job (kext-format command + SKU stream), boot 11-29

Safety setup: `apple_perf_state=1`, SoC watchdog armed at 30 s, battery temperature 28.9 °C before and 29.1 °C after,
powervr unloaded after the job.

* No hang, no firmware fault, no oops. ring2 cons/sync/prod = 1/1/1; queue `+0x10/+0x14/+0x18` = 1.
* Unit record (`X+0xe8`) is all 0 afterwards. StartCompute sets `+0xc = 1`; FinalizeCompute (`0xf892`) clears it.
  So **start → wait 0x101 → finalize all ran**, including finalize's poll of `RGX+0x18038` bit 0.
* Stamps `+0`/`+4` are still 0, and the kernel wait timed out (-110). Finalize passes `{op+0x1c = 0xb0038000,
  op+0x20 = 1}` into the engine state and sets doorbell pending bit 2; **the stamp write is in the retire path
  (`0x27e5c`, or the pending-bit-2 handler), which is not traced yet.**
* `T+0xb1bc` went 1 → 0 during the job. On unload: "GPU did not retire its jobs before removal" (expected).
* Next, offline: trace pending bit 2 / `0x27e5c` to see what retire writes, and where.

### Where the compute stamp is written (offline, 11-29)

* Finalize's `0x8e1f0 |= 4` + `0x27e5c` only wakes the main event loop (`0x1d96a`): its table at `0x2fc4c`
  (`{mask_lo, mask_hi, fn, a0, a1}` × 10) maps bit 2 → `0x210a1(2)`, i.e. reschedule compute. No stamp there.
* Engine state `E = 0x5d540 + engine*0x70` (current engine at `0x5d544`); finalize saves the stamp address in
  `E+0x9c` and the value in `E+0xa0`.
* **End (op 0x18, `0x10820`) writes the stamp:** if `[E + slot*4 + 0xa4] == 0` it calls
  `0x13814(pool_entry, [E+0x9c], [E+0xa0])`, which:
  * checks `(entry - pool_base)/0x2c == [0x5db10 + q*40]` (otherwise it logs "OoO SKU completions where it
    should not be" and returns without writing);
  * bumps the per-queue completion counter, sets the entry state to 3;
  * does `*(u32 *)stamp_addr = value` (`0x1396c`) and sets `0x8e270 |= 8`.
  If `[E + slot*4 + 0xa4] != 0`, End instead defers the completion into the mask at `0x68fa0+0x110` (no stamp).
* Finalize only continues to End if `[X+0xe8 + slot*20 + 0x98] == 0`; ours is 0.
* The fifth job's stamp stayed 0, so one of these branches was taken. Next device step: dump firmware data
  (window PA + VA; image size 0x5d320, so 0x5d540+ is bss) with `gpu-fwstate.py`: E0–E2, `0x5db10`, `0x68fa0`,
  event words.

### Sixth null job + firmware data dump (same boot, module reload, 11-29)

* Same result as the fifth: consumed, no fault/hang/oops, stamp 0. Temperature 30.3 → 30.4 °C, watchdog never fired.
* Window `+0..0x1000` == the firmware file: the image is at `win_pa + VA`.
* **But the bss reads can't be trusted:** `[0x8e420]` (the X pointer the firmware dereferences everywhere) reads 0,
  and so do the event words, qcomp and the masks. Only a few E0–E2 words are non-zero (`0x7f7f7f7f`, 1, 2).
  So firmware bss in the window is either stale (the IOP's write-back D-cache, never cleaned) or not where we
  look. Heap reads are fine (the firmware's queue writes show up). Don't use window bss as evidence.
* Next: observe through the heap instead. The scheduling pool is in the heap (queue `+0xc = 0xb0084000` → heap
  `0x84000`, 128 × 0x2c). `0x13814` sets the pool entry's word 0 to 3 when it completes; End's deferred path copies
  entry `+0x18 → +0x1c`. A dump of heap `0x84000..+0x60` after the job tells the paths apart.

### Why End may not have written the stamp (offline, 11-29, continued)

* Queue registration `0x124de(queue, _, _, slot)` fills `0x5db10 + slot*40`: `+0x10` = the queue, `+0xc` = queue
  `+0xc` (the pool), and the counters start at 0; the queue's `+0x1c` = slot. Our job is pool entry 0 (token 1),
  so the order check in `0x13814` should pass.
* Its failure path, `0x2f40c`, is a **firmware panic** (IRQs off, format, `0x2f3f4(4)`, no return). Fault 0 ⇒ not hit.
* Finalize side checks:
  * unit record `+8 != 1` → `0xf878`: only tests `RGX+0x14040` bit 1, then rejoins `0xf892` (harmless);
  * **`[[X+0xe8] + slot*20 + 0x98] != 0`** → clears it, `0x8e2b8 |= 2`, leaves the interpreter through
    `0xfa68 → 0xfe0e`, so End waits until the job is resumed. We point both the stream's unit array and
    `X+0xe8` at `HEAP_UNIT_STATE_2`. The kext takes the stream's array from `dev[+0x2a0]`, which may differ.
    Not dumped yet (`0x2e098`).
* Remaining candidates: (a) the finalize yield above; (b) End's deferral (`[E + slot*4 + 0xa4] != 0`, firmware
  bss, not readable); (c) the stamp written somewhere else.
* Next run: `gpu-heapstate.py` dumps pool `0x84000` (word 0 = 3 ⇔ `0x13814` ran), units `0x2e000..0x2e200`,
  job 0, stamps, queue and `X+0xc0..0x120`.

### Seventh null job: the stream never starts (11-29)

* Pool entry 0 (heap `0x84000`): `+0 = 1` (queued, not 3 = done), `+4 = 0xc00000` (queue slot 0, bits 22/23 set),
  `+8 = 0xb0053012` (the command | 0x12), `+0x18 = +0x1c = 0xb0053400`: **the cursor is still at the first op.**
* Unit records (`0x2e000..0x2e200`, including the `+0x98` yield words) are all 0: **StartCompute never ran.**
  Correction: the fifth job's zeros meant "never set", not "set, then cleared by finalize".
* X `+0xe0..+0x104` hold their heap pointers. Stamps 0, no fault, 30.6 → 30.7 °C.
* So the job reaches the pool (via the ring loop and the op-record start `0x73e3`, which links the context), but
  nothing dispatches the pool entry to the interpreter `0xda4e`. Next, offline: find what selects a queued pool
  entry for execution (entry state 1 → run), and which condition we don't meet.

### What should dispatch the queued entry: the GPU power gate (offline, 11-29)

* The dispatcher `0xd572..0xd692` calls the interpreter `0xd694(engine 0..3, maskA, maskB)` with runnable masks
  from `0x68fa0` (`+0xc0`, `+0x17c`).
* `0xd694` exits without dispatching (`0x10a52`) unless **`[[X+0xe0] + 0xc]`** is non-zero and not 5. The same
  test appears at `0xd66e`, `0xf26c`, `0x79a0`, `0x112d2` and `0x1daac`. Then it ANDs the per-priority, per-engine
  and global masks, clears `X+0x69b0..+0x69bc` (heap; the "blocked" mask) and picks an entry with `0x144a2`.
* `[X+0xe0]` = our `HEAP_UNIT_STATE_0` (heap `0x2c000`). We never write `+0xc`, so **if the firmware didn't, the
  GPU power state is 0 (off) and nothing is dispatched.** State enum: 0 off; 2 powering on (`0x3bd4`, after
  `RGX+0x146b8 = 1`); 1 on (`0x46fe`, after `RGX+0x14ce0 = 1` is polled); 5 (tested once at `0x1ff12`).
* Power task `0x232fa` waits on `0x8e270`:
  * bit 31 = the power IRQ (`0x1c1fa`, set up at `0x1c1e0` with source `0x10000`): reads `RGX+0x10a08 & [0x327e8]`
    (`0x181ec`) into the request word `0x8e294`;
  * bit 0 → `0x3a80(0, 0, 1)`, power-on;
  * bit 3 → the dispatcher pass `0xd30c`, unless `[0x5d574]`.
* Raisers of bit 0: StartCompute (`0xfa7e`) and the ring loop at `0x22900` (a work entry with queue == 0). The
  kext doesn't write `RGX+0x10axx` from the host.
* **Do not fake the state** (writing 1 to `0x2c00c` from the host): the firmware would touch an unpowered GPU.
* Next run (read-only): `gpu-heapstate.py` now also dumps `0x2c000..+0x100`, `X+0x178` and `X+0x69a8..+0x69c8`.

### Eighth null job: the power gate is closed (11-29)

* `[X+0xe0] + 0xc` (heap `0x2c00c`) = **0 (off) at idle and after the job.** All of `0x2c000..+0x100` is 0, so the
  firmware never ran its power-on (it would write 2, then 1).
* The blocked mask `X+0x69b0..+0x69bc` = 0, not involved. The lock byte at `X+0x178` = 0.
* During the job the firmware wrote `X+0x69ac = 1` and `X+0x69c4 = 0xabcdabcd` (zero at idle): the power struct
  saw some request.
* Pool entry and stream unchanged from the seventh job. 30.4 °C before and after. No oops or fault.
* Next, offline: who writes `X+0x69ac`/`+0x69c4`, and why the firmware's power-on (event bit 0 or the `RGX+0x10a08`
  IRQ) doesn't follow.

### The power-on request: firmware command ring 12 (offline, 11-29)

* The power manager's lazy init `0x1c290` (`P = X+0x69a8`: clear it, `P+4 = 1`, `P+0x1c = 0xabcdabcd`) explains
  the words the eighth job changed. It runs on ring-loop entry when `[0x8e268] & 0x78 == 0`, and from command
  0x10 with `+4 == 0`.
* `X+0x00..0x67` holds 13 ring descriptors; **ring 12 (`X+0x60/+0x64`) is the firmware command ring**. The ring
  loop drains it (`0x219ce`: u8 index `[obj]`, entries `[X+0x64] + i*32`, type = word 0, `tbh` at `0x219fc`
  for types 3..0x26; table decoded).
* **Type 0xe (`0x221b4`):**
  * `+0x14` = index → engine `[0x5d540 + 0xf4 + idx*4]`;
  * `+0x18` = u64 that must equal `[[0x8e154] + 0x10]`, where `0x8e154` = init page `+0x20` (our `HEAP_MAP_CTRL`;
    `+0x10` is 0), otherwise it goes to `0x225e0`;
  * `+0x04` = 0 → `0x22900`: `[X+0xe0] + engine*4 + 0x54 = 3`, then **`0x8e270 |= 1` (power-on event)**;
  * `+0x04 != 0` → TLB generation (`0x19cd4`) + `0x17be0(ctx = +0xc)`, then the same with 2.
* Our driver never posts on ring 12. That's the missing power-on request.
* Commit `a8f8fd3391e4` (WIP, local): `write_power_request()` posts `{0xe, 0...}` on ring 12 before each compute
  job. Unverified. The heap dump adds ring 12's object and first entry.

### Ninth null job (`a8f8fd3391e4`, power request on ring 12), 11-29

* **The firmware consumed the command:** ring 12 cons/sync/prod = 1/1/1, entry 0 = `{0xe, 0...}`.
* **It took the `0x22900` path:** `[X+0xe0] + 0x54 = 3` (engine 0's power request), which also raises
  `0x8e270 |= 1`.
* **But the power state `[X+0xe0] + 0xc` is still 0**; the job stays queued (pool `+0 = 1`, cursor at op 0), stamp 0.
* No fault, no oops, watchdog not fired, 30.7 °C before and after.
* Next, offline: the power task's bit-0 path (`0x236cc` → `0x3a80(0, 0, 1)` → `0x3c20`) and the earlier exits that
  can skip it (`0x233d4`: `[0x8e288] != 0` → `0x237f8`; the `0x8e270` bit-26 checks → `0x23822`).

### Why the power request does nothing: unit records and command 0x15 (offline, 11-29)

* Power-on, request 0 (`0x3a80` → `0x3c20`): walks the bits `k` of the unit mask `[0x5d618]` (if 0, returns).
  For each `k`, record `R = [X+0xe0] + k*20` must have **`R+8 == 1`** and **`R+0xc ∈ {1, 4}`**; then it
  checks the per-engine words `[X+0xe0] + 0x54 + engine*4` and powers the unit.
* So `[X+0xe0] + 0xc`, the dispatch gate, is **record 0's state field.** The firmware only writes `+0xc`
  (`0x3bd4` → 2, `0x46fe` → 1); **`+8` is never written by the firmware, so it's host-initialised** ("unit
  present"). Our records are all 0 ⇒ there is nothing to power, and the gate stays shut.
* **Command 0x15 (`0x2233c`) = power/unit configuration:** entry `+4/+8/+0xc/+0x10` → `X+0xd0/+0xd4/+0xd8/+0xdc`,
  then `0x8070` (programs `RGX+0x10000` from `P+0x18/+0x1c` and a block of `RGX+0x1187x`/`+0x110xx` registers),
  then `RGX+0x10a00 = [0x327e8]` (the power-IRQ enable mask). The path from `X+0xd8` to `0x5d618` isn't found yet.
* Kext: `0x61ee4` is an external stub (IOReporting-style 8-character channel names), **not** the command sender.
  The kext's ring-12 sender and its unit-record initialisation aren't found yet.
* Next: find the kext code that fills the `X+0xe0` records and sends 0x15/0xe (follow the `X` buffer
  allocation, `dev[...]`, and look for `lsl #5` ring writes with a u8 index bump).

### Kext search + a correction: the firmware initialises the unit records itself (11-29)

* **Kext command path:** the ring writer `0x24e7c(this, cmd32, _, &slot)` (ring object `this+0x488`, entries
  `this+0x490`; waits while full, copies 32 bytes, bumps the u8 producer at `+0x20`) has one caller,
  `0x3359c(this, cmd, flags)`. For type 0xe it checks `cmd+0x18 == this[+0x1f0]+0x500` (the mapping generation;
  this confirms the 0xe decode). `0x3359c` is reached only through **vtable slot 0x198** (vtables at kc
  `0x2b96840`, `0x2b97c30`; base implementation `0x24e7c` at `0x2b971b0`+0x198). The **only** slot-0x198 call
  site is `0x51740` (type 5). **iOS never sends 0xe or 0x15 from the host.**
* `0x61ee4` = an external stub with IOReporting-style names, not commands. `AGXFirmwareKextG10PRTBuddy` is only a
  firmware container (code 0x4b4 bytes, `__TEXT` 0x5dc88 ≈ the image).
* Kext X builder (`0x23d8c..`): X = `dev[+0x228]`; `X+0xe0/e4/e8/ec = va(dev[+0x290/298/2a0/2a8])`. The
  StartCompute unit array `dev[+0x2a0]` **is** `X+0xe8`, as in our layout.
* **Correction:** the firmware does write unit records. **`0x23844`** (power task, event bit 27 = `0x8000000`,
  call at `0x23616`) sets `[X+0xe0] + k*20 + 8 = 2` and `+0xc`, and `[X+0xe4] + k*36 + 0x20 = 4`. So the records
  are firmware-managed. The earlier "host must set +8" claim is wrong.
* Bit 27 is raised at `0x5fc0`, inside `0x4794` (a power/scheduler state check: `[X+0xf0]` state, record
  `+8/+0xc`, `X+0xe4` record `+0x20`, `X+0xe8` `+0xc`), which is called from `0x24d6a`/`0x24dde`.
* Next: what drives `0x24d6a`/`0x24dde` (a timer or event), and which condition in `0x4794` keeps it from raising
  bit 27 with our state (all records 0, scheduler `[X+0xf0]` at `HEAP_SCHEDULER`).

### Upstream check (11-29): OrchardLinux/linux main + OrchardLinux/gpu

* linux main (2026-11-28): A8 runs compute and renders; A7 boots (PR #17/#19); A10 (T8010) already supported. No G10P/A11 GPU work upstream.
* Closest relative is the A10 (G9P). Host state it needed beyond ours (OrchardLinux/gpu a10/COMPUTE.md):
  - **P+0x16c0/+0x16c4/+0x16c8 = 1**: "one scheduling unit per engine" (engine unit masks). Our G10P P sets
    nothing in that region except P+0x162c (root). G10P init at fw 0x197c0 copies **P+0x15f8..0x1658** into
    a config block (cfg+0x758..0x7b8). The G10P equivalents of the A10's unit masks are probably here, so
    zero would mean no units, which matches our `[0x5d618] == 0` blocker. Unverified.
  - V+0x45b4 = 1 requests scheduler init (A10 fw 0xd980); Queue+0x44 = 1 (we already set it).
  - A10 run 66: the exact Apple CDM record and PDS program for a first real shader (useful after the null job).
* a8x notes (11-27): the J81's first host command was consumed only once the "governor pins" were in the image.
* Next: trace who reads cfg+0x758..0x7b8 (only cfg+0x794 found so far, at fw 0x8e68) and whether any of them
  feeds the unit mask at 0x5d618 (E-table +0xd8; read at 0x3aae, no direct writer found).

### Engine unit masks found (11-29), commit 8e00d466843a

* fw 0x197c0 copies P into cfg block 0x32000: cfg+0x758 = P+0x15f8 (flags), +0x75c = P+0x15fc,
  **+0x760 = P+0x1600, +0x764 = P+0x1604, +0x768 = P+0x1608**, +0x790 = P+0x1634, ... (an off-by-one in the
  earlier note is corrected here).
* fw 0xcc80 (called from 0x3a04 and 0x1c546) zeroes the engine table 0x5d540 (0x190 bytes, stride 0x70) and sets
  each engine's +0x6c..+0x78 masks to `1 & cfg mask` (engine 0 ← P+0x1604, engine 1 ← P+0x1600,
  engine 2 ← P+0x1608). A flags bit (P+0x15f8 bit 1/0/2) forces the mask to 1 instead.
* E_k+0x68 is the "units waiting for power-on" mask: the power-on loop fw 0x3a80 walks `[0x5d540+0xd8]`
  (engine 1), and the dispatcher only clears bits in it (0xffb2, 0x102b8, ...). With P zero, no engine has
  units, so nothing is ever queued for power-on.
* Kext 0x3086c..0x30b6c fills P: 0x15f8 = 0; 0x15fc = cfg[+0x55c] if non-zero; **0x1600/0x1604 =
  (1<<n0)-1 / (1<<n1)-1 for n = gpucfg[+0x38c/+0x390]; 0x1608 = (1<<n2)-1, n2 = gpucfg[+0x394]**
  (all ones if n > 63); 0x1610 = 0; 0x1634/0x1638 = 0; 0x1628 = 1; 0x1640 = 1; 0x1644 = 1; 0x163c = bit 6 of
  gpucfg[+0x52c]; 0x165c..0x168b = 0xff; 0x168c = 0.
* n0 is also the number of 20-byte unit records (kext 0x38620 walks dev[+0x240] n0 times with stride 0x14;
  0xac18 allocates n0 entries). The counts come from the GPU config object (dev[+0x1f0]), built outside this
  kext; no ADT property matches. Using **1 per engine** (as the A10 does).

### Job 10 (11-29, commit 8e00d466843a): the stamp is written; then a firmware crash on retirement

* With the per-engine unit masks (P+0x1600/4/8 = 1) the null job **runs through: stamp +0 = 1**, pool entry
  state 3, unit state +0x94 = 1, queue +0x1c = ~0. The GPU powered and the microsequence finished.
* Then the firmware crashed: PC 0x6682 in fw 0x65f6 (`ldr r2,[r0]`, r0 = [ctx+0] = 0; r5 = 0xb006a000 = ctx
  state). 0x65f6 is called on retirement (callers 0x345e/0x7dec/0xcbe8) with the queue's context list (Q+8). Per
  entry (0x74 bytes): done if `*[+0] == +8`, or if +0x10/+0x14/+0x18 >= +0xc, or +0x1c != 0; then unlink via
  +0x64/+0x68, clear +0x60, and handle +0x24/+0x38/+0x4c.
* Kext context-state init (0x16e78..0x16ef0): +0 = fw VA of a per-context buffer (x20[+0x150+idx*8]); +4 = a
  sequence number; +8 = 0; +0xc = min(cfg[+0x1900] or [+0x54c], cfg[+0x1908]); +0x10..+0x1b = 0; +0x6c = ~0.
* Fix (commit after 8e00d466843a): ctx+0 = fw VA of a zero word (ctx page +0x100), +4 = 1, +8 = 0.
* Safety: no oops, temperature 29.1 → 29.2 °C, the watchdog never fired, rmmod was clean ("device is crashed"
  on the shutdown message, as expected).

### Job 11 (11-29, commit 786063cf4e0d): FIRST COMPLETED NULL COMPUTE JOB

* `null compute job 1: 0, stamp 1, fault 0`; apple_jobs: submitted 1, done 1, pending 0; stamp +0 = 1, +4 = 1;
  no firmware crash, no oops. rmmod was clean (no "did not retire", no "device is crashed").
* Safety: battery 29.7 °C before and after; the watchdog armed and was disarmed without firing; sleep unmasked
  afterwards.
* What it took after d695e5e6b56f: P+0x1600/4/8 engine unit masks = 1 (8e00d466843a) and ctx-state +0/+4/+8
  (786063cf4e0d). The ring-12 power request (WIP a8f8fd3391e4) is still in the build and may be unnecessary;
  to test, drop it.
