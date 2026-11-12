#!/usr/bin/env python3
"""Find ADRP(+ADD/LDR) cross-references to a VA in the D21 kernelcache."""
import struct, sys

KC = '/tmp/opencode/d21ap-kernelcache.macho'
SEGS = [
    ('__TEXT', 0xfffffff007004000, 0xb8000, 0x0, 0xb8000),
    ('__DATA_CONST', 0xfffffff0070bc000, 0xf8000, 0xb8000, 0xf8000),
    ('__TEXT_EXEC', 0xfffffff0071b4000, 0x680000, 0x1b0000, 0x680000),
    ('__KLD', 0xfffffff007834000, 0x4000, 0x830000, 0x4000),
    ('__LASTDATA_CONST', 0xfffffff007838000, 0x4000, 0x834000, 0x4000),
    ('__LAST', 0xfffffff00783c000, 0x4000, 0x838000, 0x4000),
    ('__KLDDATA', 0xfffffff007840000, 0x4000, 0x83c000, 0x4000),
    ('__DATA', 0xfffffff007844000, 0xac000, 0x840000, 0x24000),
    ('__BOOTDATA', 0xfffffff0078f0000, 0x40000, 0x864000, 0x40000),
    ('__PRELINK_TEXT', 0xfffffff004db4000, 0x7cc000, 0x97c000, 0x7cc000),
    ('__PRELINK_INFO', 0xfffffff007bbc000, 0x328000, 0x2d80000, 0x328000),
    ('__PLK_TEXT_EXEC', 0xfffffff005580000, 0x16dc000, 0x1148000, 0x16dc000),
    ('__PRELINK_DATA', 0xfffffff007a08000, 0x1b4000, 0x2bcc000, 0x1b4000),
    ('__PLK_DATA_CONST', 0xfffffff006c5c000, 0x3a8000, 0x2824000, 0x3a8000),
]
D = open(KC, 'rb').read()

def v2f(va):
    for n, v, vs, fo, fs in SEGS:
        if v <= va < v + min(vs, fs):
            return n, fo + (va - v)
    raise ValueError(hex(va))

def f2v(off):
    for n, v, vs, fo, fs in SEGS:
        if fo <= off < fo + fs:
            return n, v + (off - fo)
    raise ValueError(hex(off))

CODE_SEGS = ['__TEXT_EXEC', '__PLK_TEXT_EXEC', '__TEXT']
PTR_SEGS = ['__DATA_CONST', '__PRELINK_DATA', '__PLK_DATA_CONST', '__DATA', '__KLDDATA']

def xrefs(target, want_ptr=True):
    hits = []
    for name, v, vs, fo, fs in SEGS:
        if name not in CODE_SEGS:
            continue
        end = fo + min(vs, fs)
        off = fo
        while off + 8 <= end:
            w = struct.unpack_from('<I', D, off)[0]
            if (w & 0x9f000000) == 0x90000000:
                rd = w & 31
                imm = (((w >> 5) & 0x7ffff) << 2) | ((w >> 29) & 3)
                if imm & (1 << 20):
                    imm -= 1 << 21
                pc = v + (off - fo)
                page = (pc & ~0xfff) + (imm << 12)
                for j in range(1, 4):
                    w2 = struct.unpack_from('<I', D, off + 4 * j)[0]
                    if (w2 & 0xff800000) == 0x91000000 and ((w2 >> 5) & 31) == rd:
                        if page + ((w2 >> 10) & 0xfff) == target:
                            hits.append((pc, name))
            off += 4
    ptr = []
    if want_ptr:
        pat = struct.pack('<Q', target)
        i = 0
        while True:
            i = D.find(pat, i)
            if i < 0:
                break
            try:
                n, va = f2v(i)
                if n in PTR_SEGS or n in ('__BOOTDATA', '__KLD'):
                    ptr.append((va, n))
            except ValueError:
                pass
            i += 1
    return hits, ptr

if __name__ == '__main__':
    for a in sys.argv[1:]:
        t = int(a, 0)
        h, p = xrefs(t)
        print("target %#x" % t)
        for pc, n in h:
            print("   code %#x (%s)" % (pc, n))
        for va, n in p:
            print("   ptr  %#x (%s)" % (va, n))
