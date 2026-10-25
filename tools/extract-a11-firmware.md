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

**A11 TODO:** confirm the exact `.mtprops` filename/path and the personality string by inspecting
the extracted file (`grep '<key>C1F5E'`). `--dynamic-calibration` keeps per-device calibration out
of the firmware; the matching m1n1 work publishes it from the live ADT at boot.

## 3. Wi-Fi firmware (BCM4357)

A10 used `usr/share/firmware/wifi/C-4355__s-C0/…` (`sven`/`olaf` families) staged as
`brcmfmac4355-pcie.apple,<board>.bin/.clm_blob/.txcap_blob` + `…-PRNL-*.txt`.

**A11 TODO:** the A11 Wi-Fi is **BCM4357** (ADT `wlan-pcie,bcm4357`), so the source dir is a
`C-4357…` family with its own module-instance name. Extract the `.trx`/`.clmb`/`.txcb` + PRNL
files and stage them under `brcm/brcmfmac4357-pcie.apple,<board>.*`. Determine `<board>` from the
A11 DT `brcm,board-type`.

## 4. Bluetooth HCD → `brcm/BCM.apple,d21.hcd`

A10 extracts `usr/sbin/BlueTool` and uses `hcdpack` to pull the BCM4355C0 Patchram:

```
ipsw extract --files --pattern '^usr/sbin/BlueTool$' --output bt <IPSW>
hcdpack bt/.../BlueTool 'C-4357__s-C0' <module> 'M-PRNL_V-m__m-5.7' BCM.apple,d21.hcd
```

**A11 TODO:** ADT BT is `bluetooth,n88` (product 4768). Identify the Wi-Fi/BT combo module string
and the Patchram profile; the OTP-selected vendor (Murata/USI) may need a first-boot `dmesg | grep
'OTP: module='` to disambiguate (as the D11 guide does).

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
