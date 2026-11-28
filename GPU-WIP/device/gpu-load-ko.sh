#!/bin/sh
# DEBUG (phone side): load the pushed /run/powervr.ko at the lowest power state.
echo -n /run/gfxfw > /sys/module/firmware_class/parameters/path
echo "gfxkf: setup" > /dev/kmsg
timeout 30 modprobe -a drm_gpuvm drm_exec gpu_sched
timeout 60 insmod /run/powervr.ko apple_perf_state=1; echo "insmod exit $?"
sleep 2
dmesg | sed -n '/gfxkf: setup/,$p' | grep -E 'powervr|drm' | tail -3
