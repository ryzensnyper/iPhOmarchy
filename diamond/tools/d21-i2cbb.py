#!/usr/bin/env python3
"""d21-i2cbb.py — bit-bang I2C master for D21's soft-i2c0 (chestnut display-pmu @0x27).

Task 3 (2026-11-03): the touch ANALOG rail is function-power_ana = 98:dpLE(0x302)
-> AppleChestnutDisplayPMU setLDO: I2C reg 0x05 (hardcoded), bit mask 4<<select,
   select 2 -> bit 0x10 (VERIFIED decode, TOUCH-STATE 1G).
The chestnut sits on i2c0 (i2c,t8015 / iic,soft = GPIO bit-bang, MMIO 0x2E200000),
device 0x27. Bus also carries the lm3539 backlight (0x62) and a boost (0xEA) —
be gentle, never drive the bus hard.

GPIO ABI: chardev v2 ONLY (kernel 7.3 dropped v1 ioctls). Constants/offsets are
the empirically proven ones from /root/gpioreset.py on this exact kernel.
Open-drain: iOS left the pads in open-drain pad config, so OUTPUT 1 = float
(high-Z), OUTPUT 0 = low. .get reads GPIO_IN = the real pad level.

Usage:
  d21-i2cbb.py chip line_sda line_scl read  reg            # read 1 byte
  d21-i2cbb.py chip line_sda line_scl rmw   reg val mask   # read-modify-write 1 byte
  d21-i2cbb.py chip line_sda line_scl scan                 # probe addresses 0x03..0x77
"""
import fcntl
import os
import struct
import sys
import time

GPIO_V2_GET_LINE        = 0xC250B407  # _IOWR(0xB4,0x07, 592 B)
GPIO_V2_LINE_GET_VALUES = 0xC010B40E  # _IOWR(0xB4,0x0e, 16 B)
GPIO_V2_LINE_SET_VALUES = 0xC010B40F  # _IOWR(0xB4,0x0f, 16 B)
GPIO_V2_LINE_FLAG_OUTPUT = 2          # empirical (gpioreset.py pulses chip3:33 with it)

REQ_SZ = 592
OFF_OFFSETS = 0        # u32 offsets[0]
OFF_CONSUMER = 256     # char[32]
OFF_CFG_FLAGS = 288    # u64 config.flags
OFF_CFG_NATTRS = 296   # u32 config.num_attrs
OFF_NUMLINES = 560     # u32 num_lines
OFF_FD = 588           # s32 fd


class BB:
    def __init__(self, chip, sda, scl):
        self.chipfd = os.open(f"/dev/{chip}", os.O_RDWR | os.O_CLOEXEC)
        self.sda = sda
        self.scl = scl
        buf = bytearray(REQ_SZ)
        struct.pack_into("<II", buf, OFF_OFFSETS, sda, scl)
        buf[OFF_CONSUMER:OFF_CONSUMER + 8] = b"d21i2cbb"
        struct.pack_into("<Q", buf, OFF_CFG_FLAGS, GPIO_V2_LINE_FLAG_OUTPUT)
        struct.pack_into("<I", buf, OFF_CFG_NATTRS, 0)
        struct.pack_into("<I", buf, OFF_NUMLINES, 2)
        fcntl.ioctl(self.chipfd, GPIO_V2_GET_LINE, buf, True)
        self.hfd = struct.unpack_from("<i", buf, OFF_FD)[0]
        if self.hfd < 0:
            raise OSError(f"GPIO_V2_GET_LINE failed: fd={self.hfd}")

    def _set(self, sda, scl):
        lv = bytearray(16)
        bits = (1 if sda else 0) | ((1 if scl else 0) << 1)
        struct.pack_into("<QQ", lv, 0, bits, 3)  # bits, mask=both
        fcntl.ioctl(self.hfd, GPIO_V2_LINE_SET_VALUES, lv, True)

    def read2(self):
        """GET_VALUES on the output handle — reads the REAL pad level
        (pinctrl-apple-gpio .get reads GPIO_IN; proven by gpioreset.py)"""
        lv = bytearray(16)
        struct.pack_into("<Q", lv, 8, 3)  # mask = both
        fcntl.ioctl(self.hfd, GPIO_V2_LINE_GET_VALUES, lv, True)
        bits = struct.unpack_from("<Q", lv, 0)[0]
        return bits & 1, (bits >> 1) & 1

    def release(self):
        self._set(1, 1)

    # ---- primitives (100 kHz-ish; ~2 us half-bit) ----
    def bit(self, sda_bit):
        self._set(sda_bit, 1)
        time.sleep(2e-6)
        self._set(sda_bit, 0)
        time.sleep(2e-6)

    def start(self):
        self._set(1, 1)
        time.sleep(2e-6)
        self._set(0, 1)   # SDA fall while SCL high
        time.sleep(2e-6)
        self._set(0, 0)
        time.sleep(2e-6)

    def rep_start(self):
        self._set(1, 0)
        time.sleep(2e-6)
        self._set(1, 1)
        time.sleep(2e-6)
        self._set(0, 1)   # SDA fall while SCL high
        time.sleep(2e-6)
        self._set(0, 0)
        time.sleep(2e-6)

    def stop(self):
        self._set(0, 0)
        time.sleep(2e-6)
        self._set(0, 1)
        time.sleep(2e-6)
        self._set(1, 1)
        time.sleep(2e-6)

    def write_byte(self, b):
        for i in range(7, -1, -1):
            self.bit((b >> i) & 1)
        # ACK clock: release SDA, pulse SCL, sample mid-high
        self._set(1, 1)
        time.sleep(2e-6)
        sda, _ = self.read2()
        self._set(1, 0)
        time.sleep(2e-6)
        return sda == 0  # 0 = ACK

    def read_byte(self, nack):
        val = 0
        for i in range(8):
            self._set(1, 1)   # SDA released, clock high
            time.sleep(2e-6)
            sda, _ = self.read2()
            val = (val << 1) | sda
            self._set(1, 0)
            time.sleep(2e-6)
        self.bit(1 if nack else 0)
        return val


def bus_reset(bb):
    """9 SCL pulses with SDA released to unwedge a stuck slave"""
    for _ in range(9):
        bb._set(1, 1)
        time.sleep(5e-6)
        bb._set(1, 0)
        time.sleep(5e-6)
    bb.stop()


def xfer_read(bb, addr, reg):
    bb.start()
    if not bb.write_byte((addr << 1) | 0):
        bb.stop()
        return None, "no ACK on addr write"
    if not bb.write_byte(reg):
        bb.stop()
        return None, "no ACK on reg"
    bb.rep_start()
    if not bb.write_byte((addr << 1) | 1):
        bb.stop()
        return None, "no ACK on addr read"
    v = bb.read_byte(nack=True)
    bb.stop()
    return v, "ok"


def xfer_rmw(bb, addr, reg, val, mask):
    v, msg = xfer_read(bb, addr, reg)
    if v is None:
        return None, f"pre-read failed: {msg}"
    nv = (v & ~mask) | (val & mask)
    if nv == v:
        return v, "unchanged"
    bb.start()
    if not bb.write_byte((addr << 1) | 0):
        bb.stop()
        return None, "no ACK on addr write"
    if not bb.write_byte(reg):
        bb.stop()
        return None, "no ACK on reg"
    if not bb.write_byte(nv):
        bb.stop()
        return None, "no ACK on data"
    bb.stop()
    time.sleep(0.01)
    v2, msg2 = xfer_read(bb, addr, reg)
    return v2, f"rmw {v:#04x} -> {nv:#04x}, post={v2 if v2 is not None else msg2}"


def main():
    if len(sys.argv) < 5:
        print(__doc__)
        sys.exit(2)
    chip, sda, scl = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    op = sys.argv[4]
    bb = BB(chip, sda, scl)
    bus_reset(bb)
    try:
        if op == "scan":
            for a in range(0x03, 0x78):
                bb.start()
                ack = bb.write_byte(a << 1)
                bb.stop()
                if ack:
                    print(f"  ACK @ {a:#04x}")
            print("scan done")
        elif op == "read":
            reg = int(sys.argv[5], 0)
            v, msg = xfer_read(bb, 0x27, reg)
            print(f"chestnut 27:{reg:#04x} = {v if v is None else hex(v)} ({msg})")
        elif op == "rmw":
            reg, val, mask = (int(x, 0) for x in sys.argv[5:8])
            v, msg = xfer_rmw(bb, 0x27, reg, val, mask)
            print(f"chestnut 27:{reg:#04x}: {msg}")
        else:
            print(__doc__)
            sys.exit(2)
    finally:
        bb.release()


if __name__ == "__main__":
    main()
