#!/usr/bin/env python3
"""Decode ALL fingers from full irq-frame dumps in kmsg (frame_dump=1)."""
import sys, re

# Reassemble frames sequentially: a new frame starts at irq-frame+0.
frames = []
cur = None
for line in open(sys.argv[1]):
    m = (re.match(r"6,\d+,(\d+),-;apple-z2 spi0.0: irq-frame\+(\d+): ([0-9a-f ]+)", line)
         or re.match(r"\[\s*([0-9.]+)\] apple-z2 spi0.0: irq-frame\+(\d+): ([0-9a-f ]+)", line)
         or re.match(r"(?:\S+ ){5}apple-z2 spi0.0: irq-frame\+(\d+): ([0-9a-f ]+)", line))
    if not m:
        continue
    if m.lastindex == 2:  # journal format: no numeric ts; use clock time placeholder
        off, hexs = int(m.group(1)), m.group(2)
        ts = None
    else:
        ts, off, hexs = m.group(1), int(m.group(2)), m.group(3).strip()
        ts = int(float(ts) * 1e6) if "." in str(ts) else int(ts)
    b = bytes.fromhex(hexs.replace(" ", ""))
    if off == 0 or cur is None:
        cur = [ts, {}]
        frames.append(cur)
    cur[1][off] = b

for ts, segs in frames:
    buf = b"".join(segs[o] for o in sorted(segs))
    if len(buf) < 30 or buf[0] != 0xEA:
        continue
    msg = buf[5:]
    if msg[0] != 0x44 or len(msg) < 25:
        continue
    n = msg[16]
    if n == 0:
        continue
    t = (ts / 1e6) if ts is not None else -1.0
    out = [f"t={t:8.3f} seq={buf[1]:02x} nf={n}"]
    for i in range(n):
        f = msg[24 + 30*i: 24 + 30*(i+1)]
        if len(f) < 28:
            out.append(f"  f{i}: TRUNCATED")
            continue
        fid, state = f[0], f[1]
        ax = int.from_bytes(f[4:6], "little", signed=True)
        ay = int.from_bytes(f[6:8], "little", signed=True)
        tmaj = int.from_bytes(f[12:14], "little")
        pres = int.from_bytes(f[26:28], "little")
        # surface: x -224..6608, y -236..11904 -> screen 1080x1920
        sx = max(0, min(1079, round((ax + 224) / (6608 + 224) * 1079)))
        sy = max(0, min(1919, round((ay + 236) / (11904 + 236) * 1919)))
        out.append(f"  f{fid} st={state} raw=({ax:6d},{ay:6d}) screen=({sx:4d},{sy:4d}) tool={tmaj:5d} pres={pres}")
    print("\n".join(out))
