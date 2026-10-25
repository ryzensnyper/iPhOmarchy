#!/usr/bin/env python3
"""
Extract the Apple SmartIO coprocessor firmware from an *already-decompressed*
prelinked kernelcache (monolithic MH_EXECUTE, as shipped for iPhone A10/A11).

How it works
------------
The SmartIO firmware is a raw ARM64 image embedded in the kext's data segment
(`__PRELINK_DATA`). Its first 32 bytes are the boot vector table, identical on
A10 and A11:

    0e0400ea feffffea feffffea feffffea feffffea feffffea feffffea feffffea

That 32-byte pattern is unique in the kernelcache, so it locates the blob. The
blob's *length* is not in the blob; the kext stores it as an `{address, length}`
pair elsewhere — a little-endian u64 pointer to the firmware's runtime address
followed by a u64 length. So:

  1. parse the Mach-O segment table to map file offset <-> runtime address;
  2. find the unique vector pattern -> firmware file offset;
  3. its runtime address = segment.vmaddr + (offset - segment.fileoff);
  4. scan for that address as a LE64 pointer; the next LE64 is the length.

Usage:
    python3 extract-smartio.py <decompressed-kernelcache> <out.bin>

Decompress first, e.g.:  ipsw kernel dec kernelcache.release.<board> -o out
"""
import struct, sys

VECTOR = bytes.fromhex("0e0400eafeffffeafeffffeafeffffea"
                       "feffffeafeffffeafeffffeafeffffea")
LC_SEGMENT_64 = 0x19


def parse_segments(d):
    magic, cputype, cpusub, ftype, ncmds, sizeofcmds = struct.unpack_from("<IIIIII", d, 0)
    if magic not in (0xFEEDFACF, 0xCFFAEDFE):
        sys.exit("not a 64-bit Mach-O (decompress the kernelcache first)")
    off = 32
    segs = []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", d, off)
        if cmd == LC_SEGMENT_64:
            name = d[off + 8:off + 24].split(b"\0", 1)[0].decode(errors="replace")
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<QQQQ", d, off + 24)
            segs.append((name, vmaddr, vmsize, fileoff, filesize))
        off += cmdsize
    return segs


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    kc, out = sys.argv[1], sys.argv[2]
    d = bytes(open(kc, "rb").read())
    segs = parse_segments(d)

    hits = []
    i = d.find(VECTOR)
    while i >= 0:
        hits.append(i)
        i = d.find(VECTOR, i + 1)
    if len(hits) != 1:
        sys.exit("expected exactly one SmartIO vector pattern, found %d" % len(hits))
    foff = hits[0]

    seg = next((s for s in segs if s[3] <= foff < s[3] + s[4]), None)
    if not seg:
        sys.exit("firmware offset %#x not inside a segment" % foff)
    name, vmaddr, vmsize, sfileoff, sfilesize = seg
    raddr = vmaddr + (foff - sfileoff)

    pat = struct.pack("<Q", raddr)
    size = None
    j = d.find(pat)
    while j >= 0:
        cand = struct.unpack_from("<Q", d, j + 8)[0]
        if 0 < cand <= sfilesize and j + 16 <= len(d):
            # prefer the descriptor whose length stays within the segment
            if foff + cand <= sfileoff + sfilesize:
                size = cand
                break
        j = d.find(pat, j + 1)
    if not size:
        sys.exit("could not find a length for the firmware at %#x" % raddr)

    fw = d[foff:foff + size]
    open(out, "wb").write(fw)
    import hashlib
    print("segment   : %s (vmaddr %#x, file %#x)" % (name, vmaddr, sfileoff))
    print("firmware  : file %#x  runtime %#x  size %d (0x%x)" % (foff, raddr, size, size))
    print("wrote %s  sha256 %s" % (out, hashlib.sha256(fw).hexdigest()))


if __name__ == "__main__":
    main()
