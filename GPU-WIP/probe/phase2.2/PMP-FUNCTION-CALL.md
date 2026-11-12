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
