#!/usr/bin/env python3
"""Full-field decode of frames in a time window from a cat /dev/kmsg log."""
import sys, re

t_lo, t_hi = float(sys.argv[2]), float(sys.argv[3])
frames = []
cur = None
for line in open(sys.argv[1]):
    m = re.match(r"6,\d+,(\d+),-;apple-z2 spi0.0: irq-frame\+(\d+): ([0-9a-f ]+)", line)
    if not m:
        continue
    ts = int(m.group(1)) / 1e6
    off, hexs = int(m.group(2)), m.group(3).strip()
    b = bytes.fromhex(hexs.replace(" ", ""))
    if off == 0 or cur is None:
        cur = [ts, {}]
        frames.append(cur)
    cur[1][off] = b

for ts, segs in frames:
    if not (t_lo <= ts <= t_hi):
        continue
    buf = b"".join(segs[o] for o in sorted(segs))
    if len(buf) < 30 or buf[0] != 0xEA:
        continue
    msg = buf[5:]
    if msg[0] != 0x44:
        continue
    n = msg[16]
    print(f"t={ts:9.3f} seq={buf[1]:02x} nf={n}")
    for i in range(n):
        f = msg[24 + 30 * i: 24 + 30 * (i + 1)]
        if len(f) < 28:
            print("   TRUNCATED"); continue
        fid, st = f[0], f[1]
        ax = int.from_bytes(f[4:6], "little", signed=True)
        ay = int.from_bytes(f[6:8], "little", signed=True)
        tmaj = int.from_bytes(f[12:14], "little")
        tmin = int.from_bytes(f[14:16], "little")
        ori = int.from_bytes(f[16:18], "little", signed=True)
        cmaj = int.from_bytes(f[18:20], "little")
        cmin = int.from_bytes(f[20:22], "little")
        pres = int.from_bytes(f[26:28], "little")
        area = tmaj * tmin
        print(f"   f{fid} st={st} raw=({ax:6d},{ay:6d}) tool={tmaj:5d}x{tmin:5d} area={area:9d} "
              f"touch={cmaj:5d}x{cmin:5d} ori={ori:6d} pres={pres}")
