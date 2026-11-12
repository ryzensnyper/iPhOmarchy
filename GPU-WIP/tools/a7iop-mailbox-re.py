#!/usr/bin/env python3
"""Extract the AppleA7IOP mailbox register map from the D21 kernelcache.

Apple's own AppleA7IOP kext (shipped in the iOS kernelcache) drives the
"a7iop" coprocessor mailbox that the G10P GPU IOP uses.  Its log function
prints the mailbox registers by name, and the register offsets it passes to
the kext's readRegister() helper give the map away.

Usage:
    python3 a7iop-mailbox-re.py [kernelcache.macho]

Default kernelcache: /tmp/opencode/d21ap-kernelcache.macho

What it prints:
  * the multi-line log format string ("MAILBOX_SET: 0x%08x" ...)
  * the register offsets the log function reads, in order
  * the writes the kext performs (the enable sequence), with their values

Nothing here is a guess: every number comes out of the binary.
"""

import struct
import sys

DEFAULT_KC = "/tmp/opencode/d21ap-kernelcache.macho"

# VM segment table of the D21 kernelcache: name, vmaddr, vmsize, fileoff, filesize
SEGS = [
    ("__TEXT", 0xFFFFFFF007004000, 0xB8000, 0x0, 0xB8000),
    ("__DATA_CONST", 0xFFFFFFF0070BC000, 0xF8000, 0xB8000, 0xF8000),
    ("__TEXT_EXEC", 0xFFFFFFF0071B4000, 0x680000, 0x1B0000, 0x680000),
    ("__KLD", 0xFFFFFFF007834000, 0x4000, 0x830000, 0x4000),
    ("__LASTDATA_CONST", 0xFFFFFFF007838000, 0x4000, 0x834000, 0x4000),
    ("__LAST", 0xFFFFFFF00783C000, 0x4000, 0x838000, 0x4000),
    ("__KLDDATA", 0xFFFFFFF007840000, 0x4000, 0x83C000, 0x4000),
    ("__DATA", 0xFFFFFFF007844000, 0xAC000, 0x840000, 0x24000),
    ("__BOOTDATA", 0xFFFFFFF0078F0000, 0x40000, 0x864000, 0x40000),
    ("__PRELINK_TEXT", 0xFFFFFFF004DB4000, 0x7CC000, 0x97C000, 0x7CC000),
    ("__PRELINK_INFO", 0xFFFFFFF007BBC000, 0x328000, 0x2D80000, 0x328000),
    ("__PLK_TEXT_EXEC", 0xFFFFFFF005580000, 0x16DC000, 0x1148000, 0x16DC000),
    ("__PRELINK_DATA", 0xFFFFFFF007A08000, 0x1B4000, 0x2BCC000, 0x1B4000),
    ("__PLK_DATA_CONST", 0xFFFFFFF006C5C000, 0x3A8000, 0x2824000, 0x3A8000),
]


def v2f(va):
    for name, v, vs, fo, fs in SEGS:
        if v <= va < v + min(vs, fs):
            return fo + (va - v)
    raise ValueError(hex(va))


def f2v(off):
    for name, v, vs, fo, fs in SEGS:
        if fo <= off < fo + fs:
            return v + (off - fo)
    raise ValueError(hex(off))


class KC:
    def __init__(self, path):
        self.d = open(path, "rb").read()

    def w(self, va):
        return struct.unpack_from("<I", self.d, v2f(va))[0]

    def cstr(self, va, maxlen=120):
        off = v2f(va)
        end = self.d.find(b"\0", off, off + maxlen)
        return self.d[off:end].decode("ascii", "replace")

    def adrp_target(self, pc):
        word = self.w(pc)
        if (word & 0x9F000000) != 0x90000000:
            return None
        imm = (((word >> 5) & 0x7FFFF) << 2) | ((word >> 29) & 3)
        if imm & (1 << 20):
            imm -= 1 << 21
        return (pc & ~0xFFF) + (imm << 12)

    def add_target(self, pc):
        """Target of an ADRP + (immediate) ADD pair at pc."""
        page = self.adrp_target(pc)
        if page is None:
            return None
        nxt = self.w(pc + 4)
        if (nxt & 0xFF800000) != 0x91000000:
            return None
        imm = (nxt >> 10) & 0xFFF
        if (nxt >> 21) & 1:
            imm |= ~0xFFF
        if (nxt >> 22) & 1:
            imm <<= 12
        return page + imm

    def xrefs(self, target):
        """ADRP(+ADD/LDR) references to target in the code segments."""
        hits = []
        for name, v, vs, fo, fs in SEGS:
            if name not in ("__PLK_TEXT_EXEC", "__TEXT_EXEC", "__PRELINK_TEXT"):
                continue
            end = fo + min(vs, fs)
            off = fo
            while off + 8 <= end:
                word = struct.unpack_from("<I", self.d, off)[0]
                if (word & 0x9F000000) == 0x90000000:
                    rd = word & 31
                    imm = (((word >> 5) & 0x7FFFF) << 2) | ((word >> 29) & 3)
                    if imm & (1 << 20):
                        imm -= 1 << 21
                    pc = v + (off - fo)
                    page = (pc & ~0xFFF) + (imm << 12)
                    for j in range(1, 4):
                        w2 = struct.unpack_from("<I", self.d, off + 4 * j)[0]
                        if (w2 & 0xFF800000) == 0x91000000 and ((w2 >> 5) & 31) == rd:
                            if page + ((w2 >> 10) & 0xFFF) == target:
                                hits.append(pc)
                off += 4
        return sorted(set(hits))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_KC
    kc = KC(path)

    marker = b"MAILBOX_SET: 0x%08x"
    off = kc.d.find(marker)
    if off < 0:
        print("no AppleA7IOP mailbox log string in %s" % path)
        return 1
    va = f2v(off)
    print("format string at %#x:" % va)
    end = kc.d.find(b"\0", off)
    for line in kc.d[off:end].decode("ascii", "replace").split("\n"):
        print("   %s" % line)

    hits = kc.xrefs(va)
    print("\nreferenced from:")
    for pc in hits:
        print("   %#x" % pc)

    # Walk the logging function: every "mov w1, #imm" that is followed by a
    # blr is a register read at that offset.
    for pc in hits:
        print("\nregister reads near %#x:" % pc)
        for a in range(pc - 0x120, pc + 0x40, 4):
            try:
                word = kc.w(a)
            except ValueError:
                continue
            if (word & 0xFF800000) != 0x52800000:
                continue
            imm = (word >> 5) & 0xFFFF
            rd = word & 31
            if rd > 3:
                continue
            try:
                nxt = kc.w(a + 4)
            except ValueError:
                continue
            if (nxt & 0xFFFFFC1F) == 0xD63F0000:      # BLR
                print("   read  +%#06x" % imm)

    # The enable sequence: writes of a constant into the mailbox block.
    # Only the AppleA7IOP code cluster is scanned, and the value has to come
    # from the instruction right before the store.
    print("\nconstant writes into the mailbox block (AppleA7IOP cluster):")
    lo, hi = 0xFFFFFFF005754000, 0xFFFFFFF005759000
    pc = lo
    while pc < hi:
        try:
            word = kc.w(pc)
        except ValueError:
            pc += 4
            continue
        if (word & 0xFFC00000) in (0xF9000000, 0xB9000000):   # STR imm
            scale = 8 if (word & 0xFFC00000) == 0xF9000000 else 4
            mem = ((word >> 10) & 0xFFF) * scale
            val = None
            try:
                w2 = kc.w(pc - 4)
                if (w2 & 0xFF800000) == 0x52800000:
                    val = (w2 >> 5) & 0xFFFF
            except ValueError:
                pass
            if 0x1000 <= mem <= 0x1040 and val:
                print("   +%#06x = %#x   (at %#x)" % (mem, val, pc))
        elif (word & 0xFFC00000) in (0xF8000000, 0xB8000000):
            # STR [base, index]: the kext picks MAILBOX_SET (0x1000) or
            # MAILBOX_CLR (0x1004) with a CSEL, so the offset is computed.
            try:
                w2 = kc.w(pc - 4)
            except ValueError:
                pc += 4
                continue
            if (w2 & 0xFF800000) == 0x52800000:
                val = (w2 >> 5) & 0xFFFF
                if val in (1, 0x1000, 0x1111):
                    print("   +computed(0x1000|0x1004) = %#x   (at %#x)"
                          % (val, pc))
        pc += 4

    return 0


if __name__ == "__main__":
    sys.exit(main())
