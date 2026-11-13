# How iOS asks the PMP for a gate (the `function-*` -> PMP v2 call path)

Offline findings, 2026-11-12, from the D21 kernelcache, the ADT and the PMP
firmware image.  None of this was booted yet; it is the reason boot #11 has a
concrete thing to send.

## 1. The ADT's `function-` properties are PMP function calls

`/arm-io` carries `function-clock_gate = 30:clkG()` and
`function-power_gate = 30:pwrG()`; `pmgr` carries
`function-pmp_control = 63:PMPC()`; `soc-tuner` carries
`function-mcc_ctrl = 37:Mem$()` and `function-dispidle_ctrl = 125:ADPi()`;
single devices carry their own (`function-power_ldo = 75:pKW4('rBK3',
0x5020000)`, `function-clock_enable = 30:TCLK(0x8, 0x64, 0x8000)`,
`function-spi_cs0 = 36:GPIO(0x8a, 0x1)`, `function-dock_parent = 202:accP()`).

So a device does not get its gates from a register write; it *calls a named
function* (`clkG`, `pwrG`, `TCLK`, `GPIO`, `PMPC`, ...).  The leading number
is the function's provider, and the same provider serves several names
(`30` = `clkG`, `pwrG`, `TCLK`).

## 2. On iOS those calls land on the PMP

The prelinked kext list (`__PRELINK_INFO`) contains:

| kext | class / match | why it matters |
|---|---|---|
| `com.apple.driver.ApplePMP` | `ApplePMPv2`, `ApplePMP`, `ApplePMPThermal`, provider `RTBuddyEndpointService`, match **`PMPEndpoint1`** / `PMPEndpoint2` | the AP-side PMP client |
| `com.apple.driver.AppleT8015PMPFirmware` | match `role = PMP` | loads the image we already boot |
| `com.apple.ApplePMGR` / `com.apple.driver.AppleT8015PMGR` | match `pmgr1,t8015` | the PMGR kext that *uses* the PMP |
| `com.apple.driver.AppleT8015CLPCv3` | `AppleCLPC`, provider `ApplePMGRNub` | DVFS/perf client of the PMGR |
| `com.apple.driver.AppleT8010SOCTuner` | provider `ApplePMGRNub` | the `soc-tuner` device-set client |

and there is a private entitlement **`com.apple.private.pmp.performance-spi`**
— the PMP's performance/gate SPI.

ApplePMGR's own strings name the mechanism outright:

```
void ApplePMGR::_initPMPv2()
IOReturn ApplePMGRFunctionPMPInterrupt::_callFunctionPMPv2(void *, void *, void *)
_provider->_pmpV2()
```

`ApplePMGRFunctionPMPInterrupt::_callFunctionPMPv2()` is at the end of a run
of REQUIRE stubs in ApplePMGR's code (the demangled name is referenced from
`0xfffffff005682a14`, in the kext whose code starts near
`0xfffffff00564b000`).  So: **ApplePMGR turns a `function-<name>` call into a
"call function" message on the PMP v2 interface** — which is an RTKit message
to a PMP *endpoint*.

## 3. Which endpoint: 32

Boot #9/#10's EPMAP from the PMP was

```
RTKit: received endpoint bitmap 0x1f with base 0x0        -> eps 0..4: mgmt, crashlog, syslog, debug, ioreport
RTKit: received endpoint bitmap 0x1 with base 0x1 (last)  -> ep 32
```

Endpoint 32 is the first *application* endpoint (`app_ep_start` is 32 for
RTKit v11+), and `PMPEndpoint1` is the first app endpoint of the PMP — so
that is where a gate call goes.  (Endpoint 33+ would be `PMPEndpoint2`, the
thermal one.)

## 4. What the firmware does with it

The PMP firmware is raw 32-bit ARM (Thumb-2 body), linked at **0x01000000**
(MMU-mapped onto its physical SRAM at 0x232500000).  Its strings
`!clg: %08x` and `Not implemented` are loaded in the same function: the
**clock-gate command handler at VA `0x0100e920`**.

It decodes one 32-bit command word:

```
bits  0..11  value
bits 12..19  8-bit device index      <- fits the ADT device ids (<= 203)
bits 20..21  mode  (selects which field of the target register the index lands in: bit 0, 12 or 20)
bit  22      direction (read/write-ish); bits 22+23 set -> "Not implemented"
```

and builds the register word from those fields (`sbfx/ubfx` to split, `lsl`
to place, then a helper at `0x0100e8e2` assembles it), writes it into a
transaction object (`[r4+0]`, `[r4+8]`, `[r4+12]`, `[r4+16]`, `[r4+52]`,
`[r4+56]`) and performs it.  The `!clg: %08x` string is its debug print on the
error path.

The handler is reached through a **function-pointer table** at
`~0x010119c4..0x01011a2c` (the `0x0100e921` slot is the clg entry; its
siblings are `0x0100db09`, `0x0100dc61`, `0x0100ddd1`, `0x0100e9c1`,
`0x0100ea31`, `0x0100f689`, `0x0100f6f9`, `0x0100f761`, `0x01010675`,
`0x01011b81`).

The same firmware carries a descriptor for the PMGR window it uses itself:
`base 0x32000000, size 0x000d8000` — which *contains* the perf block at
`+0xb4000`, so those DVFS registers are inside the PMGR the PMP touches, and
the D21 DT's `0x8c000` mapping is simply too small (see boot #10's fault).

## 5. What this means for the Linux driver

The gate request is therefore an RTKit message to endpoint 32 carrying a
"call function" payload, and the firmware side of the protocol is a 32-bit
command word with an 8-bit device index.  The GPU's three virtual gates are
`GFX-SGX` 148, `GFX-BUSY` 123, `GFX-KF` 149 (parents: `GFX`), and `sgx` asks
for `clock-gates`/`power-gates` `[148, 123]` (plus `gfx-kf`'s `[149]`).

Two candidate message layouts to try, both cheap to test:

* the *function* form — `(function_id << N) | args`, i.e. what
  `_callFunctionPMPv2` would send for `30:clkG(148)` / `30:pwrG(148)`;
* the *command word* form from §4 — `value | (device << 12) | (mode << 20)`,
  sent as the message body.

Because the PMP's syslog endpoint is started by the RTKit core, the firmware's
`!clg:` / `Not implemented` prints should appear in the Linux log as
`RTKit: syslog message: ...` — so a boot can *ask* and read the answer, with
the IOP mailbox read (`IOP+0x4008`) as the single destructive test at the end.

## 6. The send path, decoded end-to-end (2026-11-13, post boot #64)

Every address below is from the D21 kernelcache (`__PLK_TEXT_EXEC`) unless
marked FW (the PMP firmware, linked at 0x01000000).

### 6.1 The function side (ApplePMGR)

`ApplePMGRFunctionClockGate::callFunction(this, p1, p2, p3)` — body
`0xfffffff005671f0c`:

```
die     = p1[31:28]          (checked against _target->_dieCount at +10852)
device  = p1[27:0]           (28-bit PMGR device id; 149 = GFX-KF)
enable  = p2[0]
arg     = p2[31:1]
        -> 0xfffffff00566c2a8(this->_target(+40), device, enable, arg, die)
```

`0xfffffff00566c2a8` re-checks the die, then schedules the real work:

```
this->[352]->vtable[29](callback = ApplePMGR::_enableDeviceGated,
                        device, enable, arg, die)
```

`_enableDeviceGated(this, device28, enable, arg, die)` — body
`0xfffffff00566c358`:

* the gate STATE is `enable ? 15 : ((arg & 1) << 2)` — **15 = on**,
  0/4 = off, cached at `pmgr + die*640 + device + 0x1abd0` (skipped if
  the cached state already matches);
* parent/dependency gates are enabled first
  (the walker at `0xfffffff00566c8cc`);
* then the state machine at `0xfffffff00565ba68` (counters at
  `pmgr + die*640 + device + 0x19b40/0x1a1d0`) — which ends in the PMP
  send.

`PowerGate::callFunction` is the sibling at `0xfffffff005672024` region;
same shape.

### 6.2 The PMP side (ApplePMP)

`ApplePMP::_sendPMCommand` — body `0xfffffff00610b7a8`, construction at
`0xfffffff00610b868`:

```
msg  = (cmd & 0xf) << 48 | (domain & 0x3f) << 42
     | ((devobj->v128() >> 12) << 16) | (1 << 52)
cmd == 4:  msg |= (payobj->v176() >> 5) & 0xffff      (bits [15:0])
```

* **only cmd 4 and cmd 6 are ever built** (`orr w8, w20, #2; cmp w8, #6`
  guards the whole construction);
* the arg field [41:16] carries the **device id** (v128() = device << 12),
  *not* a (device<<12)+offset address;
* the send is `pmp->[440]->vtable[29](&msg, 0, 1)` — RTKit endpoint 32.
* the AP-side dispatcher feeding it processes actions 0/2/4/6 from a
  command struct `{domain, obj, x}` (tail calls at `0xfffffff00610b1e8`
  .. `0xfffffff00610b2c8`; action 6 → `_sendPMCommand`).

### 6.3 The firmware side (pmp-t8015.bin)

* a **cmd classifier** at FW `0x0100c02c` (and a twin at `0x0100bfa0` for
  a word layout with the nibble at [7:4]): reads a queued message word,
  takes `cmd = word[19:16]` (= v2 message bits [51:48]), and maps
  **cmd 4 → class 1 (its own class)**, cmd 0 → class 2, cmd 15 → (1, 3),
  everything else → class 3 with r0 = cmd.  **cmd 4 is the write/value
  command; the PMP handles it silently (no ack).**
* the transaction object's command word at `obj+64` (= the "+0x40 HW
  command register") is `{enable[0], device[15:8], cmd[19:16]}`
  (read `0x0100cb4a`, written `0x0100cb72`..`0x0100cb94`).

### 6.4 Why boots #53-#64 could not work

* the mgmt type-3 clg sends (boot #57's form) had the type nibble = 3 =
  clg-word mode 3 only — and the handler's registry resolve (8 runtime
  entries) rejects every device id we can name;
* the ep-32 cmd-4 sends (boots #59-#64) were **bare**: no device in the
  (arg>>12) field, no payload — the PMP executed no-ops on device 0;
* cmd 3/5 "acks" are the read/status commands, not the gate path.

### 6.5 The message boot #65 sends

```
msg = (1 << 52) | (4 or 6) << 48 | (domain << 42) | (device << 16) | payload
```

with device ∈ {149, 148, 123, 124}, payload ∈ {0, 1, 4, 15, 0x2000}
(0x2000 = bit 13 of the gate register, set by the firmware when the
payload is 1; 15/0/4 = the PMGR gate states).
