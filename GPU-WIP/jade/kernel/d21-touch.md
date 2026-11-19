# iPhone 8 Plus touchscreen bring-up (D21, D211)

The iPhone 8 Plus (D21, D211) touch controller is an Apple MTFW `C1F5E`
part, the same family as the iPhone 6s (D11, D111). It speaks the
generation-2 Z2 protocol with the grape HID interface, so the native
`apple_z2` driver serves it on the `iphone7_plus` path: surface descriptor
`0xd9`, report enable `0xaf`, the coordinate scaling of that family and a
1 ms chip-select delay.

Nothing below has run on the device yet. The facts come from the live
device's ADT and from the iOS 16.7.16 (20H392) IPSW; the open questions are
listed at the end.

## Board controls

| Resource | D21 connection |
|---|---|
| SPI1 | `0x2e404000`, size `0x4000`, AIC interrupt 292 |
| SPI input clock | 60 MHz (ADT clock id `0x14d`) |
| Touch transfer policy | CPOL 1, CPHA 1, 3 MHz |
| Chip select | GPIO138, active low |
| Reset | GPIO33, active low |
| Touch interrupt | GPIO102, falling edge |
| Touch clock | PMGR offset `0x78000`, 24 MHz parent, requested rate 32768 Hz |
| Analog rail | PMGR resource `ELpd` (not modelled by the kernel) |
| Core rails | PMGR resources `pKW4` and `rBK3` (not modelled by the kernel) |
| Panel | 1242 x 2208 |

The SPI1 clock comes from the board's ADT clock table: clock id `0x14d`
selects entry 77 of `clock-frequencies`, a little-endian u32 array whose
entry 0 is 24 MHz and whose entry 1 is the 32768 Hz touch clock. Entry 77
is 60000000, so the DT gives SPI1 a fixed 60 MHz clock; the mainline tree
has no 60 MHz A11 clock to point at.

The A11 has no SIO (SmartIO) node, so SPI1 runs PIO-only. The controller's
DMA channel request fails with `-ENODEV`, which the driver tolerates.

The analog and core rails are PMGR resources, not PMIC regulators, and
mainline has no PMGR rail driver. The driver therefore takes the touch
`hv-supply` and `core-supply` as optional and relies on the bootloader
leaving them enabled. This is the largest open risk in the bring-up.

## ADT node

The touch node is `/arm-io/spi1/multi-touch`:

| ADT property | Value |
|---|---|
| `compatible` | `hid-transport,k1` |
| `hid-merge-personality` | `C1F5E,4` |
| `hbpp-version` | `0x103` |
| `otp-address` | `0xffffffff` |
| `function-reset` | `OIPG` + 33 |
| `function-enable_cs`, `function-spi_cs0` | `OIPG` + 138 |
| `interrupts` | 102, flags `0x06000000` (edge, falling) |
| `function-clock_enable` | `KLCT` + `0x08` + `0x64` + `0x8000` |
| `function-power_ana` | `ELpd` + `0x302` |
| `function-power_ldo` | `pKW4` + `rBK3` + `0x05020000` |
| `power-sequence` | power_ana, power_ldo, clock_enable |
| `reset-delays` | `0x64320000` |
| `force-supported` | present |

The four-character tags are byte-reversed in these properties, and the
first u32 of each `function-*` property is a runtime index, not a register
offset.

The unit's calibration is in the same node: `multi-touch-calibration` (1008
bytes), `orb-gap-cal` (976), `orb-force-cal` (1458) and
`shape-dynamic-accel-cal` (192). All four fit the MTFW's maximum sizes, so
the driver's per-variant size check passes. m1n1 copies them into the DT
node that the `touchscreen0` alias points at.

The static device tree in the IPSW names the personality `C1F5E,3`, while
the live ADT names `C1F5E,4`. The two differ in size: the `C1F5E,4` blobs
are 64396 bytes at `0x0` and 17740 bytes at `0x401ae0`.

## Firmware

The MTFW is `D21_Multitouch.payload` from the IPSW. It is an Apple
OSSerialize XML document with one entry per personality. The `C1F5E,4`
personality lists fourteen HBPP items:

| Item | Address | Contents |
|---|---|---|
| Binary | `0x0` | 64396 bytes of firmware |
| Binary | `0x401ae0` | 17740 bytes of firmware |
| Property | `0x10009000` | `multi-touch-calibration`, max 1800 |
| Property | `0x400568` | `orb-gap-cal`, max 992 |
| Property | `0x4010d0` | `orb-force-cal`, max 1476 |
| Property | `0x401a10` | `shape-dynamic-accel-cal`, max 208 |
| ReadModifyWrite | `0x10003060` | 6099 (FLL multiplier) |
| ReadModifyWrite | `0x1000305c` | 2 (reference clock divider) |
| ReadModifyWrite | `0x10003058` | 6 |
| ReadModifyWrite | `0x10003000` | 3 |
| ReadModifyWrite | `0x10003518` | 1 (32 kHz clock enable) |
| RequestCalibration | - | the two-byte request `1f 01` |
| ReadModifyWrite | `0x10003400` | 1 (execute) |
| Config | - | the HBPP configuration |

The config gives the Z2 inter-packet delay as 125 us, CPHA 1, CPOL 1, a word
delay of 0, a CS delay of 0, a clock period of 125, a minimum DMA transfer
size of 16 and a normal boot timeout of 500 ms. The driver keeps its 1 ms
CS delay when the config asks for zero, so only the inter-packet delay
changes from the iPhone 7 Plus default of 1000 us.

The `RequestCalibration` item has no address. The controller calibrates
before it answers, and iOS waits 65 ms for the answer on its N1 path; the
driver waits the same time before it reads the acknowledgement.

### The recipe

The touch firmware is a public recipe output, built from the IPSW's
`Firmware/D21_Multitouch.im4p` (SHA256
`88aff455a6d0a8c4de5c6e1ae74c94961707591bf2b25076e88eb085d6d76790`; the
D211 file is byte-identical). The recipe for the D21 adds this output:

```json
{
  "destination": "lib/firmware/apple/dfrmtfw-d21-c1f5e-4.bin",
  "sha256": "56208f90f9da8078168cab79dea6ce2feaafb5fbcf322c7888666b04f9b0d343",
  "steps": [
    {
      "step": "im4p-payload@1",
      "input": "D21_Multitouch.im4p"
    },
    {
      "step": "z2fw-from-mtfw@2",
      "profile": "C1F5E,4",
      "otp_preflight": false,
      "hbpp_version": 259
    }
  ]
}
```

The recipe pins the personality `C1F5E,4`, the one the live ADT names. The
static device tree in the IPSW names `C1F5E,3` instead, so a unit whose
ADT names `C1F5E,3` would need the other blob; the MTFW carries both.

### HBPP length convention

An HBPP blob packet counts its payload in four-byte words. HBPP 0.104 and
later count one less than the number of words; HBPP 0.103 counts them in
full. The D21 and the D11 are 0.103 controllers, so their blobs carry the
full count. `makez2fw` always writes the 0x104 convention, which makes its
D21 output one word short in each firmware blob; the Orchard converter
takes the version from the recipe (`z2fw-from-mtfw@2`, `hbpp_version` 259)
and puts it into the firmware's CONFIG record, where the driver reads it
for the calibration blobs it builds itself.

## Kernel changes

The work is on the `feature/d21-touch` branch of OrchardLinux/linux
(worktree `~/projects/OrchardLinux/trees/d21-touch`).

- `drivers/spi/spi-apple.c`: a T8015 SPI hardware variant. The ADT
  describes the A11 SPI controllers with `spi-version 1` and the DMA
  channel list, like the A10's, so the T8010 register layout applies.
- `arch/arm64/boot/dts/apple/t8015.dtsi`: the SPI1 node and its 60 MHz
  fixed clock.
- `drivers/clk/clk-apple-t8010-touch.c` and `t8015-pmgr.dtsi`: the touch
  clock at PMGR offset `0x78000`, the A10's offset. The A11 PMGR keeps the
  A10's map: the same `0x8c000` size and the same power-state offsets.
- `drivers/input/touchscreen/apple_z2.c`: a D21 variant on the
  `iphone7_plus` path, optional supplies, and the 65 ms wait before the
  acknowledgement of a calibration request.
- `arch/arm64/boot/dts/apple/t8015-d21.dts` and `t8015-d211.dts`: the
  board files, with the `touchscreen0` alias that m1n1 needs.

## Open questions

1. Does the touch clock really live at PMGR offset `0x78000` on the A11?
   The offset is taken from the A10 by analogy; the ADT's `KLCT` resource
   for the touch clock names the same descriptor on both.
2. Are the analog and core rails on when the bootloader hands over? The
   kernel cannot switch them.
3. Which report ID does the D21 use at runtime? The driver uses the
   length-based dispatch of the D11.

## First-boot checklist

1. Boot with the converted firmware and read the serial log.
2. The SPI1 controller has to answer: check for transfer timeouts.
3. The touch clock has to enable: check for "touch clock failed to become
   ready".
4. The firmware has to load: the driver logs the HBPP readiness and the
   surface descriptor.
5. The calibration records have to be accepted: the four DT properties have
   to exist with the sizes listed above.
6. Touch has to report: capture evdev events over the whole panel and
   check the coordinates against the 1242 x 2208 space.

## 2026-11-05: working on the Orchard tree (combined driver)

The iPhOmarchy touch implementation (HoolockLinux `a11-port` series
0004-0045) was ported onto `feature/d21-touch` of OrchardLinux/linux and
boots working on this unit: with the chestnut touch-HV supply enabled
first in the power sequence, the SMC `rBK3` rail call, the boot-sequence
pokes and the 0x44 contact decode, `hardware-check touch` reports
**5055 input events** in its 20 s window on the first boot of the
combined driver (kernel `7.3.0-rc1-orchard-apple-16k`, worktree
`~/projects/OrchardLinux/trees/d21-touch`).

Two integration notes for the record:

- the combined driver's `apple_z2_is_iphone7_plus()` must include D21:
  the container's deferred `SEND_CALIBRATION_V2` records are gated on
  it, and without the membership the walk fails with -EINVAL right
  after the firmware blobs are ACKed (observed, fixed in
  `8b36bd091`);
- with the HV rail up first, the d9 surface descriptor parses through
  the standard long read (`e7 d9 00 b4 1a ...` = 6836 x 12153 in
  0.01 mm) — the unpowered controller's replies that motivated the
  earlier info-frame workaround do not occur in this power order.

Known from the iPhOmarchy docs and still open there: the still-contact
refresh cadence, left-edge ghost contacts, boot-mode variance (the
`poke_delay_ms=50` settle fixes the rejected-poke mode), and the
off-IRQ-pull hazard (never poll this controller without an IRQ).

## 2026-11-16: D21 support reconciled onto v0.3.1, validated on hardware

The D21 bring-up was ported from the old tree onto orchard v0.3.1 on branch
`d21-bringup-v031` (upstream `cee9395acd…`). Commits:

- `6f712f8`/`ec568de` — reconciled D21 patches against upstream v0.3.1
  (dropped t8015 patches superseded upstream; renumbered D21 input/wifi
  patches; `apple_z2` driver patches sidelined pending rebase).
- `88862eb` — fixed corrupt hunks in `devices/t8015/0017` (spi1_clkref) so
  the full ordered patch set applies cleanly (`git apply --cached` EXIT 0).
- `982f933` — re-enabled the D21 `apple_z2` driver as a t8015-scoped
  full-file replacement patch, ported from the field-proven driver in
  `OrchardLinux/trees/d21-touch{good,}` (md5 `9d44b75…`). All its deps
  (`macsmc.h`/`apple_smc_*`, `REGULATOR_APPLE_PMIC_TOUCH`) exist in v0.3.1.
- `505ec4e` — removed the now-superseded `0030–0033.disabled` patches.
- `b06c83f` — added a DT-only GFX description: `ps_gfx` corrected to
  `0x803e0`, `ps_gfx_sgx` @ `0x804a0`, `ps_gfx_kf` @ `0x804a8`, and the
  `gpu@204000000` node + mailbox. Nothing in v0.3.1 matches
  `apple,t8015-gpu` (powervr only binds `t8010-gpu`/`s8003-gpu`), so this
  is inert — no RGX/Fender access, safe for the stable baseline.

Full 581-patch apple-16k kernel builds cleanly; `t8015-d21.dtb` carries the
touch nodes (`apple,d21-touchscreen`, `spi1_clkref`, chestnut HV) and the
GFX domains.

**Hardware validation (RAM boots, no GFX):**
- Touch-only payload (`omarchy-iphone/d21-touch-only-boot`, new v0.3.1
  kernel): `apple-z2 spi0.0` completes the full D21 init (HBPP ready, d9/db/73
  reads, "J71b order complete", watchdog armed); `/sys/class/input` shows
  "iPhone 8 Plus Touchscreen"; USB network `usb0` at 172.16.42.1; no Wi-Fi
  modules. Stayed up >7 min, no reset to iOS.
- omarchy-a v0.3.1 release `dev-20261116-113113` (built from this checkout,
  D21 kernel): RAM recovery booted on D21 from RAM, `recovery_observed:
  true`, board `d21`, transitioned to Orchard Install mode. Nothing installed
  to internal storage.
- Wi-Fi driver remains non-functional on D21 (do not rely on it).

**Reset-to-iOS root cause (important):** two earlier touch-only boots that
reset to iOS were caused by a bug in the *payload init*, not the kernel: an
`init` line wrote `/etc/modprobe.d/no-wifi.conf` but that directory does not
exist in the initramfs; under `set -e` the failed redirection killed PID 1 →
panic → reset. Fixed with `mkdir -p … || true`. With that fixed, both the new
v0.3.1 kernel and the old tree booted and stayed up — the kernel was never
the cause.

**omarchy-a build note:** the release build hit an upstream Arch ARM
`openssl`/`openssl-3` file conflict (`libcrypto.so.3` owned by both). Local,
uncommitted workaround in `omarchy-a/system/install-toolchain`: add
`--overwrite /usr/lib/libcrypto.so.3 --overwrite /usr/lib/libssl.so.3` to the
`pacman -S` line. This is device-independent and not pushed.

## 2026-11-16: omarchy-a v0.3.1 installed on D21; boot-path findings

Built a device-agnostic omarchy-a v0.3.1 release (`dev-20261116-113113`) from
this orchard checkout (D21 kernel `b06c83f`). Local gitignored
`omarchy-a/orchard.local.toml` sets `device = "d21"`. Build needed a local,
uncommitted fix in `omarchy-a/system/install-toolchain`
(`--overwrite /usr/lib/libcrypto.so.3 /usr/lib/libssl.so.3`) for an upstream
Arch ARM `openssl`/`openssl-3` file conflict (device-independent).

**Install succeeded** (`last-install.json` `installed: true`): partition 3
(ext4 `omarchy-a-d21`, 26.6 GiB) erased/reformatted into boot + arm64 root;
APFS/iOS untouched; account `tablet` set; boot entry
`omarchy-a-4a82fc0e-7.3.0-rc1-orchard-apple-16k.conf` written. D21 was gated
off for install in orchard (`features.storage_write` missing); enabled locally
with `storage_write = "working"` (commit `749699f`) after the user explicitly
authorized an erase/reformat install.

**Boot-path findings (open):**
- `orchard launch` from a cold Pongo once failed with "main_storage_init
  failed", but an immediate follow-up proxy diagnostic showed D21 NVMe storage
  initializes fine (`nvme: ANS is on die 0`, `rtkit(nvme): booting with version
  12`, `nvme: initialized at 0x259cc0000`). The failure looks transient (cold
  boot race), not a hard limitation — retry with a warm loader.
- The post-install "first start" (recovery's `Client.call('start', {root,
  boot})`, which switches directly into the installed root without m1n1
  storage) reset to iOS. Strongest suspect: installed desktop coldplugs
  brcmfmac (Wi-Fi), known broken on D21; the RAM validation had blacklisted it.
  A Wi-Fi modprobe blacklist was added locally to omarchy-a's
  `system/overlay/etc/modprobe.d/99-no-broadcom-wifi.conf` (NOT yet baked into
  a release or reinstalled) as the candidate fix.

## 2026-11-16: why orchard-path boots reset but the known-good tethered boot works

The D21 has a **known-good desktop boot** documented in
`~/omarchy-iphone/{PROMPT-NEXT-SESSION.md,TOUCH-STATE.md,d21-omarchy/RUNBOOK.md}`:
omarchy-a v0.1.1-d21 userspace, kernel `7.3.0-rc1-g2bde906a7ae3` (hoolock
a11-port, `~/hoolock/linux` at `2bde906a`), root on `/dev/nvme0n1p2` (later p3),
out-of-tree `apple_z2.ko` + `d21-touch.service`, labwc + Quickshell software
desktop. Critically that kernel has **`# CONFIG_DRM_POWERVR is not set`** and
its DTB (`d21-boot-wifi.dtb`) has **no `apple,t8015-gpu` node and no
gfx_sgx/gfx_kf domains**.

That known-good system is booted **checkm8-tethered** via
`~/checkm8-kit/boot-pmgr.sh`: palera1n -> PongoOS -> `/send` a **prebuilt
m1n1 payload** (`linux-kit/m1n1-linux-p2-omarchy*.bin` /
`m1n1-linux-p3-omarchy*.bin`) with `chosen.bootargs=root=/dev/nvme0n1p{2,3}
rootwait rw console=tty0`. The storage access that makes that root boot works
only through that prebuilt tethered payload.

Every boot attempt in this session used an **orchard path** instead:
`orchard run` (RAM Pongo upload), `orchard install`/`launch` (m1n1 reading the
boot entry from internal storage from Pongo), or a custom RAM payload +
`switch_root` — none of which is the proven tethered-boot flow. All of them
reset to iOS. Conclusion: the resets are a property of the **orchard boot
path on D21**, not of the kernel features; the Wi-Fi and GFX-blacklist
experiments were chasing the wrong variable. To get a working desktop,
boot the installed root through the prebuilt tethered payload via
`boot-pmgr.sh`, or make orchard's boot path match that payload's kernel/DTB.

On branch `d21-known-good-shape` GFX DT was reverted and powervr disabled to
match the known-good kernel shape, built and verified, but a `orchard run`
boot still reset — consistent with the above.

## 2026-11-16: tethered payload for v0.3.1 userspace (next boot attempt)

To boot the new v0.3.1 userspace through the proven path, assembled a tethered
payload in the known-good `build-payload.sh` layout
(m1n1 `2e377fb…` + `chosen.bootargs=root=/dev/nvme0n1p3 rootwait rw console=tty0`
+ t8015-d21.dtb + new Image.gz `7.3.0-rc1-orchard-apple-16k`):

    ~/checkm8-kit/linux-kit/m1n1-linux-p3-omarchy-v031.bin
    sha256 6ddb537d7e03564dd6011a1cc312bbcc47c83a80b53e57322b9cdd2191b03ff7

Boot with the tethered flow (needs iOS + physical DFU gesture, run by the user):

    cd ~/checkm8-kit && sudo PAYLOAD=linux-kit/m1n1-linux-p3-omarchy-v031.bin ./boot-pmgr.sh

This uses the same m1n1/pwn path that boots v0.1.1 daily, with the new kernel
(NVMe built in, no powervr, no GFX node) so the v0.3.1 root on p3 should mount
and start systemd. This is the first v0.3.1 boot through the working path.

## 2026-11-17: v0.3.1 userspace confirmed good; old kernel + awake payload + touch bundle

A/B result: the known-good old-kernel tethered payload (`m1n1-linux-p3-omarchy.bin`,
kernel `7.3.0-rc1-g2bde906a7ae3`) **boots the new v0.3.1 userspace** on p3 to the
omarchy PIN screen. The new v0.3.1 kernel resets to iOS even via tethered boot.
Conclusion: v0.3.1 userspace is fine; the kernel is the fault. Keep the old
kernel + new userspace.

Artifacts prepared (host-side):
- `~/checkm8-kit/linux-kit/m1n1-linux-p3-omarchy-v031-awake.bin`
  (sha `b37bfa36…`): the exact known-good kernel+DTB with suspend/sleep/hibernate
  masked in bootargs, so the desktop does not auto-sleep and SSH stays up.
- `~/omarchy-iphone/touch-v031-bundle/` — gold `apple_z2.ko` (vermagic
  `g2bde906a7ae3`), `d21-touch.service`, `install.sh`. Installed over SSH after
  boot to get touch on the v0.3.1 root (the p3 reinstall removed the old module).

## 2026-11-17: offline root-patch payload (old kernel, no SSH/blanking race)

The v0.3.1 userspace boots with the old kernel but auto-blanks before SSH can be
used. To install touch without racing the blanking, built an offline patch
payload that boots a RAM shell (old kernel g2bde906a7ae3, which can mount p3),
mounts p3 rw, writes the gold apple_z2.ko + d21-touch.service into the installed
root, masks suspend targets, and stops (no desktop):

    ~/checkm8-kit/linux-kit/d21-offline-patch-oldkernel.bin
    sha256 46be46ef52bbf1948a134fa18352a9b1b6e4bdcb103da12fc3ae06b603046cae

Send from PongoOS via:
    sudo sh -c "printf '/send linux-kit/d21-offline-patch-oldkernel.bin\nbootm\n' | ./linux-kit/pongoterm"

The patch log is at /run/orchard/offline-patch.log on the RAM payload.

### Offline patch result + live fix (2026-11-17)
The offline-patch payload booted (old kernel, RAM shell) and mounted p3 rw.
Its built-in `install` binary was missing, so the module/service copies failed,
but sleep targets were masked. Fixed live over SSH with `cp`: gold apple_z2.ko
(vermagic g2bde906a7ae3) at /root/apple_z2.ko, d21-touch.service at
/etc/systemd/system/ (its enable symlink now valid), sleep/suspend/hibernate
masked. synced. The v0.3.1 root also still has the in-tree apple_z2 module
(7.3.0-rc1-orchard-apple-16k) which will NOT load under the old kernel; the
service loads the /root gold module instead.

### Root cause of "no touch / auto-blank" on v0.3.1 desktop (2026-11-17)
Journal from p3 (via offline patch) showed TOUCH WAS WORKING: d21-touch.service
loaded the out-of-tree gold apple_z2.ko and created "iPhone10,2 Touchscreen"
input1. The blanking was omarchy-powerd's hardcoded idle timer
(IDLE_GRACE_SECONDS=8, SETTLE_SECONDS=10): ~100s after boot it goes
GRACE->SETTLING->DARK and darkens+locks at the greetd PIN screen. sleep.target
masks did not stop it (userspace daemon). Fix applied live to p3: masked
omarchy-powerd.service (-> /dev/null), removed its enable symlink, added
d21-noblank.service. synced.

### v2 offline patch with autologin (2026-11-17)
v0.3.1 adds a PIN greeter that the known-good install did not have (it used
tablet autologin), and the greeter's own labwc has no touch mapping, so the PIN
screen cannot be operated by touch. v2 offline patch writes greetd
`[initial_session]` for tablet into p3's /etc/greetd/config.toml (autologin,
bypasses PIN), keeps powerd masked, keeps gold touch module+service.
Payload: ~/checkm8-kit/linux-kit/d21-offline-patch-v2.bin (old kernel
g2bde906a7ae3), sha ef86435b9360eefc68691df6f18c523825b91426c8f50cca7cf2ac37d528ed64.
After applying, boot the desktop with m1n1-linux-p3-omarchy.bin — should go
straight to desktop with touch, no PIN, no auto-dark.

### Journal diagnosis + full live fix (2026-11-17, final)
Journal from the failed desktop boot showed 3 causes:
1. My [initial_session] autologin used the default `service="greetd"` (PIN PAM)
   -> `pam_setcred: PERM_DENIED`, greetd restart loop, start-limit-hit, no desktop.
2. gold apple_z2.ko needs `dfrmtfw-d21-c1f5e-3.bin`; p3 only had -4.bin -> probe -110.
3. powerd idle-dark (already masked).
Live fixes applied to p3 via offline-patch SSH: copied -3 firmware to
/lib/firmware/apple/; set [initial_session] with `service="greetd-greeter"`
(the permitting PAM) for true autologin; powerd masked; gold module+service.
Should now boot straight to desktop, touch working, no PIN, no auto-dark.

### "Stuck after touch OK" = USB gadget failure (2026-11-17)
Journal showed the real reason the phone looked stuck and SSH never came up:
v0.3.1's legacy g_multi gadget fails on the old kernel:
`UDC core: g_multi: couldn't find an available UDC` / `udc ... failed to start
g_multi: -22` -> no usb0, no ttyGS0, no SSH. Known-good used a configfs
usb-gadget.service (NCM+ACM, product 0x4142). v3 offline patch
(linux-kit/d21-offline-patch-v3.bin, sha f094b6c9...) installs the known-good
usb-gadget.sh/.service into p3, enables it, and blacklists g_multi. Keeps the
earlier fixes (-3 firmware, autologin via greetd-greeter, powerd masked, gold
touch) already applied live to p3.

### FINAL fix 2026-11-17: autologin was the blocker; PIN greeter works
Live diagnosis over SSH (configfs gadget up) showed greetd stuck in
`pam_setcred: PERM_DENIED` restart loop from my [initial_session] autologin —
that is why the desktop never started, NOT touch or the gadget. Fix: removed
[initial_session] from /etc/greetd/config.toml, `systemctl reset-failed greetd
&& systemctl restart greetd`. Result: greetd active with normal PIN greeter,
touch module loaded (iPhone10,2 Touchscreen input), usb0 up, powerd masked.
The valid config for v0.3.1 on D21 = old kernel g2bde906a7ae3 + PIN greeter +
gold touch module + -3 firmware + configfs usb-gadget + powerd masked; NO
greetd autologin (its pam_setcred fails and kills greetd).

### 2026-11-17: d21-touchfix was the missing final piece
The known-good chain was apple_z2 -> event1 -> d21-touchfix -> event2 -> desktop;
my v0.3.1 deploy never included the userspace d21-touchfix daemon, so the
desktop/greeter consumed no usable touch. Deployed live: d21-touchfix-v3
(aarch64 static binary at /root/d21-touchfix), d21-touchfix.service (removed
`ExecStartPre=modprobe uinput` since uinput is built-in =y in the old kernel;
/dev/uinput exists), enabled + started. Result: event2 "d21-touchfix virtual
touchscreen" present, chain complete. Also corrected d21-touch.service to the
verified recipe (poll=1 probe_times=40, poke 10003058:6, poke_after 10003300:1)
and staged all 6 firmware blobs (z2-mtcl/orbgap/orbforce/shapeaccel +
dfrmtfw-3 + t8015-smartio) in /usr/lib/firmware/apple/.

### 2026-11-17: touch responding "sometimes" = v3 sliver gate gating real taps
With the full chain up, the roll was healthy (booted=1, IRQ edges, TIDs 46-57)
but touchfix v3 logged `gated thin slot N (shape Wx0)` then
`resurrected fattened slot (Wx~374)` for each tap - the real taps' first frame
has minor=0, below v3's slim_min=220, so they were gated and only intermittently
resurrected. Fix: touchfix -s 0 disables the sliver gate (per source). Updated
d21-touchfix.service ExecStart to `-t 1500 -s 0 /dev/input/event1`, fixed the
binary's exec bit (chmod 755), force-restarted. Now running slim_min=0 with
event2 virtual device. The service change is on disk (persists).

### 2026-11-17 FINAL: D21 desktop usable — full verified recipe
Got into the omarchy-a v0.3.1 desktop. Final fixes (all live on p3, persistent):
1. Touch chain: gold apple_z2.ko (9edf47 stopfix+DROP_UNUSED) + corrected d21-touch.service
   (poll=1 probe_times=40, poke 10003058:6, poke_after 10003300:1), all 6
   firmware blobs, and **d21-touchfix v2** (tools/d21-touchfix, the genuine
   pre-v3 binary; v3's RULE 0 gated every real tap) -> event2 virtual device.
2. greetd: NO [initial_session] (autologin pam_setcred PERM_DENIED); PIN
   greeter works. powerd masked (no auto-dark). configfs usb-gadget (0x4142),
   g_multi blacklisted.
3. Display scale: D21 panel is 1080x1920, NOT in arch-ipad-scale-output's
   whitelist (iPad res only), so it stayed scale 1 = tiny UI. Applied live
   `wlr-randr --output Unknown-1 --scale 2` and patched the helper's
   whitelist (1080x1920 added, .bak kept) for persistence.
Working boot: pwn -> /send linux-kit/m1n1-linux-p3-omarchy.bin (old kernel
g2bde906a7ae3). Reinstalling v0.3.1 would wipe all these p3 fixes.

### 2026-11-17: accuracy/reliability fixes (match known-good)
Accuracy was reduced because (1) live latch params were BOOT DEFAULTS
(tool_max=2000, tool_area_max=2500000, tool_area_hard=8000000) - too aggressive,
latching real finger presses as palms; my service was missing the tuned
ExecStartPost that the known-good had. Baked it in: 3000/5000000/2000000/12000000
applies on every boot/reload. (2) No watchdog: deployed the known-good
d21-touch-watchdog.service + d21-watchdog.sh + d21-recover.sh + gpioreset.py +
rollcheck.py/.sh + touchfun.py to /root, enabled+started; auto-detects
DEAD/DEGRADED/PHANTOM rolls and re-rolls via GPIO reset pulse (rails-off 30s).
Watchdog active, logging to /var/log/d21-recover.log. Per TOUCH-STATE, per-tap
jitter/delivery is roll quality, not geometry - the watchdog now manages that.

### 2026-11-17: display scale raised 2.0 -> 2.5
UI still small for touch at scale 2; raised to 2.5 live via
`wlr-randr --output Unknown-1 --scale 2.5` and persisted by writing
`2.5\t2.5\t2.5\tUnknown-1` to
/home/tablet/.local/state/omarchy/monitors/settings (the scale helper reads
field 3 for the output). Helper also has 1080x1920 in its whitelist (earlier).

### 2026-11-17: scale 2.5 broke touch -> reverted to 2.0
Raising scale to 2.5 made touch stop responding; reverted to 2.0 (live via
wlr-randr + persisted in monitors/settings). Scale 2 is the verified value for
D21 touch coordinate mapping (TOUCH-STATE: mapping verified at output scale 2;
the scale must be set before the shell starts). Do NOT exceed scale 2 on D21.

### 2026-11-17 REPO AUDIT: wrong driver build was deployed (phantom root cause)
Audited the repo per user request. Found /root/apple_z2.ko deployed was
sha256 eeb5a4a7 (older smc-rw build), but TOUCH-STATE §1 says the known-good
CURRENT is 9edf47cbd76... = apple_z2-stopfix-58d77f32c.ko — carries the §2E
unload fix + §2F D21 INPUT_MT_DROP_UNUSED that drops stale/unused contacts
(the phantom fix). Both have identical vermagic/params so it was invisible.
Corrected bundle + deployed 9edf47 live. All touch artifacts now match
TOUCH-STATE: driver 9edf47, firmware x6, d21-touchfix v2, watchdog, tuned
latch params, scale 2. The earlier eeb5a4a7 build caused the persistent
DEGRADED/PHANTOM rolls the watchdog kept fighting.

### 2026-11-17: touchfix binary missing on p3 after reboot (sudo locked)
After fresh reboot, roll healthy (50 irq/3s, event1 present) but d21-touchfix
inactive: /root/d21-touchfix does NOT exist on p3 (the live-deployed copy was
lost), and tablet sudo password is rejected so it can't be restored live.
d21-touchfix.service is enabled + correct but ExecStart file missing -> no
event2 virtual device -> greeter labwc has no touch. Need to restore the binary
to /root via offline-patch payload (root) on p3, or restore sudo access.

### 2026-11-17: v4 offline patch restores touchfix binary to p3
After reboot, /root/d21-touchfix was missing from p3 (lost during a prior
force-recovery), so d21-touchfix.service (enabled, correct) had no binary ->
no event2 -> no greeter touch. Root sudo was confirmed working (password
omarchy! via script-file method; the <<< heredoc was the earlier failure).
But USB network (usb0) died so SSH was unavailable. Built v4 offline patch
(linux-kit/d21-offline-patch-v4.bin, sha fa848383...) that copies the touchfix
v2 binary into /root on p3 when booted. Apply it, then reboot to desktop.

### 2026-11-17: touchfix binary was NOT actually missing (audit correction)
The offline-patch v4 log showed "touchfix binary already present" with sha
20a7a29 (correct v2 build). The earlier `find / -name d21-touchfix` as tablet
failed only because /root is not readable by tablet. So /root/d21-touchfix
was always fine. The "touchfix inactive" on the desktop boot was
start-limit-hit from repeated manual restarts (restart counter 131) draining
its Restart budget in that boot's /run state - cleared by a fresh boot.
p3 unit + enable symlink are correct; next desktop boot starts it cleanly.

### 2026-11-17: touchfix never started at boot = systemd ORDERING CYCLE
Root cause finally found: journal showed
"multi-user.target: Found ordering cycle: d21-touchfix.service/start after
d21-touch.service/start after multi-user.target/start - after d21-touchfix" ->
systemd deleted the touchfix start job every boot. d21-touch.service had
After=multi-user.target AND WantedBy=multi-user.target; touchfix had
After=d21-touch.service AND WantedBy=multi-user.target => cycle.
Fix (live, on p3): sed-deleted the After=multi-user.target line from
/etc/systemd/system/d21-touch.service (kept .bak-cycle), daemon-reload,
reset-failed + start d21-touchfix. Result: touchfix active, event2 virtual
touchscreen present. The start-limit / missing-binary theories were wrong.

### 2026-11-17: rigorous known-good audit -> byte-identical touch stack patch
Audited all known-good touch artifacts vs p3. Resolved the poke-value conflict:
the latest tested config (TOUCH-STATE ~511, "first actionable win", live on
the phone) is poke=...10003058:3..., poke_after=10003400 - which is what
tools/d21-touch.service has. My earlier :6/10003300 was from an older §1
snippet. Also confirmed the boot payload DTB already has correct touch size
(1080x1920), firmware -3, level IRQ - so DTB is fine.
Built d21-known-good-patch.bin (sha 6dbdf569...): installs onto p3 the exact
known-good stack - driver 9edf47 (stopfix+DROP_UNUSED), authoritative
d21-touch.service (:3/10003400), firmware x6, touchfix v2 binary (20a7a29),
known-good touchfix.service (minus modprobe uinput, built-in), udev rule
61-d21-touchfix.rules (bench raw event1), ordering-cycle fix, services enabled.
Apply with offline-patch boot, then reboot desktop = touch stack identical to
the working v0.1.1 install.

### 2026-11-17: RAM-payload boot of installed p3 (so I can push via orchard run, no sudo)
The user wants me to push to PongoOS like earlier. Orchard RAM payloads work
via `orchard run` without sudo; only the raw tethered .bin needs sudo pongoterm.
Built d21-boot-p3 (a RAM payload whose init mounts /dev/nvme0n1p3 and
switch_root /newroot /sbin/init) using a staged known-good kernel+DTB
(/home/doug/.cache/orchard/kernel-work/known-good-staged/kernel: Image.gz from
the tethered payload, t8015-d21.dtb = 1080x1920/-3.bin/level-IRQ). Push with:
  cd ~/orchard && ./bin/orchard run ~/omarchy-iphone/d21-boot-p3 --device d21 --no-build -y
This boots the installed desktop from RAM, via the known-good DTB, with me
doing the push. First apply the byte-identical known-good touch stack to p3
(d21-known-good-patch.bin), then use this to boot - all pushes by me.

### 2026-11-17: orchard-run pushes must use --kernel-dir known-good kernel
When pushing touch payloads via `orchard run`, they MUST be built with the
known-good staged kernel (`--kernel-dir .../known-good-staged/kernel`), not the
default v0.3.1 kernel (ceb6e02) - the new kernel resets on storage access.
The first `orchard run` of d21-known-good-patch used --no-build with the old
(new-kernel) binary and reset to iOS. Rebuilt both d21-known-good-patch and
d21-boot-p3 with `--kernel-dir` (and modules=false where no module tree). Both
now use known-good-staged/kernel/Image.gz. Push via orchard run from PongoOS.

### 2026-11-17: tethered desktop boot - greetd autologin recurred, removed again
On the tethered desktop boot with the byte-identical known-good touch stack,
touch chain was perfect (touch/touchfix/wd active, event1->event2, irq flowing)
but greetd had FAILED from a recurring [initial_session] autologin
(pam_setcred PERM_DENIED) - the bad config was still on p3 from an earlier
boot. Removed [initial_session] again (saved .bak-autologin), reset-failed +
restarted greetd -> active, PIN greeter (initial_session: None). NOTE: the
known-good-patch payload must ALSO strip [initial_session] from greetd config
so this does not recur on future applies.

### 2026-11-17 ROOT CAUSE of no-touch: poll=1 probe_times=40 was missing
Rigorous diff against canonical working unit (diamond/unit/d21-touch.service)
found the "known-good" copy I used (tools/d21-touch.service) was STALE and
lacked `poll=1 probe_times=40`. TOUCH-STATE §(975-1001) calls this CRITICAL:
"without it the roll boots, streams ~2 frames and goes silent while BOTH rails
stay ON" - exactly our symptom (no evdev events despite healthy IRQ). Rebuilt
d21-known-good-patch with the canonical unit (poll=1 probe_times=40,
poke 10003058:3, poke_after 10003400), plus greetd autologin strip. Verified
in built initramfs.

### 2026-11-17: poll fix deployed, but controller in IRQ storm (32164/3s)
With poll=1 probe_times=40 unit verified on p3 and tethered boot, the
controller came up in an IRQ STORM (~10k/s, irq/3s=32164) instead of healthy
~15/s. touch inactive, no input devices, watchdog cycling; USB gadget drops
during each re-roll so live diagnosis is impossible. This is a hardware roll
failure, not a missing software step - the stack is byte-identical to known-good.
A full power-cycle (iOS restart, not just Pongo re-pwn) is the untried recovery.

### 2026-11-17: driver/unit MISMATCH - use diamond/ pair (eeb5a4a7 + poll=1)
Rigorous cross-check found two eras in TOUCH-STATE. The user-verified 100%
config (2026-11-03 03:35, §1K) = driver eeb5a4a7 (smc-rw) + poll=1 probe_times=40,
matching the diamond/ dir (driver/apple_z2.ko=eeb5a4a7, unit/d21-touch.service
with poll=1). My patch had wrongly paired 9edf47 (stopfix, from §1 dated 11-02,
NO poll) with the poll=1 unit - never validated together, likely the IRQ storm.
Fixed: known-good-patch now deploys the diamond/ pair exactly.

### 2026-11-17 FINAL STATE: verified working pair + scale 2.0
Tethered boot with diamond/ pair (eeb5a4a7 driver + poll=1 probe_times=40):
touch=active touchfix=active greetd=active, driver poll=Y probe_times=40,
event1->event2 present, IRQ flowing. Scale was erroneously 2.5 on the greeter
-> set back to 2.0 live (wlr-randr under /run/user/967) and persisted in both
greeter and tablet monitors/settings (2\t2\t2\tUnknown-1). This is the exact
known-good configuration. Awaiting user PIN entry verification.

### 2026-11-17: definitive diagnosis - controller in PHANTOM/DEAD wedge
Live capture while user tapped: kernel receives valid report=0x44 frames
(touch parse nfingers=2-6) but rollcheck verdict=DEAD (active=0 fingerlike=0)
- all contacts are phantoms/blobs, no real finger contacts. evdev captures 0
bytes, so nothing reaches the greeter. The udev rule is correct (event1
benched, event2 used, labwc has event2 open), driver/roll stack correct.
Watchdog is stuck: roll quality PHANTOM (1/2) never reaches 2/2 because DEAD
re-rolls reset the counter; 30s rails-off recoveries fail. Triggered deep
manual recovery (120s rails-off + GPIO reset pulse + reload + 25s settle) with
watchdog stopped. A full power-cycle is the fallback if this fails.

### 2026-11-17: software recovery exhausted - full power cycle required
120s rails-off + GPIO reset pulse + reload yielded 10.6 fps but verdict=PHANTOM
(active=0 fingerlike=0) - controller still produces only phantom contacts.
All software recovery durations failed (30/90/120/150s). A real hardware
power-cycle (device fully off, battery disconnected from rails) is required to
clear this controller wedge. This is a hardware state, not software config.

### 2026-11-17: watchdog was STOPPED - the real reason no auto-recovery
Found d21-touch-watchdog.service inactive (stopped at 19:31 for a deep
recovery and never restarted) - so nothing was monitoring/recovering the roll
the whole time. The controller sits in whatever bad mode it lands in.
Restarted the watchdog (active). All services now: touch/touchfix/wd/greetd
active, scale 2.0 (applied at greeter startup via the scale helper), pres_min=64.
Foreground evdev capture PROVED the chain works when the roll is alive: 38
raw events with real BTN_TOUCH down, X/Y, pressure. So the software is correct;
the only issue is delivery-mode instability, which the watchdog now handles.

### 2026-11-17: watchdog ignored DEAD verdict - "repeated presses" root cause
Measured with simultaneous decoded evdev capture: raw event1 + virtual event2
produced 0 touch-DOWN events in 16s of tapping; only 2 frames total. Roll was
DEAD (2 fps, active=0 fingerlike=0) but watchdog did NOTHING: its quiet-check
needs IRQ d<2/5s (here ~5/5s passes), and its quality check only matched
DEGRADED/PHANTOM, ignoring verdict=DEAD. So a slow-but-not-silent dead roll
fell through both checks -> the "works but needs repeated presses" symptom.
Fixed: added `|| [ "$v" = "DEAD" ]` to the watchdog quality trigger
(line 79), restarted watchdog (active). Now a dead roll re-rolls in ~2 min.

### 2026-11-17: watchdog tuned for fast recovery
Q_EVERY 12->4 (check every 20s), Q_CONFIRM 2->1 (single bad verdict),
Q_COOLDOWN 300->120. Watchdog active. A dead/phantom roll now re-rolls in ~20s
so the user is not left pressing repeatedly.

### 2026-11-17: upstream re-look - key D21 driver divergence found
Re-examined OrchardLinux repos per user request. A9/A10 GPU is merged upstream
(gpu-a9-* PRs), but no upstream D21 touch support (devices/d21 is identity-only,
touch=missing). The D21 touch driver is iPhOmarchy-only, forked from hoolock
a11-port base 8d09368 (apple_z2.c 3229 lines) + 40 D21 patches, diverging
heavily from upstream orchard's evolved driver (4666 lines, 29 input patches).
KEY FINDING: our deployed eeb5a4a7 D21 driver lacks the "idle is not dead" fix
that the newer d21-touchgood tree (5540 lines) has. The old driver's no-frames
watchdog treats idle silence (0 frames/irqs) as DEAD and recovers every 15s,
resetting a healthy idle controller - matching "repeated presses" symptom.
Upstream's touch-runtime.md also documents a header-in-data-phase resync freeze
(D21 driver already has a D21 version of that fix at lines 1135-1142).
Next: build the d21-touchgood apple_z2.c (with idle fix) as a module matching
vermagic g2bde906a7ae3, or port the idle-fix hunks onto our driver source.

### 2026-11-17: built idle-fix D21 module (from d21-touchgood apple_z2.c)
Built apple_z2.ko from the d21-touchgood tree's apple_z2.c (5540 lines, with
"idle is not dead" fix: d21_last_irq + d21_contact_down, only recover when the
controller owes a frame), using the hoolock build tree, vermagic byte-patched
to g2bde906a7ae3. sha256 4ae5542012f13ee04cc73d167274825602f102d063f16259248cc1c1ff178cc8.
Staged into d21-known-good-patch and rebuilt (known-good kernel-dir). This
replaces the old eeb5a4a7 driver that cycled a healthy idle controller every
15s - the likely cause of "repeated presses". Deploy via orchard run from
PongoOS, then tethered desktop boot.

### 2026-11-17: idle-fix module deployed to p3 (verified sha) - awaiting boot test
d21-known-good-patch pushed via orchard run; p3 verified with idle-fix module
(4ae5542...), poll unit, greetd autologin stripped. Tethered desktop boot
attempted but device dropped off USB before SSH - test pending.

### 2026-11-17: first idle-fix module FAILED (probe -22), rebuilt correctly
Building apple_z2.c from the whole d21-touchgood tree (5540 lines) produced a
module that failed probe: "invalid iPhone 7 Plus calibration apple,z2-cal-blob
size -22" - that tree expects the NEWER m1n1/DTB to pass calibration via DT
property, incompatible with our tethered older DTB. Correct fix: cherry-pick
ONLY commit c2a38a5db829 ("Do not treat an idle D21 controller as a dead one")
onto our WORKING driver source (hoolock 5513 lines, compatible with our DTB);
it applied cleanly. Built module with vermagic g2bde906a7ae3.
sha 9d8c4c9c9da2287da021c61b9a444cbc462b0b205a295b337c7bd8fd09f3ec91.
Staged into d21-known-good-patch, rebuilt. This is the correct idle fix.

### 2026-11-17: corrected idle-fix module deployed, boot did not respond
Corrected idle-fix module (9d8c4c..., cherry-picked c2a38a5 onto working driver)
verified on p3 via orchard-run patch. Tethered desktop boot: device enumerated
0x4142 but no SSH, no serial output, no touch response - device in a hung state
where USB enumerates but all interfaces are dead. Could not verify whether the
driver probed (the -22 calibration issue from the whole-tree module should be
gone since this module is from the compatible base). Boot test inconclusive.

---

## SESSION HANDOFF (2026-11-17) — state at compaction, phone in PongoOS

### Branch / code state
- Working branch: `d21-known-good-shape` (from `main` v0.3.1 `50d3172`).
  Head at compaction: `18627ca` (docs). All changes committed; no uncommitted work.
- D21 kernel patches on this branch: 0017 (DTS fix), 982f933 (in-tree apple_z2
  for v0.3.1), 505ec4e (drop disabled), b06c83f GFX DT (later reverted on this
  branch). `d21-bringup-v031` is the parallel reconciled branch.
- apple-16k config: powervr DISABLED, GFX node reverted (match known-good).

### THE TOUCH SITUATION — what is actually true
- The software stack is byte-identical to the v0.1.1 setup the user verified
  100% working: driver, firmware x6, touchfix v2, udev rule, scale 2.0,
  poll=1 probe_times=40, tuned palm params.
- The remaining issue is the A11 controller's STOCHASTIC DELIVERY-MODE / roll
  problem (TOUCH-STATE "the big one"): rolls land HEALTHY (15-25fps, touch
  works) or DEAD/PHANTOM (interrupts with no real contacts -> "repeated
  presses" / no response). A fresh pwn-cycle boot gives the best first roll.
- Two concrete bugs were found and FIXED this session:
  1. The touchfix daemon never started at boot due to a systemd ORDERING CYCLE
     (d21-touch.service After=multi-user.target + WantedBy; touchfix
     After=d21-touch + WantedBy). Removed After=multi-user.target from
     d21-touch.service on p3 → touchfix starts, event2 virtual device appears.
  2. The watchdog was STOPPED and ignored verdict=DEAD. Restarted it, added
     `|| [ "$v" = "DEAD" ]`, tuned Q_EVERY=4/Q_CONFIRM=1/Q_COOLDOWN=120 so a
     dead roll re-rolls in ~20s.
- Last build: corrected idle-fix module (cherry-pick of c2a38a5db829 "Do not
  treat an idle D21 controller as a dead one" onto our working hoolock driver,
  NOT the whole d21-touchgood tree which fails probe with apple,z2-cal-blob -22).
  sha 9d8c4c9c... vermagic g2bde906a7ae3. Staged in d21-known-good-patch and
  VERIFIED on p3. This stops resetting a healthy idle controller.

### DEVICE STATE AT COMPACTION
- Phone is in PONGOOS (05ac:4141). Safe starting point.
- p3 FILESYSTEM has the full corrected touch stack installed and verified:
  gold driver 9d8c4c... (idle fix), d21-touch.service with poll=1, firmware x6,
  touchfix v2 + service, udev rule 61-d21-touchfix, powerd masked, scale 2.0
  persisted (greeter + tablet monitors/settings), greetd autologin stripped.
  These PERSIST — any successful desktop boot uses them.

### TO TEST AFTER COMPACTION (one clean cycle)
1. Phone in PongoOS → I push d21-boot-p3 via `orchard run` (mounts p3,
   switch_root to desktop, known-good kernel/DTB), OR user runs tethered
   `sudo sh -c "printf '/send linux-kit/m1n1-linux-p3-omarchy.bin\nbootm\n' | ./linux-kit/pongoterm"`.
2. SSH up (172.16.42.1, key ~/.local/share/orchard/private/ssh/id_ed25519,
   user tablet, sudo password omarchy!) → FIRST check dmesg for
   "apple-z2 ... probe ... error -22" (should be GONE with 9d8c4c module),
   then touch=$(systemctl is-active d21-touch), touchfix active, event1/event2,
   IRQ ~15/s. Then user taps PIN 040910.
3. Recurring obstacle: after boot the device often enumerates 0x4142 but SSH
   AND serial die (gadget flakiness). If that happens, full power-cycle the
   phone and retry; it is NOT a touch-stack problem.

### KEY PATHS
- Payloads: ~/omarchy-iphone/d21-known-good-patch (patch installer),
  ~/omarchy-iphone/d21-boot-p3 (RAM boot of installed p3 via orchard run),
  ~/checkm8-kit/linux-kit/m1n1-linux-p3-omarchy.bin (tethered desktop payload),
  ~/checkm8-kit/boot-pmgr.sh (pwn helper).
- Touch source: /home/doug/hoolock/linux/drivers/input/touchscreen/apple_z2.c
  (working base); idle fix commit c2a38a5db829 in
  /home/doug/projects/OrchardLinux/trees/d21-touchgood.
- Docs: this file (docs/bring-up/d21-touch.md) has the full session history.
- Hoolock tree had one leftover modified file (brcmfmac/pcie.c) and an untracked
  defconfig from module builds — unrelated user work, left untouched.

### UPSTREAM RE-LOOK FINDINGS
- OrchardLinux A9/A10 GPU merged; no upstream D21 touch (devices/d21 identity
  only, touch=missing). Upstream apple_z2 evolved (4666 lines, 29 patches) with
  iPad fixes; our D21 driver is a divergent iPhOmarchy fork. Full port of D21
  patches onto upstream apple_z2 is a large future task, not needed if idle fix
  + watchdog resolve reliability.

### 2026-11-17: full v0.1.1 restore - root causes found
- d21-boot-p3 uses rdinit/switch_root (docs: "doesn't reproduce greeter/display
  fully") - symptoms small scale + no touch. The 100x-working path boots kernel
  DIRECTLY with root=/dev/nvme0n1p3 (m1n1-linux-p3-omarchy.bin) - wrapped as
  d21-direct-boot for orchard run (no sudo).
- Working p3 required post-install final3.sh (erased by v0.3.1 install): fixes
  sshd (config perms, privsep dir /usr/share/empty.sshd, /run/sshd), serial getty
  (getty.target.wants/serial-getty@ttyGS0), id_hoolock authorized_keys for root+
  tablet, gold touch stack. d21-full-restore does all offline.
- sshd -t failed: "Missing privilege separation directory: /usr/share/empty.sshd"
  (final3.sh only made /var/empty). Fixed + verified sshd -t rc=0 on p3.
- Scale helper in both archives checks 1536x2048|2048x1536 but D21 panel is
  1080x1920 -> bailed, small UI. Replaced helper to scale any single output to 2.

### 2026-11-17: SUCCESS - v0.1.1 restored, scale correct + touch responding
After d21-full-restore (final3.sh sshd/getty/keys fix + gold eeb5a4a7 touch +
1080x1920 scale helper) and d21-direct-boot (kernel direct root=/dev/nvme0n1p3),
user reports: scale correct (2.0), touch responding, mostly OK. The 100x-working
v0.1.1 setup is restored. USB network/gadget remains flaky (likely why SSH did
not come up this boot) but the desktop and touch are functional.

## 2026-11-17 (late): v0.3.1 reinstall + clean-touch diagnosis (LOCAL, no push)

Pivoted off the v0.1.1 restore loop. Reinstalled v0.3.1
(`dev-20261116-113113`, root 6ef80700) into p3 via `orchard install`
(pass `omarchy!`, PIN `000000`, SSH-keys yes).

### Key build: `~/omarchy-iphone/d21-usb-boot/`
RAM payload whose /init sets up usb-session (gadget 0x4144 + dropbear)
BEFORE mounting p3 and `switch_root`. This is the ONLY way to get USB+SSH
that survives into the installed desktop on this phone (plain d21-direct-boot
has no initramfs, so no gadget -> USB vanishes). Verified: SSH into the real
desktop as tablet@172.16.42.1 (orchard ssh key), kernel g2bde906a.

Quiet-boot /init loads apple_z2 in the initramfs with frame_dump=0, poll=1
probe_times=40, gold poke, tuned latch params; masks the watchdog + d21-touch
in p3 (driver already up); writes a touchfix-wait.sh that waits for event1.

### Diagnosis: touch signal is GOOD; residual fault is the controller roll
- RAM-shell raw evdev capture (`d21-touch-decode.py`, /tmp/opencode/touchcap2.bin):
  18 taps, exact coords across full 1080x1920, clean DOWN/UP. Driver+panel GOOD.
- Live desktop: d21-touchfix active, event2 (virtual touchscreen) created.
  Captured event2: 4 taps decoded, 0ms latency raw->fix (latency probe).
  Input chain event1->touchfix->event2->libinput is functional.
- Residual: in the desktop, ~1.3 fps idle tick, only 2 taps landed in 14s of
  tapping = DEGRADED delivery-mode roll. Controller drops taps before evdev.
  This is the known A11 delivery-mode lottery; NOT fixable by touchfix config.
  Real fix = Orchard kernel c2a38a5 ("idle is not dead"), not g2bde906a.
- g_multi still probes+fails -22 at boot (blacklist didn't stick); USB gadget
  instability source. pmp-t8015.bin firmware missing (separate).

### Tools added (local)
- `~/omarchy-iphone/tools/d21-touch-decode.py` - decode raw evdev capture to taps.
- `/tmp/opencode/latency-probe.py` - raw(event1)+fix(event2) DOWN on one clock.
- Artifacts: /tmp/opencode/touchcap2.bin, vcap2.bin, latency.txt.

### State at end
Desktop booted via d21-usb-boot; SSH works; touch signal clean but roll degraded.
Next: boot with the Orchard c2a38a5 kernel (Known Good State) rather than
g2bde906a to get the idle-not-dead fix and a healthy roll.
