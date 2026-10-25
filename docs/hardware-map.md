# A11 / D21 hardware map (from the Apple Device Tree)

Source: `DeviceTree.d21ap.im4p` from the iPhone10,2 **iOS 16.7.16 (20H392)** IPSW, extracted
without downloading the whole 5.7 GB (HTTP-range ZIP fetch) and LZFSE-decoded, then decoded with
m1n1's `adt.py`. Artifacts in `adt/`:

* `dtree.im4p` raw      -> `dt.bin` (LZFSE payload) -> `dt_raw.bin` (raw ADT) -> `adt.txt` (decoded)
* Reproduce: `tools/fetch_dt.py`, then `tools/lzfse -decode -i dt.bin -o dt_raw.bin`, then
  `PYTHONPATH=~/hoolock/m1n1/proxyclient python3 -m m1n1.adt dt_raw.bin`

NOTE: this is the IPSW **template**; iBoot fills some values (many show as `<< syscfg/... >>`).
Register bases, IRQs and compatible strings are present and usable; for exact GPIO numbers do a
**live retrieve** later (`PYTHONPATH=.../proxyclient python3 -m m1n1.adt --retrieve dt.bin` while
running m1n1 on the device).

## The four targets

### Bluetooth — UART, not PCIe ✅ topology
ADT: `/arm-io/uart1 { … bluetooth { … } }`

| | value |
|---|---|
| uart1 reg | `0x2E604000` size `0x4000` (compatible `uart-1,samsung`) |
| uart1 IRQ | AIC **283**; clock-ids `[300,4]`; clock-gates `[81]` |
| bluetooth compatible | `bluetooth,n88` |
| transport-speed | 3,000,000 (H4) |
| vendor-id / product-id | 1452 (`0x5AC`, Apple) / 4768 |
| power_enable | pinctrl 36 `GPIO(0x2)` (via pmgr `pKW4('gP09')`) |
| bt_wake | pinctrl 36 `GPIO(0x2,0x101)` |

**Driver gap:** `hci_bcm.c` has no `bluetooth,n88` compatible (only `brcm,bcm*`). Needs a new
Apple-BT binding/driver (or an adaptation), plus firmware. `CONFIG_BT_HCIUART_BCM` is already on.

### Touch — SPI1 ✅ topology
ADT: `/arm-io/spi1 { … multi-touch { … } }`

| | value |
|---|---|
| spi1 reg | `0x2E404000` size `0x4000` (compatible `spi-1,samsung`) |
| spi1 IRQ | AIC **292**; clock-gates `[75]`; clock-ids `[333]` |
| cs0 pin | pinctrl 36 `GPIO(0x8a)` |
| multi-touch compatible | `hid-transport,k1` |
| touch IRQ | pinctrl 36 line 102 (GPIO irq), `0x06000000` flags |
| touch lines | reset `GPIO(0x21)`, enable_cs `GPIO(0x8a)`, power_ldo `pKW4('rBK3')`, clock_enable `TCLK(0x8,0x64,0x8000)` |

**Driver gap:** the SPI **controller** is supported (`spi-apple.c` matches `apple,spi`); the
**touch controller** (`hid-transport,k1`) has **no driver** in-tree — this is the real work.

### Wi-Fi — PCIe ✅ topology
ADT: `/arm-io/apcie { … pci-bridge3 { … wlan { … } } }`

| | value |
|---|---|
| apcie reg | ECAM `0x61000000` size `0x1000000`; ports `0x601000000`,`0x601004000`,`0x602000000`,`0x602004000`,`0x603000000`,`0x603004000`,`0x604000000`,`0x604004000`,`0x600000000`(+`0x50000`, `0x600080000`, `0x6000C0000`+`0x40000`) |
| apcie compatible | `apcie,t8015` |
| apcie IRQs | AIC 340, 343, 346, 349; #ports 4; msi-vector-offset 352 |
| wlan (port 3) | compatible `wlan-pcie,bcm4357`, `wlan-pcie,bcm` → **BCM4357** |
| IOMMU | `dart-apcie3` (wlan), `dart-apcie2` (baseband) |

**Driver gap:** `pcie-apple.c` only has `t8103_hw` (`apple,pcie`). A11 needs a new `hw_info`
+ a `apcie,t8015` node. Then `brcmfmac` for BCM4357 + Apple firmware.

### Display — disp0 (TBA upstream)
ADT: `/arm-io/disp0` compatible `disp0,t8015`, reg `0x18000000`+`0x2A6000`, `0x18708000`,
`0x320B8000`, `0x3230C000`; IRQs 220,226,217,218,219,221,216,227; IOMMU `dart-disp0`.
No driver (Hoolock marks Display Pipe **TBA**). Today we only have `simpledrm` + DWI backlight.

### GPU
**No `agx`/GPU device node in the ADT** (only PMGR/thermal entries). Apple AGX has no mainline
driver; Hoolock marks GPU **TBA**. Out of scope.

## Driver gap summary

| Target | DT data | Kernel driver | Effort |
|---|---|---|---|
| SPI controller | ✅ (spi1) | ✅ `spi-apple` matches `apple,spi` | hours (DT only) |
| Touch | ✅ | ❌ none for `hid-transport,k1` | **weeks** (new driver) |
| Bluetooth | ✅ | ❌ none for `bluetooth,n88` | weeks (adapt `hci_bcm`) |
| Wi-Fi | ✅ | ⚠️ `pcie-apple` needs t8015; then `brcmfmac` | weeks |
| Display | ✅ | ❌ none (`disp0,t8015`) | TBA upstream |
| GPU | n/a | ❌ | out of scope |
