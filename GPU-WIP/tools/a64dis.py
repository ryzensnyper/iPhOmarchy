#!/usr/bin/env python3
"""Disassemble a raw arm64 binary with llvm-objdump.

usage: a64dis.py <bin> [base-addr] > out.asm
"""
import subprocess, sys

path = sys.argv[1]
base = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0
out = subprocess.run(['llvm-objdump', '-D', '--triple=aarch64', '--adjust-vma=%#x' % base,
                      '-b', 'binary', path], capture_output=True, text=True)
sys.stdout.write(out.stdout)
sys.stderr.write(out.stderr)
