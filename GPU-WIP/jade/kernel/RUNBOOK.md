# D21 current working setup — reproducibility RUNBOOK

Local-only record (do NOT push to any remote). Captured 2026-11-17.
Purpose: repeat the CURRENT setup exactly. This is the v0.3.1 install with a
custom "usb-boot" payload that gives stable USB+SSH into the installed desktop,
and a clean (non-flooding) apple_z2 touch chain. We are deliberately staying on
the `g2bde906a` kernel for now; the residual degraded-roll issue is documented
in `../d21-touch.md` (real fix = Orchard kernel c2a38a5, not applied).

## 0. Commit / hashes (pin these)
- Installed release: `dev-20261116-113113` (Omarchy A / v0.3.1), p3 root UUID
  `6ef80700-1338-48aa-be57-eba02269c2e1` (from last-install.json).
- Account: user `tablet`, sudo password `omarchy!`, lock PIN `000000`.
- SSH: key `~/.local/share/orchard/private/ssh/id_ed25519` as `tablet@172.16.42.1`.
  (RAM payloads use `~/.local/share/orchard/private/ram-ssh/id_ed25519`.)
- Boot kernel: `7.3.0-rc1-g2bde906a7ae3` (staged tree
  `~/.cache/orchard/kernel-work/known-good-staged/kernel`).
- Touch driver: `apple_z2.ko` sha `9edf47cbd76cd0b5fb09cdaf89bdf9a1b11b70057edde551c2e04bb40ff04eb4`
  (vermagic g2bde906a7ae3).
- touchfix v2 binary sha `20a7a29fb8a5fc860b5f3cee48f41daa92df4d2c831c4b1fb2f84543ceb932a8`.
- Boot payload `~/omarchy-iphone/d21-usb-boot/out/apple-16k/`:
  `linux.bin` sha `6a4e5cef55855197aecd005f78f784cda42b132780c237f9adaf4ce3de6daf48`,
  `pongo.bin` sha `6cc34754c9a0f183b5ec7900e28396b414e62900da4ab571585bf82b9b04be06`.
  History: `07fec1f3…` (initial) -> `de2ebaa3…` (poke 6->3) -> `6a4e5cef…`
  (quiet driver: removed poke_readback, added pres_min=64 — see §6).

Device: iPhone 8 Plus (D21), ECID `65d2c0408002e`, USB `3-3`.
PongoOS `05ac:4141`, payload gadget `05ac:4144`. Host iface `enp13s0f3u3`
host `172.16.42.2/30`, phone `172.16.42.1`.

## 1. (Re)install v0.3.1 into p3  — only if starting from scratch
Device must be in PongoOS. Run the interactive installer in tmux:

```
tmux new-session -d -s d21install -x 200 -y 50 \
  'cd /home/doug/orchard && ./bin/orchard install \
   /home/doug/omarchy-a/out/releases/dev-20261116-113113/index.toml 2>&1; exec bash'
```

Answer prompts in order:
1. "Continue?" -> `Y`
2. Password (sudo) -> `omarchy!`   (twice)
3. Lock-screen PIN (6 digits) -> `000000`   (twice)
4. "Allow SSH logins from this computer?" -> `Y`
5. "Where to install?" -> `1`   (replace partition 3, erases it)
6. Type `erase 3` to confirm.

Wait for "Installed". The "Could not confirm it started" timeout is expected on
T8015 (orchard launch can't read m1n1 storage) — ignore it.

After install, the phone is in a generic iPhone USB state. Power-cycle into
PongoOS for the next step.

## 2. Build the usb-boot payload (only if rebuilding)
Source: `~/omarchy-iphone/d21-usb-boot/` (init + orchard.toml + rootfs/).
The exact init is archived here as `usb-boot-init.sh` (sha
`5df8b09998fc3bf4548a51dba20d6d987aab38b3f4ae7d0d201df1f63da3a850`) and
orchard.toml as `usb-boot-orchard.toml`.

```
cd /home/doug/orchard
./bin/orchard build /home/doug/omarchy-iphone/d21-usb-boot --device d21 \
   --kernel-dir /home/doug/.cache/orchard/kernel-work/known-good-staged/kernel
```

What the init does, in order (see archived usb-boot-init.sh):
- Mount proc/sys/dev/pts/run; set up the USB gadget + dropbear via
  `sh /usr/libexec/orchard/usb-session` (gadget PID 0x4144, addr 172.16.42.1).
- Stage the 6 firmware blobs to /lib/firmware/apple.
- `insmod /apple_z2.ko write=70:08 poll=1 probe_times=40 pres_min=64 \
   poke=10003060:17d3,1000305c:2,10003058:3,10003000:3,10003518:1 \
   poke_after=10003300:1`
   - QUIET: no `poke_readback`/`verbose`/`frame_dump`/`reply_log` — driver logs
     nothing at idle; only real touch events reach evdev. (poke_readback was
     the idle chatter source; it is locked at load, so must be off at insmod.)
   - `pres_min=64` = known-good validity threshold (module default 128 filters
     light quick taps). 10003058 = **3** (was 6 in first build). See §6.
- Apply tuned latch params: tool_max 3000, tool_area_max 5000000,
  tool_area_release 2000000, tool_area_hard 12000000.
- Wait for /dev/input/event1; bring up NVMe; mount p3 rw at /newroot.
- Stage firmware + this kernel's module tree into the installed root.
- On p3: mask d21-touch-watchdog and d21-touch (driver already up); write
  `/root/touchfix-wait.sh` (waits for event1 then execs touchfix v2) and a
  d21-touchfix.service that runs it with Restart=always.
- `kill` RAM processes, mount --move dev/proc/sys/run, `exec switch_root`.

NOTE: `orchard run --no-build` recompiles the RAM image from components because
`transport = true` — that is fine (it uses the payload's own init + rootfs).

## 3. Boot the desktop (every time)
Put phone in PongoOS, then:

```
cd /home/doug/orchard
./bin/orchard run /home/doug/omarchy-iphone/d21-usb-boot --device d21 --no-build -y
```

Wait ~40 s. Confirm:
```
lsusb | grep 4144                      # 05ac:4144 Orchard d21-usb-boot
ssh -i ~/.local/share/orchard/private/ssh/id_ed25519 \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    tablet@172.16.42.1 'uname -r; systemctl is-active d21-touchfix'
```
Need to clear the RAM host key cache between boots (dropbear key is per-boot):
```
: > ~/.local/share/orchard/private/ram-ssh/network_known_hosts
```

## 4. Live touch-stack checks (over SSH into the desktop)
```
K="ssh -i ~/.local/share/orchard/private/ssh/id_ed25519 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null tablet@172.16.42.1"
$K 'systemctl is-active d21-touch d21-touchfix d21-touch-watchdog; \
    for f in /sys/class/input/event*/device/name; do echo "$f: $(cat $f)"; done; \
    lsmod | grep apple_z2'
```
Expected: d21-touchfix active (d21-touch + watchdog are intentionally masked/
inactive), event1 = "iPhone10,2 Touchscreen", event2 =
"d21-touchfix virtual touchscreen", apple_z2 loaded.

sudo on device: `echo 'omarchy!' | sudo -S -p '' <cmd>`

## 5. Capture + decipher touch cleanly
On the device (as tablet, via $K), capture raw evdev while tapping:
```
$K 'timeout 10 cat /dev/input/event1 > /tmp/touchcap'     # raw driver
$K 'timeout 10 cat /dev/input/event2 > /tmp/vcap'          # fixed/libinput path
```
Pull with `cat` over ssh (scp/sftp-server is NOT installed on the device):
```
$K 'sudo -S -p "" cat /tmp/touchcap' > /tmp/touchcap.bin   # (prefix echo omarchy!)
```
Decode on the host:
```
python3 d21-touch-decode.py /tmp/touchcap.bin
```
`latency-probe.py` (archived here) logs raw(event1)+fix(event2) DOWNs on one
monotonic clock to measure touchfix latency (measured: 0 ms).

## 6. Slow tap response — diagnosis + applied poke fix
Symptom: correct key, but a ~1 s hold is needed; quick taps often do nothing.
Measured with a raw event1 capture (tap-timing-probe.py, 60 s) on the g2bde906a
desktop: only 3/8 taps reached the driver; the ones that did were 0.034 s,
0.983 s, 0.034 s contacts arriving in ~1 s samples (~0.19 fps contact frames).
A quick tap (<~100 ms) falls between controller samples and is lost; a ~1 s
hold spans a sample boundary. Root cause = DEGRADED/metronome delivery-mode
roll, sampling contacts at ~1 Hz. Input chain itself is fine (exact coords,
0 ms raw->fix latency).

APPLIED FIX (within current setup, no kernel switch): poke `0x10003058:6 -> 3`
in the usb-boot init's insmod line. TOUCH-STATE poke-sweep: with =3, "taps
register EVEN IN METRONOME CADENCE" (~0.6 clicks/s vs ~0.27 at =6; user
confirmed "responded well with the calculator"). =2 KILLS streaming — never use.
Rebuilt linux.bin sha de2ebaa3… (see §0). This replaces the earlier 07fec1f3….

RESULT of poke=3 boot: confirmed value applied (`/sys/module/apple_z2/
parameters/poke` = ...10003058:3...), but that boot landed a DEAD roll:
all 40 boot poll-kicks logged `D21 poll N: err=0 valid=0`, IRQ delta 0, zero
touch. So the roll is chosen at power-on by the PMU/hardware, NOT by poke;
no poke value rescues a dead roll. poke=3 is still kept because it makes taps
register in a *good/degraded* roll (per TOUCH-STATE). Recovery from a dead
roll needs a reset-pulse re-roll (d21-recover.sh / watchdog) or the Orchard
c2a38a5 kernel; the watchdog is currently masked here (it was flipping USB).

If =3 is still too slow, remaining documented candidates: 0x10003058 in
{5,7,12,24}; 0x1000305c in {1,4}. Change ONE value per boot, keep others fixed.
Real root fix remains Orchard kernel c2a38a5 ("idle is not dead"), NOT applied
by decision (staying on g2bde906a). Full evidence in ../d21-touch.md.

### Live re-roll attempts (over SSH, no PongoOS) — FAILED on a dead roll
When a boot lands DEAD (all 40 `D21 poll N: err=0 valid=0`, IRQ delta 0),
live recovery was tried via the on-p3 tools (`/root/gpioreset.py`, rmmod/insmod):
- short pulse (2 s rails-off): boot preamble `00 00 00 00`, no event1. FAILED.
- full pulse (30 s rails-off, docs say normally yields healthy): still
  `00 00 00 00`, no event1, IRQ delta 0. FAILED.
Conclusion: this stuck mode survives the GPIO reset pulse because the digital
core rail is not fully controlled by line 33 — needs a WHOLE-PMU cold start
(real power-cycle / PongoOS re-pwn). Do NOT hammer re-rolls (reload storm).
Live params are otherwise correct (pres_min=64, poke=3, verbose/N, frame/N);
the failure is purely the dead controller, not config. dmesg stays quiet
(grows 0 lines) and touchfix sits in its wait-loop — system stable.

## 7. Hard rules
- Local commits only. NEVER push to any remote.
- One boot per explicit "go"; bound every device command with `timeout`.
- Announce taking/returning the phone.
- Do NOT touch /home/doug/orchard-d21 or /home/doug/iPhOmarchy.
- Never read/write GPU/Fender/GFX registers; no AP writes to gate bank 0x235280000.
- Wi-Fi (brcmfmac/g_multi) is non-functional on D21 — leave it alone.

## 8. Known-good-kernel payload `d21-usb-boot-kg` (BUILT, not yet booted)
Root-cause fix for the dead/degraded roll: boot the KNOWN-GOOD kernel
`c2a38a5` (7.3.0-rc1-orchard-apple-16k) which has the "idle is not dead"
watchdog fix (patch 0009) — on g2bde906a an idle controller is treated as dead
and the rail is cycled every ~23 s (45 cycles/boot = the storm/phantom rolls).
- Worktree: `~/projects/OrchardLinux/trees/d21-c2a38a5` (detached c2a38a5db829).
- Payload: `~/omarchy-iphone/d21-usb-boot-kg/` = usb-boot init + kernel-matched
  module `0e933722…` (vermagic orchard-apple-16k) + native boot pokes
  (`10003058:6`, `poke_after=10003458:1`, pres_min=64, no diagnostic flags).
- Build: `orchard build d21-usb-boot-kg --device d21 --kernel-tree <d21-c2a38a5>
  --pongo "Known Good State/loaders/Pongo.bin"`.
- linux.bin sha `3a1012068ef5d78ef660382c2c60b0103cdaa36b0dd9cf767fb4aba8df94ae76`,
  pongo sha `1e5543fd8e6dbd84c334b87d71aa473f4d347c2ba8a5e863b6e10f18461c7575`.
- Keeps the USB-boot init (USB/SSH stable into desktop; masks watchdog+d21-touch
  in p3, touchfix wait-loop). This does NOT erase p3 (v0.3.1 stays installed).

### 8b. First kg boot hung in initramfs — FIXED (modules=true)
First kg build had `modules=false`, so the initramfs had no nvme-apple.ko ->
`mount /dev/nvme0n1p3 failed: No such file` -> stuck at `sh` (PID1), never
switch_root'd. Root SSH (ram key) could read /run/orchard/usb-boot.log to see it.
Fix: set `modules=true` in kg orchard.toml, rebuild (linux.bin 3a101206).
Kernel idle-fix was verified live on the stuck RAM shell: uname
7.3.0-rc1-orchard-apple-16k, `D21: recovery watchdog armed (quiet_ms=15000)`,
device "iPhone 8 Plus Touchscreen", pres_min=64, verbose/frame/poke_readback N.
NOTE: tablet SSH key rejected after v0.3.1 reinstall; use ROOT with ram key
(`~/.local/share/orchard/private/ram-ssh/id_ed25519`) until tablet keys fixed.

## 9. SUCCESS (2026-11-18): known-good kernel fixes touch — USE THIS PAYLOAD
Booted `d21-usb-boot-kg` (c2a38a5 idle-fix kernel, modules=true, linux.bin
3a101206) and reached the v0.3.1 desktop with stable USB/SSH (tablet user +
orchard key; root+ram key only works in RAM shell). Verified live:
- uname 7.3.0-rc1-orchard-apple-16k; `D21: recovery watchdog armed (quiet_ms=15000)`.
- event1 "iPhone 8 Plus Touchscreen", event2 virtual, touchfix active,
  pres_min=64, verbose/frame/poke_readback N.
- At idle IRQ delta=0 in 4s and dmesg quiet: NO rail-cycling storm.
- 45s raw event1 capture: 272 frames, 25 DOWN / 25 UP (every tap landed,
  no stuck contacts), correct coords. Durations min 0.098s / median 0.148s /
  max 0.315s; 84% were quick taps (<0.2s). Quick taps register immediately —
  the "must hold ~1s" symptom is GONE. USER CONFIRMED: "this works and got the desktop!"
ROOT CAUSE (finally): the old g2bde906a kernel's no-frames watchdog treated an
idle controller as dead and cycled the rail ~every 23s (45+ cycles/boot) —
the phantom/dead/degraded rolls and slow-tap symptom. The c2a38a5 idle-fix
watches IRQ edges + contact-down state and leaves a truly idle controller alone.
This is why "it should just work every time" needed the known-good kernel;
poke/pres_min/touchfix tuning alone could never fix it.
PREFERRED BOOT: `./bin/orchard run ~/omarchy-iphone/d21-usb-boot-kg --device d21 --no-build -y`
(from PongoOS). Preserves installed p3 (v0.3.1). No touchfix/watchdog changes
needed on p3 (init handles it). Reachable: tablet@172.16.42.1 via orchard ssh key.
