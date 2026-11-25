#!/bin/sh
# Runs on the D21 inside the RAM payload's maintenance hold, after
# orchard-write has written a release's root image into p3. Mirrors orchard
# 0.3.8 install_device.finish() for a handover boot (no boot entries).
# Usage: finish-root.sh PASSWORD PIN(6 digits) TIMEZONE
# Expects in /run/orchard: tune2fs, resize2fs (orchard install-tools),
# platform.tar.gz (orchard platform layer), pin-check and pin-pam (from
# orchard's install_device.py PIN_CHECK / PIN_PAM), authorized_keys.
set -eu
P=/dev/nvme0n1p3; R=/mnt/p3; T=/run/orchard
PW="$1"; PIN="$2"; TZ_NAME="$3"
log() { echo "finish: $*"; }
grep -q " $R " /proc/mounts && { echo "p3 already mounted"; exit 1; }
$T/tune2fs -U random -L omarchy-a $P
$T/resize2fs $P
mkdir -p $R; mount -t ext4 -o rw $P $R
for d in dev proc sys; do mount --bind /$d $R/$d; done
[ -x $R/usr/lib/systemd/systemd ] || { echo "no systemd in image"; exit 1; }

log "platform layer"     # never replace a file the image already has
(cd $R && tar -xzkf $T/platform.tar.gz) 2>&1 | grep -v 'File exists' | head -5 || true
ls $R/usr/lib/modules/

log "fstab"
pu3=$(blkid -s PARTUUID -o value /dev/nvme0n1p3 2>/dev/null || true)
pu2=$(blkid -s PARTUUID -o value /dev/nvme0n1p2 2>/dev/null || true)
[ -n "$pu3" ] && [ -n "$pu2" ] || { pu3=${P3_PARTUUID:?set P3_PARTUUID}; pu2=${P2_PARTUUID:?set P2_PARTUUID}; }
printf 'PARTUUID=%s / ext4 rw,relatime 0 1\nPARTUUID=%s /boot vfat rw,relatime,fmask=0077,dmask=0077 0 2\n' "$pu3" "$pu2" > $R/etc/fstab

log "account"
ent=$(chroot $R getent passwd tablet); uid=$(echo "$ent" | cut -d: -f3); gid=$(echo "$ent" | cut -d: -f4); home=$(echo "$ent" | cut -d: -f6)
echo "tablet:$PW" | chroot $R chpasswd
digest=$(printf '%s' "$PIN" | chroot $R openssl passwd -6 -stdin)
case $digest in '$6$'*) ;; *) echo "bad pin hash"; exit 1;; esac
mkdir -p $R/etc/orchard; printf 'tablet:%s\n' "$digest" > $R/etc/orchard/pin
chown 0:$gid $R/etc/orchard/pin; chmod 640 $R/etc/orchard/pin
mkdir -p $R/var/lib/orchard/pin-tally; chown $uid:$gid $R/var/lib/orchard/pin-tally; chmod 700 $R/var/lib/orchard/pin-tally
: > $R/var/lib/orchard/pin-tally/tablet; chown $uid:$gid $R/var/lib/orchard/pin-tally/tablet; chmod 600 $R/var/lib/orchard/pin-tally/tablet
cp $T/pin-check $R/usr/lib/orchard/pin-check; chmod 755 $R/usr/lib/orchard/pin-check
for s in greetd omarchy-lock-password; do cp $T/pin-pam $R/etc/pam.d/$s; chmod 644 $R/etc/pam.d/$s; done

log "ssh keys"
for h in "$R$home" "$R/root"; do mkdir -p $h/.ssh; cp $T/authorized_keys $h/.ssh/authorized_keys; chmod 700 $h/.ssh; chmod 600 $h/.ssh/authorized_keys; done
chown -R $uid:$gid "$R$home/.ssh"

log "timezone"
[ -e "$R/usr/share/zoneinfo/$TZ_NAME" ] && ln -sf "/usr/share/zoneinfo/$TZ_NAME" $R/etc/localtime
cat $R/etc/orchard/release* 2>/dev/null || true; echo
sync
for d in sys proc dev; do umount $R/$d; done
umount $R
log "done"
