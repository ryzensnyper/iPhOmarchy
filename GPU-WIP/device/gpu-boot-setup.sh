#!/bin/sh
# DEBUG (phone side), after a fresh boot: mask sleep, load powervr with the RAM-only firmware.
/bin/systemctl mask --runtime sleep.target suspend.target >/dev/null 2>&1
echo "sleep: $(/bin/systemctl is-enabled sleep.target suspend.target | tr '\n' ' ')"
echo -n /run/gfxfw > /sys/module/firmware_class/parameters/path
echo "gfxkf: setup" > /dev/kmsg
timeout 20 modprobe -r powervr 2>&1
timeout 60 modprobe powervr apple_perf_state=1; echo "modprobe exit $?"
sleep 2
dmesg | sed -n '/gfxkf: setup/,$p' | grep -E 'powervr|drm' | tail -4
