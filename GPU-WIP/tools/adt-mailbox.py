#!/usr/bin/env python3
"""Walk the D21 ADT: print every node whose regs land in the GFX/IOP address
area, plus every node whose path mentions a mailbox."""
import sys
sys.path.insert(0, '/home/doug/m1n1/proxyclient')
from m1n1 import adt as A

dt = A.load_adt(open('/home/doug/omarchy-iphone/adt/dt_raw.bin', 'rb').read())

def walk(node):
    for v in node._children:
        path = v._path
        name = getattr(v, 'name', '')
        hits = []
        try:
            for r in v.reg:
                if 0x4c00000 <= r.addr < 0x4f00000 or 0x1c00000 <= r.addr < 0x2000000:
                    hits.append('%#x+%#x' % (r.addr, r.size))
        except Exception:
            pass
        low = path.lower()
        if hits or 'mbox' in low or 'mailbox' in low:
            ints = ''
            try:
                ints = ' ints=%s' % (list(v.interrupts),)
            except Exception:
                pass
            comp = ''
            try:
                c = v.compatible
                comp = ' compatible=%r' % (list(c) if not isinstance(c, str) else c,)
            except Exception:
                pass
            print('%-52s name=%-14s reg=%s%s%s' % (path, name, ','.join(hits), ints, comp))
        walk(v)

walk(dt)
