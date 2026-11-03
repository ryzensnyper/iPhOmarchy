#!/usr/bin/env python3
"""d21-i2creg.py — read/RMW a register on the chestnut display-pmu via /dev/i2c-N.

Task 3: touch ANALOG rail = function-power_ana = 98:dpLE(0x302)
        -> chestnut setLDO: I2C reg 0x05, bit mask 4<<select; select 2 -> bit 0x10.
        Chestnut = device 0x27 on i2c-0 (PA Semi adapter, 22e200000.i2c).
        Bus also carries the lm3539 backlight (0x62) + boost (0xEA): be gentle.

Usage:
  d21-i2creg.py read  <bus> <addr7> <reg>
  d21-i2creg.py rmw   <bus> <addr7> <reg> <val> <mask>
  d21-i2creg.py dump  <bus> <addr7> <first> <last>     (byte reads, bounded)
"""
import fcntl
import struct
import sys

I2C_SLAVE = 0x0703
I2C_SLAVE_FORCE = 0x0706
I2C_TENBIT = 0x0704
I2C_SMBUS = 0x0720


def open_dev(bus, addr):
    fd = os_open(f"/dev/i2c-{bus}")
    fcntl.ioctl(fd, I2C_SLAVE_FORCE, addr)
    return fd


def os_open(path):
    import os
    return os.open(path, os.O_RDWR)


def read_reg(fd, reg):
    # plain I2C: write reg pointer, repeated start, read 1 byte
    import os
    os.write(fd, bytes([reg & 0xFF]))
    return os.read(fd, 1)[0]


def write_reg(fd, reg, val):
    import os
    os.write(fd, bytes([reg & 0xFF, val & 0xFF]))


def main():
    op = sys.argv[1]
    bus, addr = int(sys.argv[2], 0), int(sys.argv[3], 0)
    fd = open_dev(bus, addr)
    if op == "read":
        reg = int(sys.argv[4], 0)
        print(f"i2c-{bus} {addr:#04x}:{reg:#04x} = {read_reg(fd, reg):#04x}")
    elif op == "rmw":
        reg, val, mask = (int(x, 0) for x in sys.argv[4:7])
        old = read_reg(fd, reg)
        nv = (old & ~mask) | (val & mask)
        if nv == old:
            print(f"i2c-{bus} {addr:#04x}:{reg:#04x} unchanged ({old:#04x})")
            return
        write_reg(fd, reg, nv)
        import time
        time.sleep(0.02)
        now = read_reg(fd, reg)
        print(f"i2c-{bus} {addr:#04x}:{reg:#04x}: {old:#04x} -> {nv:#04x} "
              f"(post={now:#04x} {'OK' if now == nv else 'MISMATCH'})")
    elif op == "dump":
        first, last = int(sys.argv[4], 0), int(sys.argv[5], 0)
        for r in range(first, last + 1):
            print(f"  {r:#04x} = {read_reg(fd, r):#04x}")
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
