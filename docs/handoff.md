# HANDOFF — Omarchy on iPhone 8 Plus (D21 / A11) — continue here

Written 2026-10-26. Supersedes `checkm8-kit/HANDOFF-2026-10-25.md` (that one covered only
jailbreak + dual-boot, now done). Read this top to bottom before touching anything.

## Mission

Run a usable **Omarchy-flavoured Linux** on an **iPhone 8 Plus (D21 / Apple A11 / T8015)**,
dual-booting with iOS. iOS must stay intact — it is the only route into DFU/checkm8.

## ⚠️ Read this first — the host was deliberately "un-tuned"

The previous session ended by **reverting** privileged host changes. As of now:

- **`sudo` requires a password** (passwordless sudo was removed: `/etc/sudoers.d/` is empty).
  You cannot run privileged steps until the user re-grants access (or types it). Ask the user.
- No `apple_mfi_fastcharge` blacklist (`/etc/modprobe.d/` has no apple files).
- Things that *stay* installed: `usbmuxd`, `libimobiledevice`, `sshpass`, `ipsw` (3.1.739),
  `cmake`, `fuse3`, `bc`, `clang`/`lld`, `dtc`, `python-construct`, `python-pyusb`.

**Do NOT re-register a hand-rolled `qemu-aarch64` binfmt entry** — that broke x86_64 exec on this
box last time and required a hard reboot. If aarch64 emulation is ever needed, use the packaged
`systemd-binfmt` route.

## Device & host

- Device: iPhone 8 Plus (Global) `iPhone10,2`, D21AP, iOS 16.7.16 (build 20H392).
- Host: CachyOS, kernel `6.18.48-1-cachyos-lts`, x86_64. Working dir `/home/doug`.
- **Current live state (2026-10-26 09:52):** phone is **running Hoolock Linux**
  (`05ac:4142`), reachable at `172.16.42.1` (ssh `alarm` / password `alarm`). Host up 15 h.

## What already works (M0)

- **checkm8 / palera1n jailbreak**, tethered, reproducible.
- **Dual-boot:** iOS on `/dev/nvme0n1p1` (APFS), Arch Linux ARM on `/dev/nvme0n1p2` (ext4);
  Linux boots from the internal partition via pongoOS → m1n1 → Hoolock kernel `7.3.0-rc1`.
- **SPI1 controller** brought up (project's own DT work) — `patches/0001`.
- **Full A11 hardware map** decoded from the Apple Device Tree — `omarchy-iphone/HARDWARE.md`
  and `hardware/adt-d21-peripherals.txt`.
- **A11 firmware** (partly) extracted + reproducible — see below.

The published repo has everything: **https://github.com/ryzensnyper/iPhOmarchy**

## The goal's long pole

Wi-Fi, Bluetooth, **touch** and GPU are **not supported by upstream Hoolock** on any
iPhone/iPad (GPU + display-pipe are TBA). The de-risking reference is
**[Pauli1Go/HoolockLinux](https://github.com/Pauli1Go/HoolockLinux)** — a working **A10 (T8010)**
bring-up (iPhone 7 Plus / iPad 7) with touch, Wi-Fi and BT. Our A11 touch is the **same `k1`
family** (`hid-transport,k1`; their J172 fw is `…-k1f19-6`), so their stack is the port base.

## Local paths (this machine)

| Path | What |
|---|---|
| `~/iPhOmarchy` | the published repo (working copy) |
| `~/omarchy-iphone` | planning docs: `PLAN.md`, `HARDWARE.md`, `adt/`, `tools/`, this file |
| `~/checkm8-kit` | jailbreak + dual-boot kit (palera1n, payloads, `linux-kit/`, rootfs.ext4) |
| `~/hoolock/linux` | upstream Hoolock kernel tree (`6831bc701`) with our DT edits (spi1, uart1) |
| `~/hoolock-pauli` | Pauli1Go A10 fork (the port reference) |
| `~/hoolock/docs` | Hoolock docs (features/A11.md, config_16k, SETUP) |
| `~/a11-fw` | A11 work: IPSW, kernelcaches, `firmware/` (makez2fw), **`out/`** (firmware) |
| `~/a11-fw/out` | `t8015-smartio.bin`, `dfrmtfw-d21-c1f5e-3.bin`, `D21_Multitouch.bin`, `D211_…` |

## Reproduce the two essential flows

### A. Pwn + boot Linux (needs a password for sudo)
```sh
# phone on iOS. palera1n NEEDS usbmuxd running (opposite of checkra1n).
sudo systemctl start usbmuxd
cd ~/checkm8-kit && tmux new -s pwn 'sudo ./palera1n -p -v'
# attach, press Enter, then DFU gesture: VolUp tap, VolDown tap,
#   hold Side till screen black, add VolDown ~5s, release Side, keep VolDown ~10s
# at pongoOS> (05ac:4141): quit palera1n (Ctrl-C); ensure nothing holds the device
cd ~/checkm8-kit/linux-kit
printf '/send m1n1-linux-p2.bin\nbootm\n' | sudo ./pongoterm   # or m1n1-linux-p2-<tag>.bin
# ~60 s later 05ac:4142, ssh alarm@172.16.42.1 (pw: alarm)
```
Notes: `checkra1n-0.1337.3` **never** wins the race on this host — use palera1n. Ending a shell
call can kill the tmux server; a dead tmux does **not** undo a successful pwn (PongoOS runs on the
phone). `cleanup.sh` kills leftovers by `/proc/<pid>/comm`.

### B. Edit the device tree and rebuild a payload (no kernel rebuild, no heat)
```sh
cd ~/hoolock/linux                        # edit arch/arm64/boot/dts/apple/t8015.dtsi
make -j$(nproc) LLVM=1 ARCH=arm64 dtbs
cp arch/arm64/boot/dts/apple/t8015-d21.dtb ~/checkm8-kit/linux-kit/step6/d21-boot.dtb
cd ~/checkm8-kit/linux-kit/step6
BOOTARGS="root=/dev/nvme0n1p2 rootwait rw console=tty0" ./make-blob.sh ../m1n1-linux-p2-<tag>.bin
# then boot it via flow A
```

### C. Regenerate A11 firmware (no pwn; needs `ipsw`, internet)
```sh
cd ~/a11-fw
# SmartIO (from the kernelcache; no apfs-fuse needed)
python3 ~/iPhOmarchy/tools/extract-smartio.py \
  kc/20H392__iPhone10,2/kernelcache.release.iPhone10,2_5 out/t8015-smartio.bin
#   -> 616336 bytes, sha256 8c3bbf8ffa1eb7d8864e9bdaa2242ba8fdbc953dca8ccb367bbbf5b0b3717517
# Touch Z2FW (needs the makez2fw A11-schema patch, already applied in ~/a11-fw/firmware)
firmware/makez2fw/makez2fw --dynamic-calibration 'C1F5E,3' \
  out/D21_Multitouch.bin out/dfrmtfw-d21-c1f5e-3.bin
#   -> 81220 bytes, sha256 e2ff6d1c49e9d02df5de1bc74c804e1b80ab2025ba9c38636f67d8d8fa38a312
```
Recipes: `~/iPhOmarchy/tools/extract-a11-firmware.md`, `tools/README.md` (ADT decode).

## Where to continue (priority order)

1. **Unblock filesystem extraction** (issue #7): finish building **`apfs-fuse`** so `ipsw extract
   --files` can reach `usr/share/firmware/wifi/C-4357…/`, `usr/sbin/BlueTool`, `…/multitouch/`.
   Status: `cmake -DCMAKE_POLICY_VERSION_MINIMUM=3.5 ..` gets past CMake 4; then **GCC 16** fails
   at `ApfsLib/PList.cpp:359` (`bin` shadowed / non-class type). It's a small upstream patch.
2. **Driver port** (issues #1–#4), on a branch:
   - t8015 **touch clock** (`clk-apple-t8010-touch.c` → add t8015 PMGR offsets)
   - **SmartIO + SIO-DMA** for `iop,t8015` (ADT `sio@2EE00000`, IRQ 308–311) + `apple-sio-core.c`,
     `apple-sio-dma.c`
   - merge their **T8010 `spi-apple.c`** (DMA, word sizes); add a D21 multi-touch node
     (ADT `hid-transport,k1`, SPI1 @0x2E404000 IRQ 292)
   - port **`apple_z2.c`**; wire the A11 firmware names
   - **m1n1**: A11 touch-calibration + NVMe-HMB injection (their patched m1n1 does this for A10)
3. **Bluetooth** (#5): uart1 node exists (`patches/0001`, unverified) + `hci_bcm` binding for
   `bluetooth,n88` + `.hcd`.
4. **Wi-Fi** (#6): port `pcie-apple-h9p.c` → `apcie,t8015` (ADT ECAM `0x61000000`, IRQ 340–349)
   + `brcmfmac` BCM4357.
5. **GPU** — out of scope (no mainline driver; upstream TBA).

## Gotchas

- **palera1n needs `usbmuxd` RUNNING**; checkra1n wants it gone. `tune.sh` stops usbmuxd — don't
  run it as-is when using palera1n.
- `palera1n -p` holds USB interface 0 while its shell runs → Ctrl-C before `pongoterm`.
- The **ADT from the IPSW is a template** (identity fields are `syscfg` references). Per-device
  calibration (`MtCl`, `WMac`, `WCAL`, `BMac`, `LSCI`) needs a **live retrieve** via m1n1
  (`python -m m1n1.adt --retrieve`) or the device's SysCfg — keep it private, never commit.
- **Never commit** Apple firmware, IPSWs, `rootfs.ext4`, or per-device calibration. Repo
  `.gitignore` guards this.
- iOS must remain bootable (dual-boot invariant). Only ever write `/dev/nvme0n1p2`.
- Host USB state can wedge after many exploit cycles (checkra1n symptoms); a PC reboot clears it,
  but palera1n is the working exploit here.

## References

- Repo: https://github.com/ryzensnyper/iPhOmarchy (docs/, patches/, tools/, hardware/)
- Hoolock: github.com/HoolockLinux/{linux,docs,m1n1} (branch `hoolock` / `idevice`)
- Port reference: github.com/Pauli1Go/HoolockLinux (+ `-bringup-docs`, `-linux-firmware`, `m1n1`)
- Community: henrikklee (Omarchy on iPad 6, `labwc`), ivan.codes (Omarchy on a phone via postmarketOS)
- Asahi ADT docs; palera1n; checkra1n/pongoOS
