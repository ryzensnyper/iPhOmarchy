# tools

## fetch-dt.py — get any device's Apple Device Tree without the whole IPSW

Apple IPSWs are 4–6 GB but the file we want is tiny. An IPSW is a ZIP, so this script uses HTTP
**range requests** (a seekable remote ZIP) to pull only `Firmware/all_flash/DeviceTree.<board>.im4p`,
then unwraps the DER `IM4P` container.

```sh
python3 fetch-dt.py            # edits: set URL and pick the DeviceTree entry
```

The payload it writes is **LZFSE-compressed**, so decode it before parsing:

```sh
# decode LZFSE (Apple reference tool; builds in seconds)
git clone https://github.com/lzfse/lzfse && make -C lzfse
./lzfse/build/bin/lzfse -decode -i dt.bin -o dt_raw.bin

# parse the ADT with m1n1's decoder
git clone https://github.com/HoolockLinux/m1n1
python3 -m pip install construct pyusb      # or your distro's python-construct/python-pyusb
PYTHONPATH=m1n1/proxyclient python3 -m m1n1.adt dt_raw.bin > adt.txt
# add -a for a memory map
```

For the iPhone 8 Plus (`iPhone10,2`, board `d21ap`) on iOS 16.7.16 (20H392) this produced the
tree excerpted in [`../hardware/adt-d21-peripherals.txt`](../hardware/adt-d21-peripherals.txt).

### Live ADT vs IPSW template
The IPSW `DeviceTree` is a **template**: iBoot fills in many values at runtime (they appear as
`<< syscfg/... >>`). Register bases, IRQs and compatible strings are present and usable. For the
populated tree (needed for per-device calibration), retrieve it live while m1n1 is running:

```sh
PYTHONPATH=m1n1/proxyclient python3 -m m1n1.adt --retrieve dt.bin
```

## Notes
- `fetch-dt.py` needs no third-party Python packages.
- Firmware and calibration belong to the device owner; extract them from your own device's
  firmware. Nothing Apple-proprietary is committed here.
