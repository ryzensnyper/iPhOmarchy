#!/usr/bin/env python3
"""Extract the T8015 (A11) G10P / Kingfisher GPU firmware image from an
Apple kernelcache.  Prints offsets and sizes; writes the image only to a
path outside the repo (the image itself is an Apple binary blob and must
not be committed).

Usage: kf-img-extract.py <d21ap-kernelcache.macho> <out.img>

The firmware lives in kext com.apple.AGXFirmwareKextG10PRTBuddy:
  __TEXT,__const at kernelcache file offset 0xbfa99f, 0x5d329 bytes;
  the loadable image = __const[9 : 9+0x5d320] (the 9-byte "\\0Release\\0\\6\\0\\0"
  container wrapper is stripped; see kb/A11-GPU-G10P-LAYOUT.md §0).
Image structure: A32 vector table at 0 (vector0 `b 0x20`, then `b .` x7),
ARM reset stub at 0x20, Thumb-2 body.
"""
import struct
import sys

# kernelcache file offset/size of AGXFirmwareKextG10PRTBuddy __TEXT,__const
# (verified against the __PRELINK_INFO load addr 0xfffffff005032040 / size
# 0x5dc88 and the segment table: __const vm 0xfffffff00503299f -> file 0xbfa99f)
CONST_OFF = 0xBFA99F
CONST_SIZE = 0x5D329
IMG_SKIP = 9
IMG_SIZE = 0x5D320


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    data = open(sys.argv[1], 'rb').read()
    const = data[CONST_OFF:CONST_OFF + CONST_SIZE]
    assert len(const) == CONST_SIZE, 'kernelcache too small?'
    assert const[:9] == b'\0Release\0\x06\0\0', 'unexpected wrapper: %r' % const[:9]
    img = const[IMG_SKIP:IMG_SKIP + IMG_SIZE]
    v0 = struct.unpack_from('<I', img, 0)[0]
    tgt = 8 + (v0 & 0xFFFFFF) * 4
    print('image: %d bytes (0x%x)' % (len(img), len(img)))
    print('vector0 = 0x%08x (b 0x%x)' % (v0, tgt))
    print('reset stub at 0x20, Thumb-2 body follows')
    open(sys.argv[2], 'wb').write(img)
    print('wrote', sys.argv[2])


if __name__ == '__main__':
    main()
