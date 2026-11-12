#!/usr/bin/env python3
"""Reverse the AppleA7IOP kext's G10P (A11) IOP class out of the D21 kernelcache.

The A11's GFX IOP is driven by the class ``AppleA7IOPV4GFX`` (source file
``AppleA7IOPV4GFX.cpp``), *not* by the V2 class the original bring-up spec was
copied from.  This script prints:

  * the class hierarchy and the REQUIRE strings the kext carries,
  * the class vtable and which slots the GFX overrides,
  * the register accessor (the thing that turns a byte offset into a read),
  * every register offset the kext passes through that accessor, and
  * the mailbox layout that falls out of it.

Nothing here touches the phone; it is all offline work on the kernelcache.

usage:  a7iop-v4-gfx.py [path/to/kernelcache]
"""
import struct
import sys
import os

KC = sys.argv[1] if len(sys.argv) > 1 else '/tmp/opencode/d21ap-kernelcache.macho'

# --- the kernelcache's segments (from its LC_SEGMENT_64 commands) -------------
SEGS = [
    ('__TEXT',           0xfffffff007004000, 0x0b8000, 0x000000),
    ('__DATA_CONST',     0xfffffff0070bc000, 0x0f8000, 0x0b8000),
    ('__TEXT_EXEC',      0xfffffff0071b4000, 0x680000, 0x1b0000),
    ('__DATA',           0xfffffff007844000, 0x0ac000, 0x840000),
    ('__BOOTDATA',       0xfffffff0078f0000, 0x040000, 0x864000),
    ('__PRELINK_TEXT',   0xfffffff004db4000, 0x7cc000, 0x97c000),
    ('__PLK_TEXT_EXEC',  0xfffffff005580000, 0x16dc000, 0x1148000),
    ('__PRELINK_DATA',   0xfffffff007a08000, 0x1b4000, 0x2bcc000),
    ('__PLK_DATA_CONST', 0xfffffff006c5c000, 0x3a8000, 0x2824000),
]

D = open(KC, 'rb').read()


def v2f(va):
    for n, v, vs, fo in SEGS:
        if v <= va < v + vs:
            return n, fo + (va - v)
    raise ValueError(hex(va))


def f2v(off):
    for n, v, vs, fo in SEGS:
        if fo <= off < fo + vs:
            return n, v + (off - fo)
    raise ValueError(hex(off))


def segof(va):
    try:
        return v2f(va)[0]
    except ValueError:
        return None


def q(va):
    n, off = v2f(va)
    return struct.unpack_from('<Q', D, off)[0]


def cstr(va, maxlen=120):
    try:
        n, off = v2f(va)
    except ValueError:
        return None
    end = D.find(b'\0', off)
    if end < 0 or end - off > maxlen:
        return None
    b = D[off:end]
    if not b or any(c < 0x20 or c > 0x7e for c in b):
        return None
    return b.decode()


def find_bytes(pat):
    """Yield the file offsets of every occurrence of pat."""
    i = 0
    while True:
        i = D.find(pat, i)
        if i < 0:
            return
        yield i
        i += 1


def off2va(off):
    n, va = f2v(off)
    return va


# --------------------------------------------------------------------------
# 1. the class hierarchy, from the kext's REQUIRE strings
# --------------------------------------------------------------------------
IOP_CLASSES = ('AppleIOP', 'AppleA7IOP', 'AppleM3Wrap', 'AppleMxWrap',
              'AppleASC', 'AppleANS2', 'AppleRTBuddy')


def classes():
    """The AppleA7IOP kext's own classes, from its 'site.<class>' strings."""
    print('=== the classes the AppleA7IOP kext declares')
    seen = {}
    for off in find_bytes(b'site.'):
        s = cstr(off2va(off))
        if s and s.startswith('site.') and len(s) > 5:
            name = s[5:]
            if name.startswith(IOP_CLASSES):
                seen.setdefault(name, []).append(off2va(off))
    for name in sorted(seen):
        print('   %-24s site string at %#x' % (name, seen[name][0]))
    print()

    print('=== the REQUIRE strings: file, function, condition')
    for off in find_bytes(b'/Library/Caches/com.apple.xbs/Sources/AppleA7IOP/'):
        s = cstr(off2va(off), 200)
        if s:
            print('   %s' % s)
    print()


# --------------------------------------------------------------------------
# 2. the vtables
# --------------------------------------------------------------------------
GFX_VTABLE = 0xfffffff006ccc660
M3WRAP_VTABLE = 0xfffffff006ccb258


def vtable(name, va):
    print('=== %s vtable at %#x' % (name, va))
    kext = []
    for i in range(-4, 400):
        p = q(va + 8 * i)
        if p == 0:
            print('   (ends at slot %+d, %d slots)' % (i - 1, i + 4))
            break
        if segof(p) == '__PLK_TEXT_EXEC':
            kext.append((i, p))
    print('   %d kext-code slots: %s' % (len(kext),
          ', '.join('%+d:%#x' % (i, p) for i, p in kext)))
    return kext


# --------------------------------------------------------------------------
# 3. the register accessor, and every offset read through it
# --------------------------------------------------------------------------
def accessor():
    """The GFX's readRegister(): ldr x8,[x0,#256]; ldr w0,[x8,w1,uxtw]; ret."""
    print('=== the register accessor (ivar +0x100 = the mapped block)')
    want = 0xF9408008           # ldr x8, [x0, #256]
    for va0, vs, fo in [(s[1], s[2], s[3]) for s in SEGS if s[0] == '__PLK_TEXT_EXEC']:
        off = fo
        while off + 12 <= fo + vs:
            w = struct.unpack_from('<I', D, off)[0]
            if w == want:
                w2 = struct.unpack_from('<I', D, off + 4)[0]
                # ldr w0, [x8, w1, uxtw] == 0xB9807800 | Rm<<16 | option<<13 | S<<12 | Rn<<5 | Rt
                if (w2 & 0xFFE00C00) == 0xB9807800:
                    print('   accessor at %#x:  ldr x8,[x0,#256]; ldr w0,[x8,w1,uxtw]; ret'
                          % (va0 + (off - fo)))
            off += 4
    print()


def offsets_read():
    """Every offset the kext passes to the metaclass dispatch slot 1600."""
    print('=== register offsets read through the dispatch slot (metaclass+1600)')
    res = {}
    va0, vs, fo = [s[1:] for s in SEGS if s[0] == '__PLK_TEXT_EXEC'][0]
    W = []
    off = fo
    while off + 4 <= fo + vs:
        W.append(struct.unpack_from('<I', D, off)[0])
        off += 4
    base = va0 - fo
    for i in range(len(W) - 3):
        w1, w2, w3 = W[i], W[i + 1], W[i + 2]
        if (w1 & 0xFFE0FC00) != 0xF9402000:      # ldr xRt, [xRn, #1600]
            continue
        if (w2 & 0xFFE00000) != 0x52800000:      # movz w1, #imm
            continue
        if (w2 & 0x00300000) or (w2 & 0x1f) != 1:
            continue
        if (w3 & 0xFFFFFC1F) != 0xD63F0000:       # blr
            continue
        res.setdefault((w2 >> 5) & 0xffff, []).append(base + 4 * i)
    for off in sorted(res):
        print('   +%#06x  %2d uses   %s' % (off, len(res[off]),
              ', '.join('%#x' % p for p in res[off][:4])))
    print()
    return res


def main():
    print('kernelcache: %s (%d bytes)\n' % (KC, len(D)))
    classes()
    g = vtable('AppleA7IOPV4GFX', GFX_VTABLE)
    m = vtable('AppleM3WrapV2 (base)', M3WRAP_VTABLE)
    print('\n=== the slots the GFX overrides (vs the M3Wrap base)')
    for i, p in g:
        if i >= 85 and i < 85 + len(m):
            bi, bp = m[i - 85]
            if p != bp:
                print('   slot %+3d : %#x  (base has %#x)' % (i, p, bp))
    print()
    accessor()
    res = offsets_read()
    print('=== the G10P mailbox, as the V4 GFX class sees it')
    for name, off in (('CPU_CTRL', 0x110), ('CPU_CTRL status', 0x114),
                      ('TX data', 0x800), ('RX data', 0x830)):
        print('   %-16s +%#06x' % (name, off))
    print()


if __name__ == '__main__':
    main()
