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
4. Mounts `nvme0n1p3`, copies in this kernel's module tree and the touch
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

Older payload recipes that re-create `d21-touchfix` on every boot will turn it
back on; don't use them alongside this one.

## Validation (2026-11-25)

Orchard `main` `a9668ec`, with the same kernel and `apple_z2.ko` as the
validation runs below:

| Test | Result |
|---|---|
| Fresh boots, RAM payload | 5/5 touch, 57–74 KB per 30 s tap window |
| Driver reloads | 13/13 touch, no hangs, stalls or warnings |
| Desktop boot (this recipe) | handover OK, systemd running, 0 failed units, labwc up |
| Desktop touch, helpers stopped | 25,488 B on `event1` in 30 s; user: taps land correctly |

The only call trace in the log is an IOMMU `iommu_setup_default_domain` warning
at 0.39 s. It appears on every Orchard `main` boot and is unrelated to touch.
