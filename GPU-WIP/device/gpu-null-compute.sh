#!/bin/sh
# DEBUG (phone side): one null compute job through the kernel driver (debugfs).
D=/sys/kernel/debug/dri/1
mount | grep -q debugfs || mount -t debugfs none /sys/kernel/debug
heap() { timeout 10 python3 - "$1" <<'PY'
import mmap, os, re, struct, sys
pa = int(re.findall(r"heap 0x([0-9a-f]+)\)", os.popen("dmesg").read())[-1], 16)
fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
m = mmap.mmap(fd, 0x400000, mmap.MAP_SHARED, mmap.PROT_READ, offset=pa)
r = lambda o: struct.unpack("<I", m[o:o + 4])[0]
ro = 0x19000 + 0x200                      # ring 2 object
print("%s: heap %#x ring2 cons %d sync %d prod %d | stamp +0 %d +4 %d | ready %d T+0xb1bc %d" % (
    sys.argv[1], pa, r(ro), r(ro + 0x10), r(ro + 0x20), r(0x38000), r(0x38004),
    r(0x9000 + 0xb188), r(0x9000 + 0xb1bc)))
PY
}
heap before
echo "gfxkf: null compute" > /dev/kmsg
timeout 20 sh -c "echo 1 > $D/apple_null_compute"; echo "trigger exit $?"
heap after
dmesg | sed -n '/gfxkf: null compute/,$p' | grep -vE 'wlan|brcmf' | tail -20
grep -E '^(compute|fault|fw_irq|runtime)' $D/apple_jobs
echo "oops: $(dmesg | grep -ciE 'oops|BUG:|SError|Unhandled|Internal error')"
