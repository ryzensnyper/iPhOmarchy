#!/usr/bin/env python3
"""Disassemble a VA range of the D21 kernelcache with ADRP targets resolved
to VAs, annotating any pointer that lands in a C string.

usage: kcdis2.py <va> [count]
"""
import struct, subprocess, sys
sys.path.insert(0, '/tmp/opencode')
from xref import D, v2f, SEGS

def cstr(va, maxlen=80):
    try:
        name, off = v2f(va)
    except ValueError:
        return None
    end = D.find(b'\0', off)
    if end < 0 or end - off > 400:
        return None
    b = D[off:end]
    if not b or any(c < 0x20 or c > 0x7e for c in b):
        return None
    try:
        return b.decode()
    except Exception:
        return None

def dis(va, n=64):
    name, off = v2f(va)
    d = D[off:off + 4 * n]
    lines = []
    for i in range(len(d) // 4):
        w = d[4 * i:4 * i + 4]
        lines.append('0x%02x' % w[0]); lines.append('0x%02x' % w[1])
        lines.append('0x%02x' % w[2]); lines.append('0x%02x' % w[3])
    out = subprocess.run(['llvm-mc', '--disassemble', '--triple=aarch64', '-'],
                         input='\n'.join(lines), capture_output=True, text=True)
    ins = out.stdout.splitlines()
    res = []
    for i, s in enumerate(ins):
        pc = va + 4 * i
        w = struct.unpack_from('<I', D, off + 4 * i)[0]
        extra = ''
        if (w & 0x9f000000) == 0x90000000:  # ADRP
            rd = w & 31
            imm = (((w >> 5) & 0x7ffff) << 2) | ((w >> 29) & 3)
            if imm & (1 << 20):
                imm -= 1 << 21
            page = (pc & ~0xfff) + (imm << 12)
            # look ahead for the ADD/LDR that completes it
            for j in range(1, 4):
                if pc + 4 * j >= va + 4 * n:
                    break
                w2 = struct.unpack_from('<I', D, off + 4 * (i + j))[0]
                if (w2 & 0xff800000) == 0x91000000 and ((w2 >> 5) & 31) == rd:
                    tgt = page + ((w2 >> 10) & 0xfff)
                    s2 = cstr(tgt)
                    extra = '  ; -> %#x %s' % (tgt, repr(s2) if s2 else '')
                    break
        res.append('%#011x: %-34s%s' % (pc, s.strip(), extra))
    return '%s\n' % name + '\n'.join(res)

if __name__ == '__main__':
    va = int(sys.argv[1], 0)
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 64
    print(dis(va, n))
