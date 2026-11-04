# Orchard upstream sync — session 5 (2026-11-04), 148 new commits since our last fetch

Checked per the session directive: "check orchard-linux for any new hardware
additions / patches / bring-up info that may assist our A11 hardware — before
continuing, make sure nothing crucial is being missed." Local clone `~/orchard`
(OrchardLinux/orchard), fetched to origin/main.

## The headline: iPhone X (D221, iPhone10,6) is now an upstream device

Same SoC as our iPhone 8 Plus (T8015/A11). `devices/d221/` = device.toml (BDID
match, checkm8-pongo boot, platform `apple-16k`, dtb `t8015-d221`) +
`firmware.json` (Wi-Fi recipe) + `docs/bring-up/d221-bringup.md` (their RAM
boot reaches a USB serial shell; USB = `dwc2` device mode via
`configfs-gadget.minimal-boot`; RTC = `rtc-apple-pmic` REGISTERS AND SETS THE
CLOCK — our stale-clock issue has an upstream answer).

Our D21 remains the first **Z2** iPhone upstream (the X's touch is
`hid-transport,k1`, not Z2) — our apple_z2 PR defines the Z2 path.

## Wi-Fi (the handoff's next-step #6) — the upstream path is COMPLETE for T8015

- Merged: `PCI: apple-h9p: Add T8015 support` (de95753),
  `PCI: apple-t8010-pcie: Add the T8015 variant` (in 66e711c's series),
  T8015 PCIe DARTs + host bridge + `iommu: apple-dart T8015 compatible`,
  `PCI: pwrctrl: apple-wifi: Match the BCM4357` (66edac2),
  `arm64: dts: apple: t8015: enable the D221 PCIe and power the Wi-Fi
  endpoint` (6b2ad2c).
- **Our 8 Plus uses the SAME chip**: live ADT line 7594
  `compatible = [wlan-pcie-uart,bcm4357, wlan-pcie-uart,bcm]` under the
  `apcie,t8015` controller (adt.txt 9221), `module-instance = pegasuse`
  (vs the X's `herculesk`), `function-pcie_port_control = 175:PrtC(0xb2)`.
  Firmware branch differs: `C-4357__s-B1/pegasuse.{trx,clmb,txcb}` + the GINS
  NVRAM profiles from OUR iPhone10,2 20H392 IPSW — same recipe shape as their
  sha-pinned d221 firmware.json (DriverKit-AppleBCMWLAN.dext paths).
- TODO: write the extraction recipe into `~/iPhOmarchy/tools/` (IPSW paths +
  sha256), adapt the d221 Wi-Fi DT patches for the D21 ADT facts.

## USB regressions (the reload link-deaths + g_multi -22)

- **g_multi -22 at t=0 (3/3 boots) — root cause CONFIRMED locally**: the
  rootfs `usb-gadget.service` orders only `After=sys-kernel-config.mount`,
  and `usr/local/sbin/usb-gadget.sh` does a SINGLE `ls /sys/class/udc` — it
  loses the race to the dwc2 probe (g_multi is builtin and fails its own bind
  first). FIX WRITTEN: bounded 10-s UDC wait loop
  (`/tmp/opencode/usb-gadget-fixed.sh`, staged for push + deploy after the
  dance; verify the live script matches the template first).
- **Runtime reload deaths (3/5 cut-skipped)**: our hoolock kernel LACKS
  Orchard's dwc2-gadget robustness series (their apple-16k
  `kernel/patches/drivers/usb/`): 0001 `dwc2: enter L0 before calling the
  resume callback`, 0002 `f_ecm: resend a notification that failed to send`
  (matches our death signature: gadget enumerated, IP dead), 0003-0005
  (usb-psy/VBUS/current reporting), 0006-0007 (role/charger + the J71b
  B-valid pull-up fix). Both 0001/0002 are builtin-driver patches → porting
  means a KERNEL + payload rebuild (not a module swap); queued.
- **PMP (§1M lead)**: upstream has T8015 PMP patches formatted FOR hoolock
  (`kernel/patches/hoolock/080-pmp/`: DT binding, `soc: apple: Add T8015 PMP
  driver` (Nick Chan — RTKit firmware boot, "reduces iPhone X power by half
  a watt"), DTS nodes with `firmware-name = "apple/pmp-t8015.bin"`). Our
  kernel ALREADY has the driver (the probe ran and asked for the .bin). The
  firmware is a KNOWN GAP upstream (d221-bringup.md: "still to be extracted";
  also `apple-pmgr-pwrstate: sync_state() pending due to 232300000.pmp`).
  When it lands: the PMP domain becomes kernel-managed and the
  touch-rail-is-PMP-private theory becomes testable (do touch reloads stop
  killing USB?).

## Other A11-relevant upstream work (port candidates, queued)

- `kernel/patches/hoolock/040-dialog/`: Dialog PMIC nodes for T8015 (0017) +
  RTC drivers (0003, 0018/0019 Calpe) — the clock-set path.
- `kernel/patches/hoolock/070-smc/`: 21 patches — A11/T2 SMC DT, macsmc
  input/hid (volume/power buttons), macsmc_power A11 support, T8015
  reboot/poweroff.
- `kernel/patches/hoolock/020-pmu/` + `030-perf/`: A11 CPU PMU nodes + events.
- `kernel/patches/hoolock/010-usb/`: the full Apple USB stack for hoolock
  (dwc2 A7-A11 params, USB complex bus, AUSB PHY, OHCI/EHCI/xHCI bindings)
  + `050-usb-dt/0009` (t8015 USB nodes).
- m1n1 `824bf03`: release the NVMe boot-from-host strap after a USB-started
  iBoot — our boot chain IS one; may matter for NVMe stability.
- T8010 suspend fix (bq27xxx on the freezable workqueue) — HDQ-gauge class.
- `3850ef2`: don't write system time back to the PMIC RTC.

## Orchard PR status (affects our PR plan, next-step #5)

#57 (J81 touch family-22) and #60 (J81 SPI full-duplex) are MERGED, with the
apple_z2 patches REWORKED to the kernel layout (47b6d11, 1a2ae3a) and
Signed-off-by added (272a7c7). The match-data convention is now in main.
Our D21 PR must rebase onto `kernel/patches/drivers/input/`'s reworked
apple_z2 series, convert `apple_z2_is_d21()` checks to a `d21_info`
match-data struct, and follow their commit/test conventions
(patches/orchard-ref/pr60-pr57-j81-vs-d21.md).

## D21 Wi-Fi deep-dive (session 5, same day) — the concrete gap list

Kernel coverage checked against our payload tree (`~/hoolock/linux`):

- `CONFIG_PCIE_APPLE_H9P=y` — the h9p host-bridge driver is BUILT-IN and
  compiled (pcie-apple-h9p.o present). The T8015 PCIe controller side may
  already be substantially in our lineage; diff vs the orchard
  `kernel/patches/devices/t8015/` series (clocks-as-gates 0002, DARTs 0003,
  host bridge 0004, Wi-Fi port 0005) before porting anything.
- `CONFIG_PCI_PWRCTRL_APPLE_WIFI=y` — the BCM4357 endpoint power-lifecycle
  driver (orchard 66edac2) is BUILT-IN and compiled.
- brcmfmac: in-tree WITH the apple module-instance naming code
  (brcmfmac/pcie.c builds board_type lists from DT board_type + chip OTP;
  example name `apple,shikoku-RASP-m-6.11-X3`), but **CONFIG_BRCMFMAC /
  CFG80211 / MAC80211 are NOT SET** in the payload .config. Fast path:
  build cfg80211 + mac80211 + brcmutil + brcmfmac as MODULES (vermagic
  swap, no payload rebuild), insmod in dependency order.
- **Firmware EXTRACTED** (~/a11-fw/wifi-d21/, sha-pinned, never committed):
  pegasuse.{trx,clmb,txcb} + the two matching GINS NVRAM profiles from OUR
  20H392 rootfs (the apfs-mnt was already mounted). Recipe committed as
  `tools/firmware-d21-wifi.json` (d221-schema, hashes + paths only — the
  bytes are Apple's). The brcmfmac request name is decided at probe time
  (DT board_type + OTP) — read the probe log and symlink if it differs
  from `brcmfmac4357-pcie.apple,pegasuse.*`.
- **DT facts from the live ADT**: reg_on = SMC `gP0e` (the IDENTICAL SMC
  GPIO 14 the d221 patch drives via `apple,smc-gpio`), device-wake = gpio4
  (the wlan event GPIO), `module-instance = pegasuse`,
  `compatible = [wlan-pcie-uart,bcm4357, wlan-pcie-uart,bcm]` under
  `apcie,t8015`, `function-pcie_port_control = 175:PrtC(0xb2)`. The d221
  endpoint patch (t8015-x.dtsi: root-port node + `wifi@0,0` +
  regulator-fixed from smc_gpio 14 + device-wake) is the template.
- Precedent: the D11 (iPhone 7) recipe in `~/a11-fw/firmware/iphone7.md`
  already verified BCM4355 `olaf` station-mode WPA2 with
  `firmware/tools/makebrcmfw.py` — same shape, proven in-house.
- **The gate: the DTB.** The Wi-Fi port/endpoint/regulator nodes live in
  the payload's DTB → one payload rebuild carries the Wi-Fi DT **and** the
  USB robustness patches (f_ecm resend, dwc2 L0) **and** optionally the
  PMP DT node (driver ready, firmware pending). One rebuild, three wins.

## PMP firmware — parked with a precise lead

`apple/pmp-t8015.bin` is NOT a file in the IPSW (Firmware/ carries AOP,
Callan, Multitouch, baseband, SE/Stockholm, all_flash only) and the
rootfs `/usr/standalone/firmware` has only SmartIO/nfrestore/SLAM. The
PMP image is baked into **iBoot** (`Firmware/all_flash/
iBoot.d21.RELEASE.im4p`, iBoot-8422.142.2.700.1, extracted to
/tmp/opencode/iboot-d21.im4p → payload 1,092,976 B) which is **GID-key
encrypted** — `ipsw img4 im4p extract --lookup` has no key for type
`ibot` (theapplewiki lacks it). Extraction = a checkm8-path RE
sub-project, OR ask Nick Chan (towinchenmi) upstream how his
pmp-t8015.bin was produced. Driver + DT are ready upstream
(kernel/patches/hoolock/080-pmp/); our kernel already carries the driver.

## Wi-Fi bring-up — LIVE PROGRESS to the h9p PHY wall (dances #17/#18, same day)

Dance #17 (the wifi payload) exposed a **stale-kernel packaging bug**
(make-blob.sh's relative path shipped the Nov 1 Image.gz) — fixed by
`tools/build-payload.sh` (5 gates incl. the kernel↔module vermagic
handshake; the step6 stale artifact renamed .STALE-DO-NOT-USE). Dance
#18 shipped the correct kernel (g3b07f3a1ea98, USB fixes in, touch
loads natively — no more vermagic swaps, the phone boots the desktop).

**Chain progress** (each solved on-camera):
1. apcie + DART enabled in `dtb/d21-boot-wifi.dts` ✓ (both probe)
2. pwrctrl `wifi@0,0` platform device created, apple-wifi binds ✓ — the
   blocker was `CONFIG_REGULATOR_FIXED` unset: `devm_regulator_get
   ("vdd")` deferred forever, the h9p destroyed the pwrctrl device on
   every defer (devm cleanup) and retried into the same wall. Built
   `drivers/regulator/fixed.ko` (=m, native vermagic) → **wlan-vdd
   regulator registered** → the chain fired: h9p got past
   `pci_pwrctrl_devices_ready` for the first time.
3. h9p PHY init: **global PHY init timeout (-ETIMEDOUT)** — the ROOT
   CAUSE is identified: our h9p = Pauli's original port (2125 lines,
   no match-data struct) with a BARE `apple,t8015-pcie` match entry —
   the T8015 PHY/config tunables and the different initCommon sequence
   (common status @0x24, PHY-IP handshake, port-complex ordering) are
   in Orchard's `de95753`/`0030-PCI-apple-h9p-Add-T8015-support.patch`
   (Eduardo Martins, from the d221 runtime ADT: apcie-phy-tunables,
   apcie-common-tunables, pcie-rc-tunables, apcie-config-tunables).
4. The cleanup oops after that timeout is ALREADY FIXED
   (`daf529f6e`: detach_genpd guarded — attach_genpd leaves
   pd_count=1 with NULL arrays for single-domain nodes; upstream's
   0029 has the identical fix).

**NEXT SESSION RECIPE (the h9p modernization port)**: our driver
predates Orchard's whole drivers/pci series — `0001/0003/0004` each
conflict against our 2125-line file (their base is the integrated
hoolock staging 6831bc701, 3300+ lines, NOT public — the fork's last
push is Sep 3). The port: apply Orchard's drivers/pci h9p series
(0001, 0003, 0004, 0008-0027, 0029, 0030) SEQUENTIALLY onto our file
resolving conflicts (known local deltas: our aux/ref-optional commit
337856506 — upstream also made them optional; our bare t8015 match
entry; our header). Then rebuild (Image + all modules — HEAD moves,
native vermagic for everything), assemble via build-payload.sh with
all -m handshakes, push, dance #19. brcmfmac + firmware + pwrctrl are
READY and waiting on the phone (/root/wifi/, /usr/lib/firmware/brcm/).

### ★ PORT COMPLETE (session 6, 2026-11-04 night) — recipe executed

Applied SEQUENTIALLY as hoolock commits, exported as
`patches/0050-0065` (iPhOmarchy d8be73b): 0001 (manual-availability
DART fixed cell), 0003 (match-data struct `apple_h9p_hw`), 0004 (NVMMU
TCB one-direction, page count last), 0013 (per-SoC PHY/NVMMU/port-3),
0014 (msi-doorbell u32), 0015 (T7000), 0016 (pwrctrl BCM4350), 0017
(T7000 port IRQs), 0019-0025 (the full S8003 series), 0030 (T8015 —
the PHY-timeout fix, = de95753). SKIPPED with reasons: 0008-0011 +
0026/0027 (nvme-ans — our tree still has the OLD nvme-apple layout,
no pci-apple-ans.c, no callers of the NVMMU map API), 0012/0018/0028
(binding yamls — our tree carries no apple,t8010-pcie.yaml), 0029/
0031 (already landed session 5 as 0049/0048).

- ★ **OrchardLinux/linux is now PUBLIC** (created 2026-11-01) — the
  integrated post-0025 h9p driver (3263 lines) was fetched from its
  main branch and used as the convergence target: our post-S8003 file
  is **byte-identical** to it except our documented local deltas
  (T8015 `has_clocks=false`, genpd guard, header wording). The repo's
  push predates de95753 (T8015), so 0030 still had to be ported from
  the patch.
- ★ **Local delta kept**: `apple_h9p_hw_t8015.has_clocks = false` —
  upstream's D221 DTB supplies aux/ref as CLOCK nodes; ours keeps them
  as ps_pcie POWER DOMAINS (converting broke the ANS2 NVMe on
  2026-10-27). With has_clocks=true our probe would defer forever on
  the missing DT clocks. Rationale recorded in the driver comment.
- ★ Our session-5 DT port quirks (apple,link-retry-after-power-cycle,
  hardware-trained-phy-lane, endpoint-power-after-link-setup,
  inherited-perst-before-link-setup, manual-availability-iommu 2-cell)
  are ALL parsed by the modernized generic parse path — the D21 DTB
  needs NO changes for the port.
- Gotcha repeated: patch(1) writes .orig backups on fuzz; `git add -A`
  swept them into six commits — filter-branch stripped them; use
  `--no-backup-if-mismatch` and audit before add. patch(1)'s
  "reversed" heuristic also mis-fires when an earlier hand-resolution
  happens to match a later patch's post-image (0030 hunk 1 vs our 0019
  header wording) — split the patch and apply hunks 2+ explicitly.
- gotcha (build hygiene): a bare `make <file>.o` without
  `ARCH=arm64 LLVM=1` runs an x86 syncconfig that REWRITES .config
  (arm64 symbols dropped). Recovery: `.config.old` (pre-mangle) →
  `.config`, then `make ARCH=arm64 LLVM=1 olddefconfig`. Always pass
  ARCH/LLVM on every make.

ALSO SHIPPED LIVE: `usb-gadget.sh` UDC-wait fix (the g_multi -22 race,
3/3 boots → fixed on the rootfs); `d21-touchfix` unit tolerates the
builtin uinput (modprobe → `-modprobe`, the rootfs has no module tree
for the new kernel — depmod for g3b07f3a1ea98 is a TODO if modprobe is
ever needed); the wireless modules idle-load at boot is NOT persisted
(insmod'd by hand — add a unit after the h9p port).
