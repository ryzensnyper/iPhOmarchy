# JADE Known Good State — D21 (iPhone 8 Plus, A11/T8015)

The last verified-working D21 configuration: **Omarchy-A v0.3.1 desktop with
reliable, quick touch**, reached 2026-11-18. Local record; pushed to iPhOmarchy
`GPU-WIP/jade/` on `main`. No Apple binary blobs or device-private calibration
data are stored here (hashes and text scripts only).

## Why this is "known good"
Touch "worked, but only if you pressed and held ~1 s" and produced phantom/dead
rolls on the old `g2bde906a` kernel. Root cause (proved, not guessed): that
kernel's apple_z2 **no-frames watchdog treats an idle controller as dead** and
cycles the touch rail ~every 23 s (45+ cycles/boot). The **known-good kernel
`c2a38a5` (7.3.0-rc1-orchard-apple-16k)** has the "idle is not dead" fix
(kernel patch 0009): it leaves a genuinely idle controller alone and fires only
when a frame is actually owed (IRQ edge or contact down). Booting that kernel
made touch just work — **every quick tap landed, no hold needed, no storm.**

Proof (45 s raw evdev capture, 2026-11-18): 272 frames, **25 DOWN / 25 UP**,
correct coordinates, no stuck contacts; 84% of taps were quick (<0.2 s), median
148 ms. At idle: IRQ delta 0 in 4 s and dmesg quiet — no rail cycling.

## Pinned configuration (exact)
- Installed root: Omarchy-A **v0.3.1**, release `dev-20261116-113113`,
  p3 root UUID `6ef80700-1338-48aa-be57-eba02269c2e1`.
  Account `tablet`, sudo password `omarchy!`, lock PIN `000000`.
- Boot kernel: **7.3.0-rc1-orchard-apple-16k** (commit `c2a38a5db829d9cd83dde69c1e0d22566a1e119d`,
  worktree `~/projects/OrchardLinux/trees/d21-c2a38a5`).
- Touch driver: `apple_z2.ko` sha `0e933722c393d4e2947bb5756a2bd246678526c10339c2d5f1893758e6fd9770`
  (vermagic orchard-apple-16k, from that kernel tree; has `d21_last_irq`/`quiet_ms` idle fix).
- Boot payload `~/omarchy-iphone/d21-usb-boot-kg/out/apple-16k/`:
  `linux.bin` sha `3a1012068ef5d78ef660382c2c60b0103cdaa36b0dd9cf767fb4aba8df94ae76`,
  `pongo.bin` sha `1e5543fd8e6dbd84c334b87d71aa473f4d347c2ba8a5e863b6e10f18461c7575`.
  (Blobs are NOT in this repo — build/rebuild from the projects below.)
- Device: iPhone 8 Plus (D21), ECID `65d2c0408002e`, USB `3-3`.
  PongoOS `05ac:4141`, payload gadget `05ac:4144`. Host `enp13s0f3u3`
  `172.16.42.2/30`, phone `172.16.42.1`.
- SSH into the desktop: `tablet@172.16.42.1` with
  `~/.local/share/orchard/private/ssh/id_ed25519`. (In the RAM shell before
  switch_root, use `root@172.16.42.1` with `.../ram-ssh/id_ed25519`.)

## Exact boot procedure (repeatable)
Phone in PongoOS, then:
```sh
cd /home/doug/orchard
./bin/orchard run /home/doug/omarchy-iphone/d21-usb-boot-kg --device d21 --no-build -y
```
Wait ~40 s for SSH / desktop. Clear the RAM host-key cache between boots if
using the ram key: `: > ~/.local/share/orchard/private/ram-ssh/network_known_hosts`.

Verify (over SSH):
```sh
uname -r                        # 7.3.0-rc1-orchard-apple-16k
cat /proc/1/comm                # systemd (confirms switch_root into p3)
cat /sys/class/input/event1/device/name   # iPhone 8 Plus Touchscreen
cat /sys/class/input/event2/device/name   # d21-touchfix virtual touchscreen
systemctl is-active d21-touchfix           # active
dmesg | grep "watchdog armed"              # D21: recovery watchdog armed (quiet_ms=15000)
```

## How the payload works (files in `jade/`)
`usb-boot-init.sh` (payload `/init`, exact copy) does, in order:
1. Mount proc/sys/dev/pts/run; `sh /usr/libexec/orchard/usb-session` — sets up the
   USB gadget (0x4144) + dropbear so USB/SSH survive the handover into the desktop.
2. Stage 6 firmware blobs to `/lib/firmware/apple`.
3. `insmod /apple_z2.ko write=70:08 poll=1 probe_times=40 pres_min=64
   poke=10003060:17d3,1000305c:2,10003058:6,10003000:3,10003518:1 poke_after=10003458:1`
   — the matched driver's own C1F5E,4 fwconfig boot sequence; NO poke_readback /
   verbose / frame_dump (quiet). Idle silence is safe on this kernel.
4. Tuned latch params: tool_max 3000, tool_area_max 5000000,
   tool_area_release 2000000, tool_area_hard 12000000.
5. Wait for event1; modprobe nvme (module tree is REQUIRED — `modules = true` in
   orchard.toml); mount p3 rw at /newroot; stage firmware + module tree into p3.
6. On p3: mask d21-touch + d21-touch-watchdog (driver already up, idle fix in
   kernel); write `/root/touchfix-wait.sh` (waits for event1 then execs touchfix
   v2) + d21-touchfix.service (Restart=always).
7. Kill RAM processes, mount --move dev/proc/sys/run, `exec switch_root`.

`usb-boot-orchard.toml` = `modules = true, firmware = true, transport = true`.

Rebuild payload (needs the worktrees/projects listed above; no binaries in git):
```sh
cd /home/doug/orchard
./bin/orchard build /home/doug/omarchy-iphone/d21-usb-boot-kg --device d21 \
  --kernel-tree /home/doug/projects/OrchardLinux/trees/d21-c2a38a5 \
  --pongo "/home/doug/Known Good State/loaders/Pongo.bin"
```

## Steps that led here (kept concise, in order; for repeatability)
1. Reinstalled v0.3.1 into p3 via `orchard install .../dev-20261116-113113/index.toml`
   (prompts: Y → password `omarchy!` ×2 → PIN `000000` ×2 → allow SSH Y →
   choose partition 1 → type `erase 3`). Expected "Could not confirm it started"
   timeout on T8015 — harmless.
2. Built a USB-boot RAM payload so USB/SSH survive into the installed desktop
   (plain direct-boot has no initramfs → gadget dies). Root cause of the earlier
   USB loss: no `usb-session` before switch_root.
3. Kept the v0.3.1 touch chain on p3: driver + touchfix **v2** (sha
   `20a7a29fb8a5fc860b5f3cee48f41daa92df4d2c831c4b1fb2f84543ceb932a8`) + udev
   bench rule + tuned latch params. touchfix waits for event1 so it never fails
   with "open source: No such file".
4. Diagnosed slow taps with a raw evdev timing capture: quick taps fell between
   the controller's ~1 s samples; a ~1 s hold spanned a sample. Poke/pres_min /
   touchfix tuning could only partially help — the roll is chosen at power-on.
5. Root-caused to the old kernel's idle watchdog and switched the boot kernel to
   `c2a38a5` (idle fix) — this is THE fix that made touch reliable.
   (First kg build hung in initramfs: `modules = false` omitted nvme-apple →
   `mount /dev/nvme0n1p3 failed`; fixed with `modules = true`.)
6. Verified: quick taps register, no hold, no storm, desktop stable — user confirmed.

## Tools (text, in `jade/`)
- `d21-touch-decode.py` — decode a raw evdev capture to taps with coordinates.
- `tap-timing-probe.py` — raw(ev1)+fix(ev2) DOWN/UP with timestamps on one clock
  (run as root on device; output to /tmp; pull with `cat` over ssh — scp/sftp-server
  is not installed on device).

## Hard rules / notes
- Local edits then explicit push to iPhOmarchy `GPU-WIP/` on `main` only.
- NO Apple binary blobs, firmware, cal bytes, or linux.bin/pongo in git
  (.gitignore excludes `*.bin`, `*.dtb`, `*.log`; `.ko` is NOT ignored — never add one).
- Wi-Fi (brcmfmac/g_multi) is non-functional on D21 — leave it alone.
- Never read/write GPU/Fender/GFX registers or gate bank `0x235280000`
  (GPU bring-up is the separate `GPU-WIP/` work).
- Device-private PxCl / calibration bytes stay OFF public repos.
- Full raw notes: orchard repo `docs/bring-up/d21-touch.md` and
  `docs/bring-up/d21-current-setup/RUNBOOK.md` (local commits).
