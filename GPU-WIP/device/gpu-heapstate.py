#!/usr/bin/env python3
# DEBUG (phone side): read-only dump of the G10P heap state after a compute job.
import mmap, os, re, struct
pa = int(re.findall(r"heap 0x([0-9a-f]+)\)", os.popen("dmesg").read())[-1], 16)
fd = os.open("/dev/mem", os.O_RDONLY | os.O_SYNC)
m = mmap.mmap(fd, 0x100000, mmap.MAP_SHARED, mmap.PROT_READ, offset=pa)
def dump(name, off, n):
    w = struct.unpack("<%dI" % (n // 4), m[off:off + n])
    nz = [(i * 4, v) for i, v in enumerate(w) if v]
    print("%-9s %#07x: %s" % (name, off, " ".join("+%x=%x" % p for p in nz) or "all 0"))
dump("pool", 0x84000, 0x84)          # entries 0..2 (0x2c each): word 0 = 3 after the stamp path
dump("units", 0x2e000, 0x200)        # start/finalize records (24 B) and the +0x98 yield words (20 B)
dump("job0cmd", 0x53000, 0x2c0)
dump("stamp", 0x38000, 0x40)
dump("queue", 0x63000, 0xa0)
dump("X+0xc0", 0xc0, 0x60)
dump("pwr", 0x2c000, 0x100)          # [X+0xe0]: +0xc power state (0 off, 2 powering on, 1 on), +0x54 per engine, +0x5c+20*slot
dump("X+0x178", 0x178, 0x10)         # power-task lock byte
dump("X+0x69a8", 0x69a8, 0x20)       # power struct; +0x69b0..+0x69bc = the dispatcher's blocked mask
dump("ring12", 0x19000 + 12 * 0x100, 0x30)           # consumer +0, sync +0x10, producer +0x20
dump("r12e0", 0x39000 + 12 * 0x20 * 256, 0x20)        # first command entry (type 0xe)
