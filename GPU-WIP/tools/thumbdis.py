#!/usr/bin/env python3
"""Disassemble a Thumb-2 range of a raw binary with llvm-mc.

usage: thumbdis.py <bin> <offset> [count] [base-addr]
"""
import subprocess, sys

path = sys.argv[1]
off = int(sys.argv[2], 0)
n = int(sys.argv[3]) if len(sys.argv) > 3 else 32
base = int(sys.argv[4], 0) if len(sys.argv) > 4 else 0
d = open(path, 'rb').read()
blob = d[off:off + 2 * n]
lines = []
for i in range(0, len(blob) - 1, 2):
    lines.append('0x%02x 0x%02x' % (blob[i], blob[i + 1]))
out = subprocess.run(['llvm-mc', '--disassemble', '--triple=thumbv7', '-'],
                     input='\n'.join(lines), capture_output=True, text=True)
ins = out.stdout.splitlines()
for i, s in enumerate(ins):
    print('%#010x: %s' % (base + off + 2 * i, s.strip()))
if out.stderr.strip():
    print('# stderr:', out.stderr.strip()[:300])
