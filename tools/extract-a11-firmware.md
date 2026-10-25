# Extracting A11 (D21) Linux firmware

Adapted from [Pauli1Go/HoolockLinux-linux-firmware](https://github.com/Pauli1Go/HoolockLinux-linux-firmware)
(their `iphone7*.md` guides target A10). The A10 tooling (`makez2fw`, `hcdpack`) is reusable; the
**paths and offsets must be re-derived for A11**. Nothing Apple-proprietary is committed — these
steps run on the device owner's machine and output into the phone's `/lib/firmware`.

## Input

- iPhone 8 Plus (Global) `iPhone10,2`, **iOS 16.7.16 (20H392)** restore image:
  `https://updates.cdn-apple.com/2025FallFCS/fullrestores/122-76738/B6C604B4-548E-401F-BBFF-916E3FFDF235/iPhone_5.5_P3_16.7.16_20H392_Restore.ipsw`
  (~5.74 GB)
- [`ipsw`](https://github.com/blacktop/ipsw) (Arch: `ipsw_*_linux_x86_64.pkg.tar.zst`)
- `makez2fw` (from the A10 firmware repo, GPL-2.0-or-later; `make -C makez2fw`)
- `hcdpack` (Project Sandcastle `03db9c6a…`)

## 1. SmartIO firmware → `apple/t8015-smartio.bin`

The A10 guide reads the native `AppleT8010SmartIO` image out of the **kernelcache** at a fixed
offset (`0x02705000`, size `0x00088060`).

```
ipsw extract --kernel --device iPhone10,2 --output kc <IPSW>
# locate the AppleT8015SmartIO image inside kernelcache.release.* for D21
```

**A11 TODO:** the D21 kernelcache entry/offset differ. Approach: extract the kernelcache, then
scan for the SmartIO image (the A10 image starts with a recognizable header; `strings` for
`SmartIO`, or diff against the component list) to find the offset/size, then assert a SHA-256 so
extraction is deterministic (as the A10 guide does).

## 2. Touch firmware → `apple/dfrmtfw-d21-<personality>.bin`

`makez2fw` converts an Apple multitouch source into the **Z2FW** container the `apple_z2` driver
loads. A10 examples:

```
D11/D111:  makez2fw --dynamic-calibration 'C1F5E,2' D11.mtprops dfrmtfw-d111-c1f5e-2.bin
J172:      makez2fw 'K1F19,6' J172_Multitouch.mtfw syscfg.bin dfrmtfw-j172-k1f19-6.bin
```

For A11 the ADT multi-touch node gives the personality directly:
`hid-merge-personality = C1F5E,3` → so likely

```
ipsw extract --files --flat --pattern '(^|/)usr/share/firmware/multitouch/D21\.mtprops$' \
  --output touch <IPSW>
makez2fw --dynamic-calibration 'C1F5E,3' touch/.../D21.mtprops dfrmtfw-d21-c1f5e-3.bin
```

**A11 — CONFIRMED (2026-10-26).** `usr/share/firmware/multitouch/D21.mtprops` extracts cleanly
(264,559 bytes); `grep '<key>C1F5E'` shows **`C1F5E,3`** (and a `C1F5E,4`), matching the ADT
`hid-merge-personality`. `--dynamic-calibration` keeps per-device calibration out of the firmware;
the matching m1n1 work publishes it from the live ADT at boot.

## 3. Wi-Fi firmware (BCM4357)

A10 used `usr/share/firmware/wifi/C-4355__s-C0/…` (`sven`/`olaf` families) staged as
`brcmfmac4355-pcie.apple,<board>.bin/.clm_blob/.txcap_blob` + `…-PRNL-*.txt`.

**A11 — FOUND (2026-10-26).** On A11 the Wi-Fi blobs are **not** under `usr/share/firmware/wifi/`
(that is the A10 layout). They live in the DriverKit Wi-Fi driver:

```
System/Library/DriverExtensions/com.apple.DriverKit-AppleBCMWLAN.dext/Firmware/C-4357__s-B1/
```

Module-instance family **`C-4357__s-B1`**, chip name **`pegasus`** (matches ADT `wlan-pcie,bcm4357`).
Contents:

```
pegasuse[-JP].{trx,clmb,txcb}   # e = kernel/OS image
pegasusk.{trx,clmb,txcb}        # k = variant image
P-pegasus{e,k}[-JP]_M-GINS_V-{m,u}__m-{5.1,5.3,6.1}.txt   # 12 PRNL profiles
```

Extract with:

```
ipsw extract --files --flat \
  --pattern 'System/Library/DriverExtensions/com.apple.DriverKit-AppleBCMWLAN.dext/Firmware/' \
  --output wifi <IPSW>
```

Stage as `brcm/brcmfmac4357-pcie.apple,<board>.{bin,clm_blob,txcap_blob}` (+ `…-PRNL-*.txt`);
derive `<board>` from the A11 DT `brcm,board-type` and pick the `pegasus{e,k}` + PRNL profile to
match the OTP-selected module.

## 4. Bluetooth HCD → `brcm/BCM.apple,d21.hcd`

A10 extracts `usr/sbin/BlueTool` and uses `hcdpack` to pull the BCM4355C0 Patchram:

```
ipsw extract --files --pattern 'BlueTool' --output bt <IPSW>
# -> .../usr/sbin/BlueTool (9,760,944 bytes) + com.apple.BlueTool.plist
hcdpack bt/.../BlueTool 'C-4357__s-B1' <module> 'P-pegasus*_M-GINS_V-*__m-*' BCM.apple,d21.hcd
```

**Gotcha:** `ipsw --pattern` anchoring with `^…$` does **not** match — the paths it tests carry a
prefix, so the anchored `'^usr/sbin/BlueTool$'` finds nothing. Use a substring like `'BlueTool'`.

**A11 TODO:** ADT BT is `bluetooth,n88` (product 4768). BlueTool is extracted; the Wi-Fi/BT combo
module string / Patchram profile still need picking. The A11 Wi-Fi module is `pegasus` under
`C-4357__s-B1` (see §3), so the PRNL profiles `P-pegasus*_M-GINS_V-{m,u}__m-{5.1,5.3,6.1}.txt` are
the candidates; the OTP-selected vendor (Murata/USI) may need a first-boot `dmesg | grep 'OTP:
module='` to disambiguate (as the D11 guide does).

## Findings — 2026-10-25 (iPhone10,2, iOS 16.7.16 / 20H392)

Input IPSW downloaded and verified: 6,158,048,697 bytes.

### Touch source located, personality confirmed
- The IPSW ships **`Firmware/D21_Multitouch.im4p`** (and `D211_Multitouch.im4p`) — extract the DER
  `IM4P` payload (no LZFSE here) to get the MTFW. Both are 226,175 bytes and **identical** on disk.
- The payload is an XML **eplist** (starts `<dict><key>C1F5E,3</key>…`), i.e. personality
  **`C1F5E,3`** — matching the ADT `hid-merge-personality`. It contains `HBPP` firmware items,
  a Z2/SPI config, and calibration items.
- **Build — SOLVED.** The A11 MTFW schema differs from the A10-era tool in two ways:
  1. dynamic-calibration placeholders name the provider in **`<key>Property</key>`** (e.g.
     `multi-touch-calibration`) with the bound in **`<key>MaxSize</key>`**, where the tool looks
     for `Provider`/`Max Size`;
  2. a **`RequestCalibration`** action (no address) appears inside the HBPP sequence.

  [`../patches/0003-makez2fw-a11-mtfw-schema.patch`](../patches/0003-makez2fw-a11-mtfw-schema.patch)
  handles both. Result:

  ```
  makez2fw --dynamic-calibration 'C1F5E,3' D21_Multitouch.bin dfrmtfw-d21-c1f5e-3.bin
  → configs=0 init=1 blobs=9 rmw=6 calibrations=4 waits=1 skipped=1 payload=81038 bytes
  → 81,220 bytes, sha256 e2ff6d1c49e9d02df5de1bc74c804e1b80ab2025ba9c38636f67d8d8fa38a312
  ```

  The four dynamic calibrations (`multi-touch`, `orb-gap`, `orb-force`, `shape-dynamic-accel`)
  match the A10 guide exactly; their values are supplied at boot by m1n1 from the live ADT.
  Install as `apple/dfrmtfw-d21-c1f5e-3.bin` (do not commit — regenerate per device/SysCfg).

### `apfs-fuse` — BUILD SOLVED (2026-10-26)
`ipsw extract --files` mounts the iOS filesystem (APFS) and shells out to **`apfs-fuse`** (not in
the Arch repos; build from `github.com/sgan81/apfs-fuse`). With it built and on `PATH`,
`ipsw extract --files` reached all three targets.

Build recipe (CachyOS / GCC 16):

```
git clone https://github.com/sgan81/apfs-fuse && cd apfs-fuse
git submodule update --init 3rdparty/lzfse
# CMake 4.x rejects the old policy version:
cmake -S . -B build -DCMAKE_POLICY_VERSION_MINIMUM=3.5
# GCC 16 failure: ApfsLib/PList.h uses uint8_t without <cstdint>
#   (the 2026-10-25 note mis-diagnosed this as "PList.cpp:359 bin shadowed").
#   Fix: add  #include <cstdint>  to ApfsLib/PList.h
make -C build -j"$(nproc)"
# make apfs-fuse discoverable by ipsw without sudo:
ln -sf "$PWD/build/apfs-fuse" ~/.local/bin/apfs-fuse
ln -sf "$PWD/build/apfsutil"  ~/.local/bin/apfsutil
```

Notes: needs `cmake` + `fuse3` (do **not** install `zlib` on CachyOS — it conflicts with the
`zlib-ng-compat` drop-in; zlib is already provided). Point `TMPDIR` at real disk when extracting —
`/tmp` is a RAM-backed tmpfs and `ipsw` stages the multi-GB fs DMG there. Only `PList.h` needed
changing for GCC 16; no other missing-`<cstdint>` header actually failed to compile.

### SmartIO firmware — SOLVED
The SmartIO firmware is a raw ARM64 image embedded in `__PRELINK_DATA` of the (decompressed)
prelinked kernelcache; its first 32 bytes are the boot vector table, **unique** in the
kernelcache. Its length comes from the kext's `{address,length}` descriptor.

[`extract-smartio.py`](extract-smartio.py) automates this. A11 result:

```
python3 extract-smartio.py kernelcache.release.iPhone10,2_5 t8015-smartio.bin
→ __PRELINK_DATA, file 0x2ccf000, runtime 0xfffffff007b0b000, size 616336 (0x96790)
→ sha256 8c3bbf8ffa1eb7d8864e9bdaa2242ba8fdbc953dca8ccb367bbbf5b0b3717517
```

The same tool reproduces the A10 image exactly (`0x88060`, sha256 `408adbb0…`), which validates
the method. (No `apfs-fuse` needed — the kernelcache is a top-level IPSW ZIP entry, fetchable by
HTTP range.) Install as `apple/t8015-smartio.bin` (regenerate/verify per device; not committed).

### Extracted so far (kept locally, not committed)
`a11-fw/kc/…/kernelcache.release.iPhone10,2_5` (51 MB, from `kernelcache.release.iPhone10,2`),
`a11-fw/out/D21_Multitouch.bin`, `a11-fw/out/D211_Multitouch.bin`,
`a11-fw/out/dfrmtfw-d21-c1f5e-3.bin`, `a11-fw/out/t8015-smartio.bin`.

Filesystem extraction via `ipsw extract --files` (2026-10-26), into `a11-fw/extracted/`:

```
touch/D21.mtprops                                             264,559 B
bt/usr/sbin/BlueTool                                        9,760,944 B
bt/…/com.apple.BlueTool.plist                                     269 B
wifi/…/Firmware/C-4357__s-B1/pegasus{e,k}[-JP].{trx,clmb,txcb}  ~3 MB
wifi/…/Firmware/C-4357__s-B1/P-pegasus*_M-GINS_V-*__m-*.txt
```

## 5. Private calibration (never commit)

`WMac`, `WCAL`, `BMac` (and A11 touch calibrations) come from **the specific phone's** SysCfg and
must remain private. The A10 `m1n1` publishes these into the Linux DT at boot via
`tools/make_syscfg_payload.py`; we need the A11 equivalent.

## Install (on the phone's rootfs / initramfs)

```
/lib/firmware/apple/t8015-smartio.bin
/lib/firmware/apple/dfrmtfw-d21-<personality>.bin
/lib/firmware/brcm/brcmfmac4357-pcie.apple,<board>.{bin,clm_blob,txcap_blob}
/lib/firmware/brcm/BCM.apple,d21.hcd
```

Firmware must be present **early** (initramfs) for touch to probe on a cold boot.
