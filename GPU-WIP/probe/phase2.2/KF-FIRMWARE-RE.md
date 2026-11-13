# Kingfisher (G10P) firmware — kernelcache RE session 2026-11-14

Offline session after boot #80 saturated the blind PMP path.  Goal: decode the
AGX kext's power-kick path.  Most of what this session found was *already
established* by the earlier `A11-GPU-G10P-*` RE sessions; this document records
the session's independent re-derivations (which now agree with them), the new
facts, and the exact locations for future work.

## 1. The firmware container — re-derived, matches `A11-GPU-G10P-LAYOUT.md` §0

- `com.apple.AGXFirmwareKextG10PRTBuddy`: load `0xfffffff005032040`, size
  `0x5dc88`.  Its `__TEXT,__const` (file offset `0xbfa99f`, `0x5d329` bytes)
  holds the firmware wrapped in a 9-byte `\0Release\0\6\0\0` header.
- **Loadable image = `__const[9 : 9+0x5d320]`** — regenerated this session as
  `/tmp/opencode/g10p.img` from the kernelcache; extraction tool added:
  `GPU-WIP/tools/kf-img-extract.py` (offsets hard-coded, wrapper asserted).
- Image structure (verified): A32 vector table at 0 — vector0 `0xEA000006`
  (`b 0x20`), then `b .` ×7; ARM reset stub at `0x20`; Thumb-2 body.
- **The boot stub is byte-identical to the PMP firmware's boot stub**
  (`pmp-t8015.bin` @0x68 == `g10p.img` @0x29+... wait — see below): the
  sequence `lsls r3, r2, #3` / `add.w r0, lr, #imm` / `b .` family differs in
  exactly three immediates (PMP 0x78 vs G10P 0x30, and two branch imm values).
  Same container family, same boot stub generator.
  NOTE the G10P stub starts 9 bytes later than a naive alignment suggests —
  `g10p.img[0x29]` == `pmp-t8015.bin[0x68]` (93/96 bytes identical).
- The rest of the image: 382 KB of ARM32/Thumb-2 code + packed u64 string
  constants stored byte-reversed (`IDLE_OFF`, `FAST_DEVICE_POWER_ZONE`,
  `PRFLIMIT`, zone/unit names) — normal for movw/movt-built constants.

## 2. The AGXG10P driver kext (new facts)

- `com.apple.AGXG10P`: load `0xfffffff00553ca40`, size `0xb7a0` (47 KB) — the
  data/strings region (kernelcache file `0x1107400..0x1112ba0`).  Three plist
  persona variants: `AGXAcceleratorG10P_A0`, `AGXAcceleratorG10P_B0`, both
  matching `gpu,t8015`.
- Its strings include the **Fender method-name table**
  (`Fender::isPoweredOffWaitingForKicks()`, `didGPUWakeUp()`,
  `initConfigRAMOffset()`, `incrementConfigRAMOffset()`,
  `terminateConfigRAMSequence()`, `writeConfigRAMCommand32/64()`,
  `readTimerSleepControl()`, ...) and the property names
  **`fenderPhys`, `fenderMap`, `startFender`, `FenderRegs`,
  `gpu-fender-idle-off-delay-ms`**.
- The kext's *code* lives in `__PLK_TEXT_EXEC` (cluster around VA
  `0x6b5abcc..0x6b8d000`, kernelcache file `0x2722000..0x2755000`).  There is
  exactly one direct ADRP+ADD xref to the string
  `AGXArmFirmwareKingfisherV4` (VA `0xfffffff005543765`): a registration call
  at file `0x2754888` — `f(0x7bb72e8, "AGXArmFirmwareKingfisherV4",
  0x7bb7310, 0x1968)` then `[x0] = vtable 0x6fd04a8`.
- All *other* string references (Fender names, property names, the power-kick
  string) resolve through **dyld chained fixups** (LC_DYLD_CHAINED_FIXUPS) —
  no raw pointers, no direct ADRP+ADD — which is why naive xref scans miss
  them.  Future xref work must decode the fixups first.

## 3. Where things stand relative to the bring-up

- The real RTKit MU is the one embedded in the **Fender window**
  (`0x204d00000`, `CPU_CTRL` at +0x110 — what phase 2.2's boots poll);
  `0x204d24000` (IOP+0x4000) is a dead page (established earlier, re-confirmed
  by this session's reading of the driver comments).
- The MU stays dark because **the firmware is not running**.  The firmware
  start path = Fender window copy (`+0x200c`, 4-byte stride) + `FENDER_RUN`
  (`+0x2048`) — the PMP's gate bank[0] (GFX-SGX/KF/BUSY, "no_ps" devices) has
  never moved and is the remaining suspect for the IOP SRAM/clock enable.
- The PMP's dev 149 (GFX-KF) is now registrable and cmd-4-controllable
  (boot #76: gate states ON/OFF move bank[40]; #80: cmd 1 + dev 149 visibly
  processed, power-state slots → 0x20).

## 4. Proposed boot #81 (not yet run)

Merge the two paths for the first time:

1. bare cmds 1/3/5 + registration `(6<<52)|0x00950643` (the init trigger);
2. cmd-4 dev 149 with the empirical ON gate state (per #76: payload 4 →
   bank[40] `0x1f0f23ff`; cross-check §6 of PMP-FUNCTION-CALL.md which says
   15 = on — try both), watching bank[0] **and bank[40]** at every step;
3. if a gate moves: immediately do the Fender window copy + `FENDER_RUN`
   release (the boot #12-era sequence) and tight-poll the MU at
   Fender+0x110 for a RTKit HELLO;
4. SRAM deltas around each step.
