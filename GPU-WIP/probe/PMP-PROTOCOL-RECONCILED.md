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
