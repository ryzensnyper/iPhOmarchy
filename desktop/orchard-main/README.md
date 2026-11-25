# Omarchy-A desktop on Orchard main (D21)

A RAM payload recipe for the iPhone 8 Plus (D21) that boots the stock
[Orchard](https://github.com/OrchardLinux/orchard) `main` kernel, loads its
shared `apple_z2` touch driver with **no module parameters**, and hands over to
the installed Omarchy-A root on `nvme0n1p3`.

Touch on D21 has been in Orchard `main` since commit `06e093ea`, so this recipe
needs no local kernel patches. It replaces the DIAMOND build's gold-config
`insmod` and the userspace touch helpers.

## What the init does

1. Brings up the USB session (network + serial + SSH).
2. Coldplugs drivers, loads `nvme-apple`, waits for `nvme0n1p3`.
3. `modprobe apple_z2` and waits for `/dev/input/event1`.
4. Waits up to 30 s for an optional **maintenance hold**: if a host creates
   `/run/d21-hold` over SSH, the boot stays in RAM with `nvme0n1p3`
   unmounted until the host creates `/run/d21-go`. This is how a new root
   image gets written (below).
5. Mounts `nvme0n1p3`, copies in this kernel's module tree and the touch
   container, then `switch_root`s into the installed system's systemd.

## Build and boot

The touch firmware container (`dfrmtfw-d21-c1f5e-4.bin`) is built on your own
host from your own device and is **not** in this repository. Put it in the
recipe before building:

```sh
mkdir -p rootfs/lib/firmware/apple
cp /path/to/your/dfrmtfw-d21-c1f5e-4.bin rootfs/lib/firmware/apple/
cd /path/to/orchard   # main, at or after 06e093ea
./bin/orchard build /path/to/this/recipe --device d21 --pongo /path/to/Pongo.bin
```

With the phone in PongoOS:

```sh
printf '/send out/apple-16k/linux.bin\nbootm\n' | ./pongoterm
```

After about 60 s the desktop (labwc, greetd, user `tablet`) is up. SSH as
root with Orchard's RAM-session key
(`~/.local/share/orchard/private/ram-ssh/id_ed25519`, use `-o IdentitiesOnly=yes`).

## Install a new Omarchy-A release into p3

This replaces `orchard install` and `orchard launch` on D21: the release's
root image goes straight into `p3`, and this payload boots it. **It wipes
`p3`.** iOS (`p1`) and the boot partition (`p2`) are untouched. Tested with
Omarchy-A v0.3.6 (built on orchard 0.3.8), with the payload built from
orchard `v0.3.8`.

On the host, fetch and verify the release and orchard's tools:

```sh
gh release download v0.3.6 -R OrchardLinux/omarchy-a \
    -p root.blocks.zst -p root.map.json -p release.toml -p SHA256SUMS
sha256sum -c --ignore-missing SHA256SUMS
gh release download v0.3.8 -R OrchardLinux/orchard -D o38 \
    -p install-tools.tar.gz -p platform-apple-16k.tar.gz -p SHA256SUMS
(cd o38 && sha256sum -c --ignore-missing SHA256SUMS)
mkdir stage && tar xzf o38/install-tools.tar.gz -C stage orchard-write resize2fs tune2fs
cp o38/platform-apple-16k.tar.gz stage/platform.tar.gz
cp install/finish-root.sh stage/
install/extract-pin-files.py path/to/orchard/src/orchard/install_device.py stage
cat ~/.ssh/your_key.pub > stage/authorized_keys
```

Boot the payload, and within 30 s hold it:

```sh
ssh root@172.16.42.1 'touch /run/d21-hold'
(cd stage && tar cf - .) | ssh root@172.16.42.1 'mkdir -p /run/orchard && tar xf - -C /run/orchard'
# orchard-write takes the map as plain "start count" lines, not the JSON.
python3 -c "import json;print(''.join(f'{s} {c}\\n' for s,c in json.load(open('root.map.json'))['ranges']),end='')" \
    | ssh root@172.16.42.1 'cat > /run/orchard/root.map'
# BYTES and SHA256 of root.blocks.zst, from release.toml [root]:
ssh root@172.16.42.1 '/run/orchard/orchard-write /dev/nvme0n1p3 /run/orchard/root.map BYTES SHA256' < root.blocks.zst
ssh root@172.16.42.1 'sh /run/orchard/finish-root.sh PASSWORD PIN Area/City'
ssh root@172.16.42.1 'touch /run/d21-go'
```

`orchard-write` verifies the image hash itself. `finish-root.sh` does what
orchard's installer does after writing:
- sets a new filesystem UUID and grows the filesystem to the partition
- unpacks the platform layer without replacing image files (the image's `tar` is busybox, hence `-k`)
- writes `fstab`
- sets the `tablet` password and the 6-digit lock-screen PIN, with the installer's PIN-check and PAM files
- adds SSH keys and sets the timezone

It writes no boot entries. The payload is the bootloader here. After `d21-go`
the desktop is up in about 30 s.

## Retire the DIAMOND helpers on the installed root

The old `d21-touch`, `d21-touch-watchdog` and `d21-touchfix` units must be
masked in the installed root's `/etc`. A mask in `/run` does not override a
unit file in `/etc`. `d21-touchfix` also grabs `event1` and re-emits touches
on a virtual `event2`, so while it runs the desktop isn't using the driver
directly.

```sh
systemctl disable d21-touchfix
mkdir -p /root/disabled-units
mv /etc/systemd/system/d21-touchfix.service /root/disabled-units/
systemctl daemon-reload
systemctl mask d21-touch d21-touch-watchdog d21-touchfix
```

Undo: `rm /etc/systemd/system/d21-touchfix.service; mv /root/disabled-units/d21-touchfix.service /etc/systemd/system/; systemctl enable d21-touchfix`.

On a fresh release root (as above) the DIAMOND helpers are not present.
Older payload recipes that re-create `d21-touchfix` on every boot will turn it
back on; don't use them alongside this one.

## Validation (2026-11-25)

The first four rows ran on Orchard `main` `a9668ec`, the last on orchard
`v0.3.8` `116004fb`. All used the same `apple_z2.ko`.

| Test | Result |
|---|---|
| Fresh boots, RAM payload | 5/5 touch, 57–74 KB per 30 s tap window |
| Driver reloads | 13/13 touch, no hangs, stalls or warnings |
| Desktop boot (this recipe) | handover OK, systemd running, 0 failed units, labwc up |
| Desktop touch, helpers stopped | 25,488 B on `event1` in 30 s; user: taps land correctly |
| **Omarchy-A v0.3.6** installed into p3 as above | write 38 s, hash OK; systemd running, 0 failed units; 25,032 B in 30 s; user: PIN unlock, taps, swipes and pull-downs work |

The only call trace in the log is an IOMMU `iommu_setup_default_domain` warning
at 0.39 s. It appears on every Orchard `main` boot and is unrelated to touch.
