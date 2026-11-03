# The phantom multi-finger mode — the in-pocket / prox-baseline investigation

Session 2026-11-04 (3rd). Origin: dance #9 streamed **phantom multi-finger records
(nfingers=4, nobody touching) while real fingers went unreported**, and the user
proposed the iPhone's own "pocket guard" as the mechanism (on iOS, waking shows the
notification screen and a Home press is required before touch works normally).

**Verdict up front: the user's intuition is well-supported.** The Z2 firmware family
has (a) an explicit **in-pocket proximity-baseline subsystem**, configured by a
calibration blob iOS downloads and we never do; (b) a **high-level state machine with
a UILock state** (plus FaceDet/Anticip/Diag) matching the "locked until Home press"
behavior; and (c) telemetry counters exposing an **analog-scan noisy/saturated** state
machine we can read live. None of this was in our bring-up because it is all
kext-driven, not container-driven.

No Apple firmware or calibration bytes are reproduced here — findings and sources only.

---

## 1. Evidence (all gathered from local artifacts this session)

### 1.1 The D21 ADT multi-touch node declares 11 calibration sources; we load 4

`~/omarchy-iphone/adt/adt.txt` (live Device Tree of this unit), the
`/arm-io/spi2/multi-touch` node (phandle 90):

| ADT property | SysCfg source | Loaded by us? |
|---|---|---|
| `multi-touch-calibration` | `MtCl` | ✅ `z2-mtcl.bin` (1024 B) |
| `orb-gap-cal` | `OrbG` | ✅ `z2-orbgap.bin` (992 B) |
| `orb-force-cal` | `OFCl` | ✅ `z2-orbforce.bin` (1474 B) |
| `shape-dynamic-accel-cal` | `SDAC` | ✅ `z2-shapeaccel.bin` (208 B) |
| **`prox-calibration`** | **`PxCl`** | ❌ **never sent** |
| `orb-offset-cal` | `OOCl` | ❌ |
| `orb-accel-cal` | `OICo` | ❌ |
| `orb-dynamic-accel-cal` | `FDAC` | ❌ |
| `sshb-force-cal` | `SFCl` | ❌ |
| `sshb-2.75v-ungrouped-cal` / `-grouped-cal` | `uTSC` / `gTSC` | ❌ |
| `sshb-inverse-filter-cal` / `sshb-5v-ungrouped-cal` | `SIFC` / `uFSC` | ❌ |

(The same node also confirms our SMC work: `function-power_ldo = 75:pKW4('rBK3',
0x5020000)` — rBK3 IS the touch LDO function, code base 0x05020000, ON=+1 — and the
`power-sequence` blob spells `function-power_ana` → `function-power_ldo` →
`function-clock_enable`, the iOS order patch 0040 implements.)

### 1.2 The iOS kext (AppleMultitouchSPI / AppleMultitouchZ2SPI, from the D21
### kernelcache, iOS 16.7.16 20H392) has a prox-baseline subsystem

Strings + labeled disassembly (`~/omarchy-iphone/captures/mtspi-labeled.asm`,
D21 kc at `~/a11-fw/kc/20H392__iPhone10,2/kernelcache.release.iPhone10,2_5`):

- `"in-pocket-prox-baseline Data"` — a **Dynamic Calibration dictionary entry** the
  kext looks up at runtime and publishes as an IOReporter named
  `"ProximityBaseline"` (group `"Multitouch"`, channel `"Dynamic Calibration"`).
- `"sending prox calibration bytes"` / `"No prox calibration data present"` /
  `"%s: downloaded %u bytes of prox calibration data (` — the **Z2 bootload path**
  (`MTSPIBootloader_Z2`) downloads the prox calibration as an extra HBPP DATA-packet
  stream: header `0xE118`, chunks ≤ 0x3F0 (1008) B, status `0x4BC1` — the *same*
  transport as our fw + 4 cal blob downloads. It is **not** in the container's
  `Calibration Sequence` (which lists only the 4 providers we already send), which is
  exactly why our bring-up missed it: it is kext-driven, not container-driven.
- The device→host direction exists too: `"Updated dynamic cal entry <%s> with
  external message type 0x%X, length %u"` — **the controller pushes dynamic-cal
  updates (including the in-pocket baseline) to the host via external messages**, and
  the kext stores/publishes them. The baseline *computation lives in the firmware*;
  iOS's role is to supply `PxCl` at bootload and surface the result.
- `"WANTS_FRAMES_IGNORED"` — a personality flag where the host deliberately ignores
  frames (a guarded-reporting precedent in the stack).

### 1.3 The Z2 high-level state machine has the locked/guarded states

From the container fwconfig (`tools/d21-fwconfig.txt`, report 114 = 0x72
"Multitouch high level stats", Unit=Us, TicksPerSecond=1000):

```
states: Unknown(0) Active(1) Ready(2) Rsv(3) UILock(4) FaceDet(5) Rsv(6) Rsv(7)
        PreReady(8) Anticip(9) Diag(10)
```

`UILock` is the controller-side "UI locked" state — the firmware-level counterpart of
the iOS wake/lock screen the user described. Our driver already knows this list and
boot-writes state 1 (Active) via the `hl_state` param; every sampled boot log reads
back `high-level state index=1`. **The dance #9 phantom roll therefore started
Active and degraded at runtime** (or the 0x72 value is not the whole story — the
in-pocket decision is a separate firmware-internal mechanism).

### 1.4 The firmware exposes its analog-scan state machine on report 0xf8

The container's `DefaultMultitouchProperties` (report 248 = 0xf8, 83 B, the counters
our docs already read: "0xf8 counters still climbing") carries, at decode time,
exactly 15 counters:

```
touch.timing.F1/F2/F3.{dirty,clean,active}-frames   (offsets 1..36)
touch.asd.state-normal.frames / .transitions        (37/41)
touch.asd.state-noisy.frames / .transitions         (45/49)
touch.asd.state-saturated.frames / .transitions     (53/57)
```

`asd` = the analog-scan-diagnostics state machine: **normal / noisy / saturated**.
A roll stuck in `state-noisy` is the classic phantom generator (ghost contacts),
and a saturated/noisy pipeline suppressing real fingers matches the blind mode.
The offsets above are relative to the 0xf8 report payload (report length 83).

### 1.5 History repeats: nfingers=4 appeared before, with a zeroed surface mirror

STATE.md 2026-10-29: "Observed once: **4 phantom fingers** (nfingers=4, nobody
touching) right before the death", and the **0x7f critical-errors report tail
(surface-config mirror: height 12153, min_x −224, min_y −236, max_x 6608, max_y
11960) read all-zero** after that death — "the controller has LOST (or never
applied) its runtime surface config". So there are (at least) two distinct
phantom families:

- **Family A — the big single blob** (12.7M area, bottom-centre, recurs across
  boots; handled by the palm latch). Not this investigation.
- **Family B — the blind multi-finger mode** (nfingers=4 phantom records + real
  fingers unreported, frames still flowing so the silence watchdog is satisfied).
  Seen 2026-10-29 (right before a stream death) and as dance #9's boot mode.
  This is the one the recovery milestone cannot see and the user's pocket-guard
  hypothesis targets.

## 2. The working theory (testable)

1. iOS bootloads the Z2 with fw + 4 cal blobs **+ prox calibration (PxCl)**; the
   firmware computes/uses the **in-pocket prox baseline** from it. Our boot omits
   PxCl, so the in-pocket subsystem runs on an absent/garbage reference.
2. The phone lies **face-up flat on a desk**: a large uniform parasitic load on the
   panel — plausibly the same signature the in-pocket detector looks for. With no
   baseline to discriminate, the detector can latch "in pocket" at boot
   (the mode lottery) and stay latched: **guard candidates reported (the phantom
   records), real touches suppressed**.
3. On iOS the guard state is transient because (a) PxCl is correct, and (b) the
   locked→unlocked transition (Home press / FaceDet→Active) is driven by iOS every
   wake. Linux never drives any transition, so a latched guard persists forever.

Predictions if true:
- P1: simulating pocket conditions on a HEALTHY roll (panel covered by fabric/
  palm/light uniform pressure for several seconds) can produce the Family-B
  signature — reproducible, not a random fault.
- P2: during a Family-B roll, 0xf8 shows `asd.state-noisy` (or saturated) frames
  climbing while `state-normal` stalls; 0x72 may read ≠ 1 (UILock/Anticip/Diag)
  or report 0x7f shows the zeroed surface mirror.
- P3: loading PxCl (and possibly the sshb/orb extras) at bootload reduces or
  eliminates Family B.

## 3. Experiment battery (cheap → deep; next Linux session)

- **E0 (zero code):** the driver's runtime `read_now` knob (0644) does raw report
  reads without a reload: `echo 7f:16 > /sys/module/apple_z2/parameters/read_now`
  and the dump lands in dmesg (`D21 read <id> len ...` + hex). Ready-made sampler:
  **`/tmp/opencode/phantom-sample.sh`** (host copy; push to /root, run
  `sh /root/phantom-sample.sh phantom` on the NEXT phantom roll BEFORE any reload,
  then `... healthy` after a good reload for the contrast table — it samples
  72:4 + f8:83 twice 5 s apart + 7f:16 and appends to /root/phantom-sample.log).
  Add a `recdump.py` window of the phantom records if the roll persists.
  (Hands off the panel during sampling.)
- **E1 (zero code, the hypothesis test):** on a HEALTHY roll, cover the panel
  uniformly (thin fabric layer + light flat hand or a book) for ~10 s, remove,
  then tap. If Family B can be triggered on demand, the mechanism is confirmed
  and the "pocket guard" name is earned. Repeat 3×.
- **E2 (extract PxCl):** SysCfg is exposed read-only under Linux as
  `/dev/nvme0n3` (per the HoolockLinux recipe; verify size before use). Parse the
  SysCfg key table (makez2fw/syscfg.c format) and pull **PxCl** (and record the
  other multi-touch keys for later). Device-private: never commit or publish.
- **E3 (the fix candidate):** add a 5th cal download — the driver already has the
  enum (`APPLE_Z2_CAL_*`), the DT-property→firmware-file fallback and the HBPP
  blob builder; add `apple,z2-prox-cal-blob` + `apple/z2-proxcal.bin` and the
  target address (kext uses the bootloader HBPP path; find the fixed target
  address in MTSPIBootloader_Z2 or by reading the bootloader response). Re-test
  the mode lottery across ≥10 reloads.
- **E4 (detector, the touch item):** Family-B detector = "frames flowing AND
  (sustained all-phantom run OR 0xf8 asd-noisy/saturated share above threshold OR
  0x72 ≠ Active OR 0x7f surface mirror zeroed)" → trigger the existing
  reload-or-recover ladder. Wire it as a second trigger alongside
  `quiet_ms` in the recovery code (Orchard PR #52's control-reply-run detector is
  the sibling heuristic for the control-stall family).

## 3.5 E0 RESULTS — LIVE (dance #10, 2026-11-04 3rd session)

Dance #10's fresh boot **landed family B again** (2nd boot in a row: dance #9 was
nfingers=4, dance #10 nfingers=3). Sampled BEFORE any reload, phone hands-off on
the desk (`/root/phantom-sample.log`, decoded on the host):

- **The ghost records are FROZEN:** 3 contacts at identical coordinates every frame
  — f1 raw (559,9158) tool 3237, f3 raw (4162,**−236**) tool ~21300, f5 raw
  (1527,11313) tool 1001 — all **pres 0, st 4** (hover-class). f3's y is EXACTLY the
  surface descriptor's min_y (−236): a clamped, out-of-surface artifact. Tool 21300
  is between finger (~1000) and palm-blob (25000+) scale.
- **0x72 high-level state = 1 (Active) during the phantom roll.** The guard state is
  NOT visible in the HL report (or the driver's byte pick is not the fwconfig
  offset — the healthy contrast will tell).
- **0x7f critical-errors: the surface-config mirror is ZEROED** (`03 08 50 04` +
  zeros; healthy 10-29 reference was `03 08 50 00 | 79 2f … | 20 ff | 14 ff | d0 19
  | 78 2e` with the full surface mirror). **The 2026-10-29 zeroed-mirror signature
  is now correlated with the blind mode.** The controller has lost (or never
  applied) its runtime surface config.
- **0xf8 counters captured twice 5 s apart** (raw hex in /root/phantom-sample.log):
  three counters climb in lockstep (Δ222/5.05 s each ≈ 44/s), one is FROZEN
  (3739→3739), two climb at different rates (Δ206, Δ152), one byte flag = 1.
  Semantic mapping pending the healthy-roll contrast sample (counters are at
  fwconfig offsets 1..61 per §1.4; the reply payload alignment is still to be
  pinned — differences identify the channels without it).
- **The mode EVOLVES:** nf=3 frozen → (minutes later) nf=1 drifting ghost at raw
  (2674–3307, 1176–2367), tool ~4000 (resting-hand scale), pres 0–1, still st=4.
  Slowly wanders; never crosses pres_min → the driver correctly drops it (ZERO
  palm-latch messages — the ghost is never an active contact because pres < 128).
- **★ REAL FINGERS WERE REPORTED IN THIS MODE.** During a tap/hold/swipe test the
  controller emitted **7 clean real-touch lifecycles** (pres 119–463, finger-scale
  tool 563–725, st 1/3/7/4), interleaved with the ghost. The "blind" mode is
  PARTIAL delivery, not total: some gestures arrive (the 2 long ones fully),
  several taps delivered only 1-2 frames or nothing — the §1L delivery-loss
  pattern, present here too.
- **★ The "no touch response" was an INFRA failure, not the mode:**
  **d21-touchfix was NOT running** (unit enabled, v3 binary present, journal shows
  NO start attempt this boot — a silent auto-start failure, same class as the
  d21-touch auto-start quirk in §1M). The driver forwarded real taps to event1;
  the desktop reads event2 (touchfix output) → dead screen. `systemctl start
  d21-touchfix` fixed it instantly: user verdict "yes … seems more responsive"
  (top half better than bottom — the known regional asymmetry).
  **ADD TO THE POST-DANCE CHECKLIST: `systemctl is-active d21-touchfix` (and start
  it) — the auto-start is not trustworthy.**
- **★ USB-net death TIMING CORRELATION:** `systemctl restart d21-touch` (rBK3
  OFF→ON cycle) at T; within ~25 s the IP link was dead (gadget still enumerated);
  re-plug attempts → device VANISHED from the bus → dance #10. This is the
  strongest live evidence yet for the **smc_cut_rail=0 experiment** (§3 next-step
  1): the reload's rail cycle is timed exactly against the link death.



- D21 ADT: `~/omarchy-iphone/adt/adt.txt` (multi-touch node, prox node, PxCl).
- iOS 16.7.16 D21 kernelcache: `~/a11-fw/kc/20H392__iPhone10,2/…` — kext strings
  incl. the in-pocket/prox cluster at file offset ~0xA6AAD0; labeled disasm
  `~/omarchy-iphone/captures/mtspi-labeled.asm` (prox send fn @ 0x115e8: HBPP
  0xE118 DATA packets, ≤0x3F0 chunks, status 0x4BC1; ProximityBaseline reporter
  fn @ 0x6700).
- Container: `~/a11-fw/D21_Multitouch.bin` (plist; payload parts decoded this
  session — fw 0x0753/0x0773 images are ARM "Cumulus" armv5, no plaintext mode
  strings); decoded config `~/omarchy-iphone/adt/A11 Linux Touch
  Driver(WIP)/tools/d21-fwconfig.txt` (0xf8 counter map, 0x72 state list, Boot +
  Calibration sequences with addresses: MtCl @0x10009000, OrbG @0x400568, OFCl
  @0x400D10, SDAC @0x401A10; Boot Sequence = exactly our gold poke line + 0x10003400:1).
- HoolockLinux firmware guide: `~/a11-fw/firmware/iphone7.md` §9 — SysCfg =
  `/dev/nvme0n3` read-only under Linux; kboot copies touch cal blobs from the
  live ADT (`apple,z2-cal-blob` et al.).
