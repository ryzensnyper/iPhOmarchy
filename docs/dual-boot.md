# HANDOFF — 2026-10-25: dual-boot Linux on the iPhone 8 Plus — WORKING

Supersedes the "Current blocker" section of `AGENT_START.md`. Stages A, B and C are all
done. The phone boots Arch Linux ARM from its internal partition while iOS stays intact.

## Outcome

* Disk unchanged from the brief: `nvme0n1p1` = iOS (APFS), `nvme0n1p2` = Linux (ext4, 27.6 GiB).
* `rootfs.ext4` (8 GiB Arch Linux ARM) written into `/dev/nvme0n1p2`, verified by mounting.
* Installed system boots and is reachable:

  ```
  /proc/cmdline : root=/dev/nvme0n1p2 rootwait rw console=tty0
  /             : /dev/nvme0n1p2  ext4  rw,relatime
  uname         : Linux d21ap 7.3.0-rc1-g6831bc701a6c-dirty aarch64
  ssh           : alarm@172.16.42.1   password: alarm   (Arch Linux ARM default)
  ```

## Root cause of the old blocker (important)

`checkra1n-0.1337.3` **never** wins the checkm8 race on this host/kernel (6.18.48-cachyos-lts):
every log in the kit is 0 `setup packet was accepted`, thousands of retries, `-110`/`-71`
in dmesg. It is not host USB state and not tuning.

**`palera1n -p -v` pwns reliably here.** README-LINUX already said it ("palera1n's pwn is
exactly what you already used"); checkra1n is the fallback and it does not work on this box.

Two tool differences that matter:

* **palera1n needs `usbmuxd` RUNNING** (it uses it to find the iOS device and push it to
  recovery). checkra1n wants it gone. `tune.sh` stops usbmuxd — do not run tune.sh as-is when
  using palera1n; start usbmuxd instead (`sudo systemctl start usbmuxd`).
* palera1n `-p` holds interface 0 while its PongoOS shell is up. Quit it (Ctrl-C) before
  running `pongoterm`.

## Working procedure (reproduce)

```sh
# Phone on iOS. usbmuxd up. One pwn at a time.
sudo systemctl start usbmuxd
cd ~/checkm8-kit
tmux new -s pwn 'cd ~/checkm8-kit && sudo ./palera1n -p -v'
# attach, press Enter, then the DFU gesture:
#   VolUp tap, VolDown tap, hold Side till screen black (keep holding),
#   add VolDown 5 s, release Side, keep VolDown ~10 s
# Success: Checkmate! -> Booting PongoOS... -> pongoOS>  (lsusb = 05ac:4141)

# quit palera1n (Ctrl-C in the tmux pane); make sure nothing holds the device:
#   (no checkra1n/palera1n/usbmuxd procs; no /proc/*/fd -> /dev/bus/usb/*)

cd ~/checkm8-kit/linux-kit
printf '/send m1n1-linux-d21.bin\nbootm\n' | sudo ./pongoterm   # Stage A: RAM Linux (flashing)
#   or  /send m1n1-linux-p2.bin                              # Stage C: installed system
# USB drops (LIBUSB_ERROR_IO) by design; ~60 s later 05ac:4142, 172.16.42.1 answers.
```

## Flashing a DIFFERENT Linux into /dev/nvme0n1p2

The proven, safe pipeline is the same one used for `rootfs.ext4`:

1. **Produce an ext4 FILESYSTEM image** (not a whole-disk image) of the distro, for **aarch64**,
   sized to fit the 27.6 GiB partition. Examples:
   * a rootfs tarball (Arch Linux ARM, Alpine, etc.) -> `mkfs.ext4` a file, mount, extract, umount.
   * `pmbootstrap`/postmarketOS: use its rootfs, not its full disk image.
   Never a raw disk image that includes its own GPT.
2. **Boot the RAM Linux (Stage A, `m1n1-linux-d21.bin`)**, NOT the installed system — the script
   refuses to write `p2` while it is mounted, and running from `p2` means it *is* `/`. The RAM
   ramdisk is throwaway.
3. Verify and write (this never touches `p1`/the GPT):

   ```sh
   cd ~/checkm8-kit/linux-kit
   md5sum your-image.ext4            # record it
   ./push-rootfs-part.py /dev/nvme0n1p2 your-image.ext4 --check   # 128 MiB link test
   ./push-rootfs-part.py /dev/nvme0n1p2 your-image.ext4           # ~8 GiB, few minutes
   ```
   It streams gzip over `nc` to port 9100 (host->phone only; inbound is firewalled) and
   verifies by mounting the partition on the phone at the end.

### Kernel caveat — the kernel does NOT come from the rootfs

On this device the kernel is RAM-loaded by PongoOS/m1n1 from the payload blob. The rootfs only
supplies userland, so:

* `m1n1-linux-p2.bin` embeds kernel **7.3.0-rc1-g6831bc701a6c-dirty**. A distro shipping a
  different kernel version will have `/lib/modules/<other>` and mostly not work.
* Either keep the same kernel (copy its `/lib/modules` into the new rootfs), or **rebuild the
  payload blob** with the distro's kernel:

  ```sh
  cd ~/checkm8-kit/linux-kit/step6
  BOOTARGS="root=/dev/nvme0n1p2 rootwait rw console=tty0" ./make-blob.sh ../m1n1-linux-p2.bin
  ```
* Keep `root=/dev/nvme0n1p2` in BOOTARGS, and the image must support NVMe + ext4 (or change the
  fs and pass the matching `rootfstype`).

Reachability note: the USB link is host-only; the phone has no internet during bring-up, so
always stream the image from this PC rather than trying to download on the phone.

## Host changes made this session (left in place)

* `/etc/sudoers.d/99-doug-nopasswd` — passwordless sudo for `doug` (remove to revert).
* `/etc/modprobe.d/blacklist-apple-mfi.conf` — blacklists `apple_mfi_fastcharge` (optional;
  did not by itself fix checkm8, but harmless and keeps the Apple device handler out of the way).
* `usbmuxd` installed; auto-starts via `39-usbmuxd.rules` whenever the phone is in iOS mode.
  Needed for palera1n; kill it before checkra1n.
* `sshpass`, `libusb`, `usbmuxd`, `tmux` installed.
* **Bugfix**: `linux-kit/push-rootfs-part.py` `--check` parser now accepts BusyBox `md5sum`
  output (`hash  -`), which previously always reported a false `MISMATCH`. The write path was
  never affected.

## Gotchas that bit us

* Ending a shell call can kill the tmux server here; a dead tmux does not undo a successful pwn
  (PongoOS runs on the phone). Just verify `05ac:4141` and continue with `pongoterm`.
* Leftover `checkra1n`/`usbmuxd` processes survive their parent; `cleanup.sh` matches by
  `/proc/<pid>/comm` for a reason.
* Throughput on the 8 GiB write ramped down from ~14 MiB/s to ~4.7 MiB/s; total dd 798 s.
  Normal for this link; it completed and verified.
* The phone is still tethered: re-pwn every boot. iOS must stay bootable — it is the only way
  into DFU.
