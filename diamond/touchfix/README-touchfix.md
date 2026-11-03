# d21-touchfix — userspace stale-contact fixer (2026-11-02 night; v3 2026-11-04)

**Traceability record.** Every userspace change for the touch fixer lives in this
folder: `d21-touchfix.c` (the daemon), `d21-touchfix.service` (unit),
`61-d21-touchfix.rules` (udev). Nothing else on the system was touched. The kernel
driver and its module are NOT modified by this change.

## The problem it fixes (measured 2026-11-02 night)

The Z2 controller holds contacts alive for seconds without reporting a lift:

- `captures/combo-KEY5.txt`: a contact held **t=11.27–24.72 s** (73 frames,
  states [3,4], never lifted); a second (tid 6) overlapped it t=14.55–20.39.
- While a stale contact is held, each new physical tap arrives on a second slot →
  libinput sees two fingers → apps discard multi-finger input as a gesture.
- Ground truth from the calculator protocol: **14 BTN_TOUCH downs reached the
  desktop, only 4 clicks reached the app** (user confirmed no clear-press was made;
  display showed four 5s).
- Long-presses work precisely because they are single-finger holds — which is also
  why "the longer I press the better the hit" (user, earlier the same night).

## What the daemon does

Reads `/dev/input/event1`, applies THREE rules, re-emits on a uinput virtual device
(`d21-touchfix virtual touchscreen`):

> **RULE 0 (v3, thin-sliver gate):** a FRESH contact whose NARROWER touch dimension
> (`min` of ABS_MT_TOUCH_MAJOR/MINOR) is below `slim_min` (default 220, `-s`) is a
> blob sliver or hover artifact, not a finger. Its down is cancelled in the SAME
> evdev frame (TID k ... TID -1 before SYN) so libinput never sees it; a contact
> that fattens within 150 ms gets its down re-emitted.
>
> **RULE 1 (stale release):** when a NEW contact appears while another slot has been
> held longer than `stale_ms` (default 1500, `-t`), synthesise the stale slot's lift
> first.
>
> **RULE 2 (palm arbitration):** when a contact's touch area (touch_major ×
> touch_minor) crosses `palm_area` (default 2500000, `-a`) while ANOTHER contact is
> down, synthesise its lift immediately.

From v3, **BTN_TOUCH is owned**: computed from the number of live forwarded slots at
each SYN; the driver's own BTN_TOUCH is dropped. A gated phantom can then never hold
the button down.

- Fresh taps then land as the only finger down = clean single-finger clicks.
- Long-press: never triggers (only fires when a NEW finger arrives).
- Drag: unaffected (smooth movement is not a new contact).
- Zombie contacts (the controller keeps streaming a force-released slot) are
  forwarded harmlessly: libinput ignores position updates on a slot whose
  tracking id is -1; the real lift passes through as a no-op.
- Known tradeoff: a deliberate second finger placed on a contact that is already
  older than `stale_ms` releases the first finger (slow 2-finger gestures
  degrade). Tune `-t` if that matters in practice.

### v3 evidence (2026-11-04, captures/combo-TLOW2 + combo-V3 + combo-OSK)

Measured on a HEALTHY roll (shape split is clean and non-overlapping):

| contact class | touch dims (evdev 0x30/0x31) | min dim |
|---|---|---|
| blob slivers (bottom band, pr spikes) | 1033×153, 824×148, 978×147 | ≤157 |
| hover artifact near a real tap | 257×122 | 122 |
| real finger taps (anywhere) | 1736×287 … 998×1259 | ≥274 |
| drag starts | 1045×787, 1329×795 | ≥787 |

Mechanisms killed: (a) blob 1-frame pressure spikes (pr 185–369) passing
`pres_min=128` → solo ghost clicks in the bottom-centre zone; (b) hover artifacts
downing 0–50 ms before a real tap → the real tap became contact #2 → the compositor
discarded the pair as a two-finger gesture (the "tap did nothing" quirk; measured on
the top-corner reference taps in combo-TLOW2-e1).
Verification round (combo-V3): 17 raw downs → 16 forwarded, the only difference the
one thin artifact; 2-finger taps forwarded as clean simultaneous pairs; 0 real taps
eaten. A NEW controller pattern surfaced the same day: fresh contacts can arrive
with touch_minor=0 (shape 2122×0) and fatten a frame later — the gate cancels and
the resurrect path re-downs them ~70–140 ms late (imperceptible).

ABS ranges are mirrored from the raw device at startup (X 0..1079, Y 0..1919,
slot 0..5 etc.); `INPUT_PROP_DIRECT` + BTN_TOUCH give it `ID_INPUT_TOUCHSCREEN`.
The udev rule benches the RAW device (`iPhone10,2 Touchscreen`) with
`LIBINPUT_IGNORE_DEVICE=1` — the kernel name on this install; the older docs'
`ATTRS{name}=="apple-z2"` does not match. The daemon only ever READS the raw node.

## Build + deploy (all paths in this folder)

```sh
# build (same recipe as mtstate):
podman run --rm -v "$PWD":/w localhost/orchard-hardware-recovery-tools:bookworm \
  bash -c 'cd /w && aarch64-linux-gnu-gcc -static -O2 -o d21-touchfix d21-touchfix.c'

# deploy:
scp -i ~/.ssh/id_hoolock d21-touchfix root@172.16.42.1:/root/d21-touchfix
scp -i ~/.ssh/id_hoolock d21-touchfix.service root@172.16.42.1:/etc/systemd/system/
scp -i ~/.ssh/id_hoolock 61-d21-touchfix.rules root@172.16.42.1:/etc/udev/rules.d/
ssh -i ~/.ssh/id_hoolock root@172.16.42.1 '
  systemctl daemon-reload
  systemctl enable --now d21-touchfix
  udevadm trigger --name-match=event1'    # re-evaluates the ignore property live
```

## Verify / test

```sh
# daemon up and virtual device present:
ssh phone 'systemctl status d21-touchfix --no-pager | tail -3'
ssh phone 'grep -A2 d21-touchfix /proc/bus/input/devices'    # Handlers=eventX
# force-releases appear in the journal as they happen:
ssh phone 'journalctl -u d21-touchfix -n 20 --no-pager'
# end-to-end: tap the calculator — the acceptance protocol
# (tap one key repeatedly, read the display) measures clicks-landed vs taps.
```

## Rollback (complete, nothing persists)

```sh
ssh -i ~/.ssh/id_hoolock root@172.16.42.1 '
  systemctl disable --now d21-touchfix
  rm /etc/udev/rules.d/61-d21-touchfix.rules
  udevadm trigger --name-match=event1'
```

The raw device returns immediately; the kernel module is untouched.

## Status log

- 2026-11-02 night: created; motivation + evidence above. Deployed to p3
  (`/root/d21-touchfix`, unit + rule installed, daemon ACTIVE). Verified: faithful
  passthrough (event1 vs event2 decode identical in rounds A/A2), stale-release fires
  (journal), virtual device tagged ID_INPUT_TOUCHSCREEN=1, LIBINPUT_IGNORE_DEVICE
  switch-over works live. LIMITATION (measured): the click loss is controller-side
  (15 taps → 10 raw contacts → 5 clicks); the daemon cannot recover contacts the
  controller never emits as separate lifts. Gotchas recorded: failed multi-file scp
  created a directory at the rule path; legacy uinput setup write EINVAL → use
  UI_DEV_SETUP/UI_ABS_SETUP; virtual event node changes on daemon restart after a
  module reload (event2→event3).
- 2026-11-04 (v3): RULE 0 thin-sliver gate + owned BTN_TOUCH (see above for the
  measured evidence). Old binary kept as `/root/d21-touchfix-v2.bak`; in-daemon
  rollback = run with `-s 0`. The v2 palm-area rule never fired on the blob because
  it computes the TOUCH-dims area (blob sliver ≈158k ≪ 2.5M) — the §1B-era
  "tool vs touch" conflation; RULE 0 is the actual blob defence.
