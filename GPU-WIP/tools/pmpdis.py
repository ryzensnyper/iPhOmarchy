#!/usr/bin/env python3
"""Correctly-addressed Thumb-2 disassembly of the PMP firmware.

llvm-mc prints one line per *instruction*, so the addresses have to be
accumulated from the encoding lengths -- not from the byte offset.

usage: pmpdis.py <file-offset> <byte-count>
"""
import subprocess
import sys

PATH = '/home/doug/a11-fw/out/pmp-t8015.bin'
BASE = 0x01000000

d = open(PATH, 'rb').read()
off = int(sys.argv[1], 0)
n = int(sys.argv[2], 0)
blob = d[off:off + n]
lines = ['0x%02x 0x%02x' % (blob[i], blob[i + 1]) for i in range(0, len(blob) - 1, 2)]
out = subprocess.run(['llvm-mc', '--disassemble', '--show-encoding', '--triple=thumbv7', '-'],
                     input='\n'.join(lines), capture_output=True, text=True)
pc = BASE + off
for line in out.stdout.splitlines():
    if 'encoding' not in line:
        continue
    asm, enc = line.split('@ encoding:')
    asm = asm.strip()
    try:
        b = bytes(int(x, 16) for x in
                  enc.replace('[', '').replace(']', '').replace(',', ' ').split())
    except Exception:
        print('%#010x: %s' % (pc, asm))
        continue
    print('%#010x: %-46s ; %s' % (pc, asm, ' '.join('%02x' % x for x in b)))
    pc += len(b)
