# Orchard reference patches — WiFi/PCI/DART stack (mirrored 2026-11-03)

Source: github.com/OrchardLinux/orchard @ main (post 6b5fca68, 2026-11-03).
Last commit touching drivers/wifi: 5ca0cc5f (2026-10-29, "Disable Wi-Fi P2P on
J71b/J71t"); the stack landed 2026-10-29 in 538395f ("Add the A8X (T7000) drivers
from Martin Puškáč's port") on top of the earlier J71b (iPad 6) bring-up.

## Why mirrored
D21 (iPhone 8 Plus, T8015/A11) has the apcie node in DTB (pcie@610000000) but
lspci shows NOTHING and brcmfmac is not in the kernel: the host-driver/DART/
config wiring is missing. Orchard's A7-A10 line is the working reference for
the exact same path on the older Apple SoCs:

- wifi/    7 brcmfmac patches: Apple NVRAM selected BY OTP (0002: no manual
           NVRAM filename guessing), port authorized only after the fw
           handshake (0004: fixes wpa_supplicant 2.11 connect churn),
           msgbuf RX buffers mapped for device reads (0003), BCM4350 OTP
           read (0005), per-firmware feature-disable table (0007, P2P etc).
- pci/    23 apple-h9p (A7-A10 PCIe host) patches: SoC differences as match
           data (0003), NVMMU TCBs (0004/0021/0025), PHY/link events (0013),
           MSI doorbell single-cell (0014), T7000 (0012/0015/0017) and S8003
           (0018-0025) bring-up incl. storage-port-first order, tunables,
           PME_Turn_Off; pwrctrl-apple-wifi BCM4350 REG_ON + device-wake
           power sequence (0016); ANS NVMe bring-up from reset (0011/0026/0027).
- iommu/   9 DART patches: master-config deref fix (0001), S5L8960X error
           reflector + translation-in-iOS-order (0004/0006), NO_PERM pgtable
           quirk (0008), T7000 hw data (0009).
- devices-t8010/0002-pcie-dart-windows.patch — how the PCIe DART windows are
           described in DT (the t8010 analog of our missing apcie wiring).

## D21 mapping notes (to be filled during the WiFi task)
- Our WiFi chip on iPhone10,2: Broadcom (BCM4355-class, USI module) — confirm
  chip + OTP/NVRAM IDs from SysCfg/dmg before porting 0005 (that patch is
  BCM4350-specific).
- T8015 DART for apcie is A11-generation: expect needing our own hw data
  (like 0009 does for T7000), guided by the ADT (apcie/dart nodes) rather
  than any of the SoC patches verbatim.
- Kernel config: CONFIG_PCIEAPPLE (or the h9p equivalent), apple-dart, and
  brcmfmac must be enabled in our a11-port build.
