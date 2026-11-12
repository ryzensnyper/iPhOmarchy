#!/usr/bin/env python3
"""Disassemble the PMP firmware (Thumb-2) with capstone via ctypes.

Usage:
    python3 pmp-dis.py 0x0100e940 60        # VA and instruction count
"""

import ctypes
import struct
import sys

FW = "/home/doug/a11-fw/out/pmp-t8015.bin"
BASE = 0x01000000

CS_ARCH_ARM = 0
CS_MODE_THUMB = 16      # capstone v6 numbering (this lib's header)
CS_MODE_MCLASS = 32

lib = ctypes.CDLL("/usr/lib/libcapstone.so")


class CsInsn(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_uint),
        ("address", ctypes.c_uint64),
        ("size", ctypes.c_ushort),
        ("bytes", ctypes.c_ubyte * 16),
        ("mnemonic", ctypes.c_char * 32),
        ("op_str", ctypes.c_char * 160),
        ("detail", ctypes.c_void_p),
    ]


lib.cs_open.restype = ctypes.c_int
lib.cs_open.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
lib.cs_disasm.restype = ctypes.c_size_t
lib.cs_disasm.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                          ctypes.c_uint64, ctypes.c_size_t,
                          ctypes.POINTER(ctypes.POINTER(CsInsn))]
lib.cs_free.restype = None
lib.cs_free.argtypes = [ctypes.POINTER(CsInsn), ctypes.c_size_t]
lib.cs_strerror.restype = ctypes.c_char_p
lib.cs_strerror.argtypes = [ctypes.c_int]

DATA = open(FW, "rb").read()


def dis(va, count=64, show_strings=True):
    off = va - BASE
    code = DATA[off:off + 4 * count + 32]
    handle = ctypes.c_void_p()
    rc = lib.cs_open(CS_ARCH_ARM, CS_MODE_THUMB, ctypes.byref(handle))
    if rc:
        print("cs_open failed:", lib.cs_strerror(rc))
        return
    insn = ctypes.POINTER(CsInsn)()
    n = lib.cs_disasm(handle, code, len(code), va, count, ctypes.byref(insn))
    for i in range(n):
        a = insn[i]
        raw = bytes(a.bytes[:a.size]).hex(' ')
        extra = ""
        if show_strings:
            for w in struct.unpack_from('<%dI' % (a.size // 4), bytes(a.bytes[:a.size])):
                if BASE <= w < BASE + len(DATA):
                    st = DATA[w - BASE:w - BASE + 48].split(b'\0')[0]
                    if len(st) > 2 and all(32 <= c < 127 for c in st):
                        extra = '   ; "%s"' % st.decode()
                        break
        print("%#010x: %-12s %-9s %s%s" % (a.address, raw,
                                            a.mnemonic.decode(), a.op_str.decode(), extra))
    lib.cs_free(insn, n)


if __name__ == "__main__":
    va = int(sys.argv[1], 0)
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 64
    dis(va, n)
