# D21: Wi-Fi, suspend/resume and the AOP (2026-11-26)

> **Merged:** all of this is in Orchard `main` now (PRs #251–#254, #257, #259–#261), and
> Orchard's kernel source moved to [OrchardLinux/linux](https://github.com/OrchardLinux/linux).
> These files are kept for reference only; build from a plain Orchard checkout.

These were the local patches for the iPhone 8 Plus (D21, T8015), in Orchard's old
`kernel/patches/devices/t8015/` layout. Each one was
validated on the device, built from Orchard v0.3.8 (`116004fb`).

| Patch | What it does | Result |
|---|---|---|
| 0021 | T8015 DART: uses the register layout of iOS's `AppleT8015DART`. It is T8020-like: TCR at 0x100, TTBR at 0x200, stream select 0x34, command 0x20 (invalidate 0x1002) and diag/reflector/fetch at 0x60/0x64/0x68. Before this, Linux used the S5L8960X offsets and translation setup failed with -5. | PCIe DMA works |
| 0022 | brcmfmac: BCM4357 (`14e4:440a`) support. rambase 0x170000, WCC_SEED, firmware name `brcmfmac4357-pcie`. **Reading the OTP at ChipCommon 0x8c0 resets the SoC**, so the OTP read is skipped. | Driver loads, NetworkManager connects, ping works |
| 0023 | D21 DTS: `brcm,board-type = "apple,pegasuse"`. | Firmware lookup works |
| 0024 | apple_z2 D21: the touch controller boots in the background after resume, from `complete()` on `system_dfl_long_wq`. | Screen lights about 0.3 s after the press; touch follows about 8 s later. It was 8 s for both before. |
| 0025 | AOP: adds the A11 AOP and its mailbox to `t8015.dtsi` and enables them on D21. `apple,t8015-aop` uses the A10 loader settings. | Firmware boots; see below |

The Wi-Fi firmware and NVRAM come from the IPSW and are not in this repo. Because
the OTP is skipped, the NVRAM is assumed to be Murata's (m-5.3 is used as
`brcmfmac4357-pcie.apple,pegasuse.txt`). That means the MAC address may not be
the phone's real one.

## Suspend/resume

s2idle suspend works, and a side-button press wakes the phone. This uses two
changes on the installed system (p3), in `desktop/orchard-main/p3/`.

**Why the phone used to look stranded after suspend.** The kernel did wake.
But `macsmc-input` swallows the KEY_POWER of the press that wakes it
(`wakeup_mode`). omarchy-powerd therefore saw "sleep ended, nothing pressed",
kept the screen dark and suspended again.

The fixes:

- **`powerd-buttonwake.py`** patches `/usr/libexec/omarchy-powerd`. After a
  sleep, a rise in the `macsmc-input` wakeup `event_count` counts as a power
  press. An omarchy-a package update overwrites this, so the script must be
  re-applied after updates.
- **`d21-wifi-sleep.service`** (WantedBy `sleep.target`) unloads brcmfmac
  before sleep and loads it again afterwards. Without it, every suspend aborts
  with -5: the BCM4357 never answers brcmfmac's D3 request.

**The old no-suspend workaround.** Before these fixes, an
`/etc/systemd/sleep.conf.d/90-d21-no-suspend.conf` drop-in and a powerd
stay-awake flag kept the phone from suspending at all, so it could never get
stranded. Both are now disabled.

The payload's RAM stage keeps `blacklist brcmfmac`
(`rootfs/etc/modprobe.d/d21-wifi-manual.conf`), because it has no Wi-Fi
firmware. The installed system loads brcmfmac normally.

**Temperature.** Wi-Fi does not make the phone warmer: the measured draw was
2.56 W with brcmfmac loaded and 2.57 W without.

## AOP and the Home button (work in progress)

> **Update, 2026-11-26: the Home button is parked.** The lock-ups in the later
> Touch ID handover tests were Linux claiming the AOP's GPIO interrupts (fixed in
> Orchard PR #254); the earlier `turtle` freeze was not re-tested. The AOP only reports
> clicks once the Touch ID sensor reports a finished reset, and that most likely needs
> the sensor's firmware patch from the Secure Enclave. The sensor itself works over SPI
> mode 2 and is now switched off at boot (Orchard PR #257). See the
> [front page](../../README.md#touch-id-and-the-home-button). The notes below are the
> state before that.

With patch 0025 and the AOP firmware from the IPSW (`aopfw-iphone10aop.im4p`,
not in this repo), the A11 AOP:

- boots to `AOP IS READY`, using the A10 loader and the ECID boot argument;
- finds its sensors (BMI262, HSCDTD601A, BMP284, CT709, VL62L0, and the
  AD7149 Home-button sensor);
- announces 26 EPIC services, including `aop-button` (endpoint 0x2d),
  `turtle` (0x2e) and `mesa` (0x2f).

The Home button's click logic is the `turtle` service: its firmware strings
include SSHBClickAlgs, "Click event" and "Finger detect". iOS drives it through
AppleSPUHIDDevice, whose HID reports go to AppleSPUButtonDriver.

Home-button status:

- **No reports yet.** Pressing Home sends nothing with listeners attached, and
  nothing after setting the report-interval properties (`aop-button` accepts
  key 0; `turtle` rejects keys 0x16, 0x5c and 0).
- **Raw EPIC calls froze the phone.** Sending raw calls to `turtle` locked up
  the whole kernel; the next boot's log will show which call. Next step: find
  the real enable sequence in iOS's AppleSPUHIDDevice code rather than guessing
  commands on the device.
