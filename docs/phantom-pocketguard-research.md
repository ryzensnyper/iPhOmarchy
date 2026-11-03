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

## 3.7 ★ THE POCKET-GUARD VERDICT (dance #13, 2026-11-04 — the calibrated boot)

The first fully-calibrated boot ever on D21 Linux (correct DTB polarity 0x8 +
all four cals + **the prox calibration accepted**, same `e1 0e` ack as the
regular cals) **fixed the controller-side tap-delivery loss**:

- **Measured** (10 number-row taps, the §1L protocol): **15 raw contact
  lifecycles in the stream (positions + pressures 257-1077, every tap
  present)** → **23 BTN_TOUCH downs / 22 ups forwarded on event1**. The §1L
  baseline was 4-6 raw lifecycles per 30 taps and 2-3 clicks (7-10%).
  User verdict: "Improved" (not yet perfect — multi-finger ghost records
  still mix into the stream; the touchfix v3 gate handles them).
- **The in-driver recovery also performed live end-to-end**: the roll went
  silent at boot (this rootfs unit lacks the poll=1 kick — known), the
  watchdog fired, 3 resyncs failed, **the full in-driver restart succeeded**
  (fw + cals + prox reload), the stream returned, and the **USB link
  survived the restart** (smc_cut_rail=0). Pre-recovery 0x7f byte3 = 04
  (critical bit), post-recovery = 00.
- **Conclusion: the user's pocket-guard intuition was substantially right.**
  The Z2's in-pocket baseline subsystem runs on the prox calibration
  (syscfg PxCl) that iOS downloads and we never did; without it the panel's
  contact detection degraded (bottom region worst — the pocket-gradient
  signature; the §1L OSK loss; the phantom/guard boots). Feeding PxCl +
  completing the cal set + the IRQ-polarity fix restored delivery.
- Boot-time IRQ flip now logs the true no-op: `D21: touch IRQ -> level-low
  (was 8)`; live DTB = 24 102 8. The -22 mismatch class is closed at the
  root (the 2026-11-03 "fix" had written 0x4 = LEVEL_HIGH — decode error;
  see diamond/payload/README-irqlevel.md).
- Also resolved: the "missing cal acks" scare was a kmsg-ring artifact —
  the 12-second ring under frame_dump flood plus truncated greps. The full
  boot window shows the complete sequence: fw blobs → container boot
  sequence (5 pokes `4a d1`, `1F 01`=`49 69`, `10003400:1`=`00 00`) → the
  unit's poke replay (5× len=20 `e1 0e`) → **the four cals (1040/1008/1492/
  224 B)** → **the prox blob (160 B)** → poke_after → init → flip no-op.

## 3.6 SESSION RESULTS CONTINUED (dance #11, same session)

- **The 0xf8 counters do NOT discriminate** — decoded both rolls with the reply
  alignment pinned (`content = reply[2..]`, fwconfig offset N = reply[2+N]; the
  content@reply[3] alternative gives garbage). The pattern is IDENTICAL on the
  dance #10/#11 degraded boots and on a post-reload roll: F1/F2/F3.clean-frames
  climb in lockstep at **44.7/s** (the scan rate — the 0x44 stream at ~15 fps is
  a subsample), F1.active frozen, asd.normal.frames = 0 with
  asd.normal.transitions +30/s, asd.noisy.frames = 1. **Scratch f8 as a
  detector input.**
- **0x7f byte3 = the critical-error bits**: 04 (bit2) on both dance boots, 00
  after a reload. But delivery stayed degraded with byte3=00 → the bit marks a
  boot-time condition that a reload clears, not the delivery quality. Weak
  detector candidate; keep sampling it.
- **The Oct 30 "healthy idle" captures (kmsg-idlenow/kmsg-live) show the SAME
  hand-scale blob** (nf=1, st=4, tool ~4000, pres 0, screen ≈(555,358)) — so a
  single hovering hand-scale record at that spot is the panel's NORMAL idle
  signature (desk/hand artifact), NOT a phantom marker. The real phantom
  signatures remain: (a) the boot-time FROZEN multi-record trio (one at
  tool 21300, y clamped to the surface min), (b) the delivery loss.
- **Delivery across rolls** (user tests): dance #11 boot = "top better than
  bottom, OSK weak" (the §1L pattern verbatim); post-reload roll (7f=00) =
  "still seems degraded". The loss persists across rolls and the 7f bit →
  consistent with the §1L **bottom artifact parked on the OSK region jamming
  controller-side contact detection** (12.7M-class blob, recurs across boots).
- **★ USB-net A/B RESULT (updated — NOT conclusive):** reload A/B so far:
  cut-enabled (`smc_cut_rail=1`) reloads 2/2 link-death (one → enumeration
  vanish, both needing a dance); cut-skipped (`smc_cut_rail=0`) reloads 1/3
  clean (one survived, one died to no-IP, one → vanish). **The unload-time
  rail cut alone is NOT the killer.** Every touch probe additionally does the
  SMC ON write + RW state probe + chestnut HV enable + reset/clock regardless
  of the param. Lead for the vanish class: the dance #11 boot logged
  `udc 230100000.usbdev: failed to start g_multi: -22` AT t=0 — the phone-side
  UDC failing once at boot then recovering; a UDC that flunks at boot may be
  fragile for the whole boot. NEXT DIAGNOSTIC (no reload needed): during the
  NEXT touch boot, watch phone-side dmesg for UDC/gadget reset events
  timestamped against the touch probe's SMC transactions — if the UDC logs a
  disconnect at the SMC-write moment, the cause is phone-side and the
  PMP/PMIC domain (§1M: the touch rail is PMP-private) becomes the suspect.
  Mitigation kept: the usb-rail drop-in (harmless), reloads minimized until
  WiFi lands.
- **★ E3 SHIPPED (patch 0043): the driver downloads the in-pocket prox
  calibration.** SysCfg (`/dev/nvme0n3`, 128 KB, sha 4765d8da…) parsed
  (datakey FourCCs are byte-REVERSED in the data dictionary: lCxP=PxCl,
  GbrO=OrbG, lCFO=OFCl, CADS=SDAC, lCtM=MtCl, lCFS=SFCl, CFIS=SIFC, CbrO=OrbC):
  **PxCl = 144 B** (→ `/usr/lib/firmware/apple/z2-proxcal.bin`, sha
  056baf3a…), SFCl 48 B, SIFC 28 B, OrbC 5002 B, MtCl 852 B. OrbG/OFCl/SDAC
  match our existing cal files byte-for-byte (offset parsing proven). **uTSC,
  gTSC, uFSC, FDAC are NOT present in this unit's SysCfg** — iOS never
  downloaded those either; the ADT references resolve empty. OOCl is a 16 B
  inline value, not a blob.
  Patch 0043 (`f0d89690d`): D21 sends the prox blob to **0x10009600** (the
  makez2fw GEN_1 slot) through the same post-boot blob path as the four cals,
  after the fw loop, optional + non-fatal, `prox_cal=0` disables. Lesson
  recorded: the GEN_1 pre-firmware ordering (prox before the fw image) acked
  `1f 01` but derailed the fw download (-EPROTO, probe -71) — the kext's
  bootloader-phase prox send does not translate to our choreography; post-fw
  is the proven path. **Boot result with prox: pending the next boot (this
  session's reloads kept getting killed by the USB link).**
- **d21-touchfix failed to auto-start on 2/2 dance boots** (unit enabled, v3
  binary present, journal shows NO start attempt). The desktop reads event2 =
  touchfix output, so a missing touchfix = "touch dead" even when the driver
  forwards taps. Post-dance checklist: `systemctl is-active d21-touchfix ||
  systemctl start d21-touchfix`.
- **★ /root writes are lost by HARD POWER CUTS unless synced**: the ec97a9c9
  module write (16:07) reverted to the older da849cb2 across the dance #11
  power cycle, while the proxcal firmware file (pushed minutes earlier with
  idle time to flush) survived. **RULE: run `sync` (twice) immediately after
  every push, and verify the sha before relying on it after any dance.**
  /root/touch-revive.sh remains unexamined (suspect #1 for reversion).
- `/proc/interrupts` on this kernel: the AIC count column is STATIC (65828 on
  two different boots, per-CPU columns 0) — do not use it for irq rate; count
  `touch parse` lines per wall time instead.

## 3.8 ★ SESSION 2026-11-04 (4th): the roll lottery persists on calibrated boots —
### measured three ways, two detectors closed, two new leads

Three fully-calibrated boots in one day (prox acked + DTB 0x8 on all three),
THREE different rolls — the calibration is settled, the per-boot mode lottery
is not:

| boot | roll | 15-tap protocol (10 OSK + 5 top) | report state |
|---|---|---|---|
| #13 (3rd sess.) | GOOD | 10 taps → 15 raw lifecycles → 23 downs | — |
| power-on 17:08 | ALL-DEAF (top+bottom) | 15 taps → 6 raw (~3 real) → 6 downs | f8: normal.frames=0, trans +19/s, noisy=1; 7f byte3=00 |
| #14 (reload-death → dance) | MIXED (top works, bottom deaf) | 15 taps → 7 raw → 3 downs; TOP taps arrived (pres 654-1092), BOTTOM 1/10 | f8: same signature as bad boot; 7f byte3=04 (INVERTED) |

- **★ f8 is DOUBLY SCRATCHED**: the counters are cumulative (the ~44.7/s
  lockstep trio scales with uptime — 135K at 3400 s, 12.6K at 446 s) and the
  asd signature (normal.frames=0, transitions ~19/s, noisy.frames=1) is
  IDENTICAL on the all-deaf, mixed, and (per §3.6) degraded rolls. It cannot
  discriminate roll quality.
- **★ 0x7f byte3 is a weak, non-monotone marker**: 04 on the MIXED roll, 00 on
  the all-deaf roll, 00 post-recovery on #13. Not a delivery predictor. The
  7f "surface mirror" area currently reads f8-counter values, not the surface
  descriptor — earlier "zeroed mirror" readings (dance #10) need that
  reinterpretation; the mirror-vs-counters switch condition is unknown.
- **★ The parked-artifact jamming theory WEAKENED**: dance #14 had NO parked
  bottom ghost and NO giant y-clamped blob in the whole capture window, and
  the bottom was still deaf (1/10). The bottom deafness is deeper than the
  artifacts (see the prox-address lead below).
- **★ NEW DRIVER FLAW (measured, fix drafted): the palm-latch counter counts
  oversized frames regardless of pressure.** The #14 top taps arrived with
  tool_major 3797-4332 (≥ tool_max=3000) and pres ramping; big_frames hit 8
  BEFORE pres crossed pres_min, so the whole tap was latched and never
  forwarded (zero evdev events at those times — event1 absolute-timestamp
  decode). The one finger-scale tap (tool 736, pres 529) forwarded instantly.
  Fix (patch 0045 candidate): count big_frames only on frames that would
  forward (pres >= pres_min); the giant-blob class still hard-latches on
  tool_area_hard (its pres is irrelevant, area ≫ 12M).
- **★ NEW LEAD for the bottom deafness — the prox target address.** Our
  patch 0043 writes PxCl (144 B) to 0x10009600 (makez2fw GEN_1 slot) via the
  post-boot cal path; the e1 0e ack proves the WRITE, not that the fw ever
  READS it from there. The iOS kext sends PxCl through the BOOTLOADER HBPP
  DATA stream (0xE118 chunks ≤1008 B, status 0x4BC1) BEFORE the fw boots —
  a different channel entirely. If the fw's in-pocket subsystem is still
  running uncalibrated, the bottom (pocket-gradient) region is exactly where
  it should be deaf — the observed signature. NEXT: decode the kext prox
  send fn (mtspi-labeled.asm @ 0x115e8) for the actual target, and/or find
  the GEN_1 slot semantic in makez2fw; consider an HBPP-DATA prox variant.
- **Plain POWER-ON boots Linux with full calibration** (2/2: the 17:08 boot
  + dance #14): the dance is only needed after a power-CUT-into-iOS or an
  USB-death reboot. The reload USB-death remains the dance-forcer.
- **g_multi -22 at t=0 reproduced 3/3 boots** (`couldn't find an available
  UDC` — g_multi loads before dwc2 probes; configfs-gadget.g1 then binds
  fine). The reload link-death reproduced again (dance #14 was forced by
  it). NEW: `pmp-t8015-v1 232300000.pmp` probe fails with missing
  `apple/pmp-t8015.bin` — the PMP driver exists in the kernel without
  firmware; relevant to the §1M PMP-domain lead for the USB deaths.
- **d21-touchfix auto-start failed again on dance #14** (4th consecutive
  boot). Started manually per checklist. Root cause still unexamined —
  journal shows NO start attempt; suspect an ordering/condition issue in the
  unit (worth a dedicated look: `systemctl cat d21-touchfix` + journal).
- **Tooling lessons**: `pkill -x cat` in a capture script kills the NEXT
  capture's kmsg stream too (use PID files); evdev captures via
  `timeout N dd bs=24` are sound (a silent driver forwards nothing — 0 bytes
  is data); evdev event timestamps are absolute (tv_sec = the phone's epoch
  clock) — align them against kmsg uptime via the first event's frame, not
  against the capture launch time.

## 3.9 ★ DANCE #15 (2026-11-04 4th session, evening): the prox fix LIVE at
### 0x00400180 — correct but not sufficient on one roll; the drift is the story

Patch 0044 (the prox target corrected from the GEN_1 guess 0x10009600 to the
kext default 0x00400180, extracted from the 20H392 kernelcache's Z2 defaults
initializer along with cal_dl_addr=0x00400200 / fw_execute_addr=0x10001800 /
fll_mval=0x16e4@0x10001c04; the D21 ADT declares none of the overriding DT
properties, so iOS runs the defaults) shipped and boot-verified:
`D21: prox calibration -> 0x00400180 (160 bytes)` on dance #15.

- **Delivery on #15**: 15 taps → 8 raw lifecycles → 9 downs → 7 desktop.
  BOTTOM taps now read FINGER-SCALE (tool 875-896, pres 481-764 — #13-class
  healthy shapes) where #14's bottom was absent — but only 2/10 arrived raw.
  User verdict: "no real change".
- **The tool scale is REGION- and ROLL-dependent**: #15's TOP taps read tool
  5000-5498 (pres up to 879 — genuine strong touches) while the bottom reads
  ~880; #13-era taps read 560-725 everywhere; the palm class stays ≥25000.
  The unit's tool_max=3000 was eating every longer top tap mid-press
  (latched after 8 oversized frames before pres peaked).
- **Latch gates raised live via sysfs** (no reload): tool_max 3000→12000,
  tool_area_max 5M→8M, tool_area_hard stays 12M (palm blobs 868M still
  hard-latch; the idle blob tool ~4100 passes the gate now but its pres sits
  0-1 idle). PERSISTED in the unit's ExecStartPost + daemon-reload.
- **★ THE ROLL DRIFTS WITHIN A BOOT**: four minutes after the 8-lifecycle
  window, the same boot with the same params gave 3 lifecycles / 2 downs in
  the re-test window, with the stream collapsing into hover-noise (79 ghost
  lifecycles pres < 128, fps sagging to ~2.4 metronome cadence). The mode
  lottery is not just per-boot, it is PER-MINUTE — any single-boot A/B of a
  fix is confounded by drift; only multi-boot distributions are meaningful.
- **The reload USB link-death count is now 2/4 cut-skipped** (dance #14 and
  the reload3->#15 transition both died; re-plug 0/2, both needed dances).
  The reload as a re-roll lever is USB-expensive; WiFi (PR #55 port) remains
  the unlock.
- **The vermagic rule**: modules must carry the running kernel's git-hash
  vermagic (payload kernel = hoolock 2bde906a7); same-length hash swap in
  the .ko works, NUL-truncation does NOT (the kernel strcmps the full
  string incl. flags). See patches/REBUILD-VERMAGIC.md.
- **Bottom line**: the prox target is now CORRECT (a real bug fixed — the
  data lands where the fw reads it), but one roll cannot show its effect on
  the lottery distribution; the bottom-region deafness persists per-roll.
  Next levers: E1 (the uniform-cover trigger test — reproduce the deaf mode
  on demand), multi-boot roll statistics with the fix in place, patch 0045
  (latch pres-gating), and the USB-net/PMP investigation to make reloads
  cheap.
