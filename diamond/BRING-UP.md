# DIAMOND Build — D21 touch bring-up (reproducible)

**iPhone 8 Plus (iPhone10,2 / D21AP, A11 / T8015) · kernel 7.3.0-rc1-g2bde906a7ae3 ·
validated 2026-11-03.** This is the recipe that took the Z2 touch controller from
"boots dead on every reload" to **5/5 deterministic live reloads and a user-verified
working desktop touchscreen**. Follow it top to bottom on any D21-class device running
the same kernel line; adapt the kernel bits for other Z2 devices via the same decode.

## What was actually wrong (the two-layer discovery)

1. **The power layer.** The D21 ADT wires the touch digital-core rail as
   `function-power_ldo = 75:pKW4('rBK3', 0x5020000)` — an **SMC function**, not a
   kernel regulator. Decoded from iOS's `AppleSMCEmbeddedFunctions.cpp`:

   - the function call is a **plain `SMC_MSG_WRITE_KEY` of a 4-byte code**
     `code = (dt_value & 0xffff0000) | enable`
   - **ON = `0x05020001`** (boots the controller; preamble answers `1f 01 1f 01`)
   - **OFF = `0x05020000`** (iOS writes this on every screen lock)
   - a raw `0x00000000` write is an **INVALID code** and trips the SMC's systemic
     protection → full device reset (reproduced twice, once on a cool idle system)
   - `SMC_MSG_RW_KEY`'s write phase is inert; its read phase returns the state byte
     (`00` = off, `01` = on) — useful only as a status read

   The high-voltage analog rail is the **chestnut display-PMIC regulator**
   (I2C `0x27` reg `0x05` bit `0x10`, already native in this tree as
   `chestnut-touch-hv`).

2. **The runtime layer.** After the fw upload the controller's **interrupt assertion
   needs host queue-pulls to kick-start**: without pulls the roll boots, streams ~2
   frames and goes silent *while both rails measure ON*. 40 x 100 ms pulls at init
   (`poll=1 probe_times=40`) start the IRQ flow and it then sustains itself.

Plus one trap: the HV rail must be **stable** before the core rail comes up (1–2 ms
gap → boot-then-silent; 500 ms → reliable; the manual proof used 12 s).

## Prerequisites

- The phone boots Linux (checkm8/palera1n → PongoOS → m1n1 payload → NVMe root) —
  see `docs/dual-boot.md`.
- Kernel with the full patch series (`patches/0001–0040`), module vermagic matching
  the running kernel (for a different kernel build, rebuild from the patch, see
  "Rebuilding" below).
- The touch firmware container + calibration blobs in `/lib/firmware/apple/`
  (`tools/` builds them from your own device's mtprops/ADT; nothing Apple-private
  ships here).
- `macsmc` bound (`ls /sys/bus/platform/drivers/macsmc` shows `23638…smc`) — the SMC
  function calls go through it.

## Deploy

```sh
# on the host, from this repo
scp diamond/prebuilt/apple_z2-d21-t8015-eeb5a4a7.ko root@172.16.42.1:/root/apple_z2.ko
scp diamond/prebuilt/{smc-keyprobe.ko,spmi-dump.ko,spmi-poke.ko,i2c-dev.ko} root@172.16.42.1:/root/
scp diamond/tools/{d21-i2creg.py,d21-i2cbb.py} diamond/verify-diamond.sh root@172.16.42.1:/root/
scp diamond/d21-touch.service root@172.16.42.1:/etc/systemd/system/d21-touch.service
ssh root@172.16.42.1 'systemctl daemon-reload && systemctl enable --now d21-touch d21-touchfix'
```

`d21-touch.service` is the gold config **plus the poll kick** — this is the line that
matters (never drop `poll=1 probe_times=40`):

```
ExecStart=/usr/bin/insmod /root/apple_z2.ko write=70:08 poll=1 probe_times=40 \
  frame_dump=1 verbose=1 poke_readback=1 \
  poke=10003060:17d3,1000305c:2,10003058:3,10003000:3,10003518:1 poke_after=10003400:1
```

(`write=70:08` and the pokes are the D21 Boot Sequence; `dmesg -n 1` + the tuned
palm params run via ExecStartPost — see the unit file.)

## Verify (the checklist)

```sh
sh /root/verify-diamond.sh
```

expects:

| check | pass value |
| --- | --- |
| apple_z2 loaded + bound | `event1` = "iPhone10,2 Touchscreen" in /proc/bus/input/devices |
| d21-touchfix virtual node | `event2` = "d21-touchfix virtual touchscreen" |
| SMC function state | RW read of rBK3 returns `01` after load |
| HV regulator | chestnut reg 0x05 bit 0x10 set (`/sys/class/regulator/regulator.1` enabled) |
| stream | IRQs ticking (the phantom idles at ~15 fps bursts; touches add records) |
| reload | `systemctl restart d21-touch` → preamble `1f 01 1f 01` + live roll, 5/5 |
| desktop | labwc at scale 2.0 (`/usr/local/libexec/arch-ipad-scale-output tablet` after VT changes) |

## Troubleshooting map (each symptom = one known cause)

| symptom | cause | fix |
| --- | --- | --- |
| preamble `00 00 00 00`, probe -110 | rail OFF (wrong SMC code, or the OFF command was sent as "on") | plain-write `0x05020001`; check `smc_on_val` |
| device reset right after a key write | raw 0 written to a FUNCTION key | never write raw 0; ON/OFF codes only |
| boots, ~2 frames, silent, rails measure ON | IRQ not kick-started | `poll=1 probe_times=40` in the unit |
| boots, garbage frames, silent, then fine on manual retry | HV raced the core rail | the 500 ms settle in `power_on` (already in the patch) |
| reload dead, preamble OK, init completes | OFF→ON drain too short (rare) | `systemctl stop` → sleep 5 → `start`; report if persistent |
| touch works, desktop doesn't react | touchfix not running, or the stale-scale | `systemctl enable --now d21-touchfix`; run the scale tool |
| "Invalid module format" on insmod | vermagic mismatch | rebuild from `patches/0040` against YOUR kernel (full vermagic string, NUL-padded) |

## Rebuilding for another device / kernel

```sh
git -C <hoolock-linux> checkout <base> && git am patches/0040-input-apple_z2-*.patch
make LLVM=1 ARCH=arm64 M=drivers/input/touchscreen          # or your build flow
# patch the module vermagic to the running kernel's release (FULL string, NUL-padded)
```

For non-D21 Z2 devices the decode is the transferable part: find your ADT
`function-power_ldo` (provider, 4CC name, value), compute
`code = (value & 0xffff0000) | enable`, wire the device's HV/ana regulator into
`power_on` with a settle, and keep the poll-kick. Verify with the same checklist.

## Safety rules (learned the hard way)

- **Never write raw 0 to a FUNCTION-flag SMC key.** It is an invalid code; the SMC
  protects the system by resetting it. Twice measured, once on a cool idle system.
- Never leave a kernel module spinning unbounded (any loop gets a hard cap).
- Check the SoC temp between experiment blocks (`/sys/class/hwmon/hwmon*/temp*_input`,
  abort > ~40 °C); charging over Lightning adds heat during long ladders.

## Shas

See `diamond/SHA256SUMS`. Driver source: Hoolock Linux `a11-port` @ `b2533c59a`
(patch `patches/0040`). The prebuilt modules carry vermagic
`7.3.0-rc1-g2bde906a7ae3 SMP preempt mod_unload aarch64` — same-kernel devices only.
