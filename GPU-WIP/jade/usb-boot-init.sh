#!/bin/busybox sh
# Quiet, deterministic D21 desktop boot:
#  - driver loaded in initramfs (event1 ready before systemd), NO frame_dump
#  - watchdog masked (no re-roll storm / gadget wedge)
#  - USB gadget + dropbear up before handover (USB/SSH survive into desktop)
#  - touchfix waits for event1 robustly
export PATH=/bin:/sbin:/usr/bin:/usr/sbin
/bin/busybox --install -s /bin
mount -t proc -o nosuid,nodev,noexec proc /proc
mount -t sysfs -o nosuid,nodev,noexec sysfs /sys
mount -t devtmpfs -o mode=0755,nosuid devtmpfs /dev
mount -t tmpfs -o mode=0755,nosuid,nodev tmpfs /run
mkdir -p /dev/pts /newroot /run/orchard /lib/firmware/apple
mount -t devpts -o mode=0620,ptmxmode=0666 devpts /dev/pts
exec </dev/console >/dev/console 2>&1
LOG=/run/orchard/usb-boot.log
log() { echo "$*" >> "$LOG" 2>/dev/null; }
: > "$LOG"

# Firmware where the driver expects it.
cp /*.bin /lib/firmware/apple/ 2>/dev/null
log "firmware: $(ls /lib/firmware/apple/ | tr '\n' ' ')"

# Load the touch driver QUIETLY (no frame_dump/verbose) with the gold poke +
# poll kick, so event1 exists before systemd/greetd enumerate input devices.
# 10003058:3 (not 6) = documented win: taps register even in metronome/degraded
# cadence (TOUCH-STATE §poke sweep). 6 drops taps in a bad roll; 2 kills streaming.
# Known-good kernel 7.3.0-rc1-orchard-apple-16k (c2a38a5, idle-fix) with its
# OWN C1F5E,4 fwconfig boot sequence: poke=...10003058:6..., poke_after=10003458:1.
# Quiet: no poke_readback/verbose/frame_dump. Idle silence is safe on this kernel.
insmod /apple_z2.ko write=70:08 poll=1 probe_times=40 pres_min=64 \
  poke=10003060:17d3,1000305c:2,10003058:6,10003000:3,10003518:1 poke_after=10003458:1 2>>"$LOG"
log "insmod rc=$?"
# tuned latch params on every load
for p in "tool_max 3000" "tool_area_max 5000000" "tool_area_release 2000000" "tool_area_hard 12000000"; do
  set -- $p; echo "$2" > "/sys/module/apple_z2/parameters/$1" 2>/dev/null || true
done
i=0; while [ $i -lt 30 ] && [ ! -e /dev/input/event1 ]; do sleep 1; i=$((i+1)); done
log "event1 present: $([ -e /dev/input/event1 ] && echo yes || echo NO)"

# USB gadget + dropbear for the stable host channel.
sh /usr/libexec/orchard/usb-session || log 'usb-session failed'
log "usb-session done"

# NVMe + p3.
for alias in /sys/bus/*/devices/*/modalias; do
  [ -r "$alias" ] || continue; m=$(cat "$alias")
  case "$m" in brcm*|*brcmfmac*|*broadcom*|powervr) continue ;; esac
  modprobe -qb "$m" 2>/dev/null || true
done
modprobe nvme-core nvme nvme-apple 2>/dev/null || true
i=0; while [ $i -lt 40 ] && [ ! -e /sys/class/block/nvme0n1 ]; do sleep 1; i=$((i+1)); done
mount -t ext4 -o rw /dev/nvme0n1p3 /newroot 2>>"$LOG" || { log 'mount FAILED'; exec sh; }
log 'p3 mounted'

# Stage firmware + this kernel's module tree into the installed root.
mkdir -p /newroot/lib/firmware/apple
cp /*.bin /newroot/lib/firmware/apple/ 2>/dev/null
release=$(uname -r)
if [ -d "/lib/modules/$release" ]; then
  mkdir -p "/newroot/usr/lib/modules/$release"
  cp -a "/lib/modules/$release/." "/newroot/usr/lib/modules/$release/" 2>/dev/null || true
fi

# On p3: mask the watchdog (it wedges the gadget) and d21-touch (driver is
# already loaded in initramfs, so no duplicate insmod). Make touchfix wait for
# event1 so it never fails with "open source: No such file".
ln -sf /dev/null /newroot/etc/systemd/system/d21-touch-watchdog.service 2>/dev/null || true
rm -f /newroot/etc/systemd/system/multi-user.target.wants/d21-touch-watchdog.service 2>/dev/null || true
ln -sf /dev/null /newroot/etc/systemd/system/d21-touch.service 2>/dev/null || true
rm -f /newroot/etc/systemd/system/multi-user.target.wants/d21-touch.service 2>/dev/null || true
cat > /newroot/root/touchfix-wait.sh <<'WAIT'
#!/bin/sh
i=0
while [ $i -lt 60 ] && [ ! -e /dev/input/event1 ]; do sleep 1; i=$((i+1)); done
exec /root/d21-touchfix -t 1500 /dev/input/event1
WAIT
chmod 755 /newroot/root/touchfix-wait.sh 2>/dev/null || true
printf '%s\n' '[Unit]' 'Description=D21 touch fixer' 'After=d21-touch.service' '' '[Service]' 'Type=simple' 'ExecStart=/root/touchfix-wait.sh' 'Restart=always' 'RestartSec=3' '' '[Install]' 'WantedBy=multi-user.target' > /newroot/etc/systemd/system/d21-touchfix.service
chmod 644 /newroot/etc/systemd/system/d21-touchfix.service 2>/dev/null || true

sync
kill -TERM -- -1 2>/dev/null || true
sleep 1
kill -KILL -- -1 2>/dev/null || true
for name in dev proc sys run; do mount --move "/$name" "/newroot/$name"; done
exec switch_root /newroot /sbin/init
