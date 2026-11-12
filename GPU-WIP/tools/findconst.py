#!/usr/bin/env python3
"""Search binaries for 32/64-bit constants (LE) -- e.g. register addresses.

usage: findconst.py <file> <const> [const ...]
prints every file offset where the constant appears, as LE32 and LE64.
"""
import struct, sys

path = sys.argv[1]
d = open(path, 'rb').read()
for arg in sys.argv[2:]:
    v = int(arg, 0)
    hits = []
    for fmt, size in (('<I', 4), ('<Q', 8)):
        if size == 4 and v > 0xffffffff:
            continue
        pat = struct.pack(fmt, v)
        start = 0
        while True:
            i = d.find(pat, start)
            if i < 0:
                break
            hits.append('%s@%#x' % ('le32' if size == 4 else 'le64', i))
            start = i + 1
    print('%-16s %s' % (arg, ' '.join(hits) if hits else '(none)'))
