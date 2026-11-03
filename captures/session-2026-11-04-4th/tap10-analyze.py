#!/usr/bin/env python3
"""Lifecycle analysis of tap10-decoded.txt: per-finger lifecycles, active vs ghost, regional."""
import re, sys
from collections import defaultdict

frames = []  # (t, [(fid, st, sx, sy, tool, pres)])
for line in open(sys.argv[1]):
    m = re.match(r"t=\s*([\d.]+) seq=\S+ nf=(\d+)", line)
    if m:
        frames.append((float(m.group(1)), []))
        continue
    m = re.match(r"\s+f(\d+) st=(\d+) raw=\(\s*(-?\d+),\s*(-?\d+)\) screen=\(\s*(\d+),\s*(\d+)\) tool=\s*(\d+) pres=(\d+)", line)
    if m and frames:
        fid, st = int(m.group(1)), int(m.group(2))
        sx, sy, tool, pres = int(m.group(5)), int(m.group(6)), int(m.group(7)), int(m.group(8))
        frames[-1][1].append((fid, st, sx, sy, tool, pres))

t0, t1 = frames[0][0], frames[-1][0]
print(f"window: t={t0:.1f}..{t1:.1f} ({t1-t0:.1f}s), {len(frames)} frames with contacts")

# lifecycles: a lifecycle starts at st=3 (or first sighting after absence) and ends at
# disappearance or st=0. Keyed by fid; guard against fid reuse by requiring a gap.
active = defaultdict(list)  # fid -> list of frames
last_seen = {}
lifecycles = []  # (fid, t_start, t_end, frames[list])
open_lc = {}
prev_t = None
for t, fings in frames:
    seen = set()
    for fid, st, sx, sy, tool, pres in fings:
        seen.add(fid)
        active[fid].append((t, st, sx, sy, tool, pres))
        if fid not in open_lc:
            open_lc[fid] = [fid, t, t, [(t, st, sx, sy, tool, pres)]]
        else:
            lc = open_lc[fid]
            # new lifecycle if gap > 1.0 s
            if prev_t is not None and t - last_seen.get(fid, t) > 1.0:
                lifecycles.append(open_lc.pop(fid))
                open_lc[fid] = [fid, t, t, [(t, st, sx, sy, tool, pres)]]
            else:
                lc[2] = t
                lc[3].append((t, st, sx, sy, tool, pres))
        last_seen[fid] = t
    # fingers not seen this frame: close lifecycles unseen for > 0.35 s
    for fid in list(open_lc):
        if t - last_seen.get(fid, t) > 0.35:
            lifecycles.append(open_lc.pop(fid))
    prev_t = t
for fid in list(open_lc):
    lifecycles.append(open_lc.pop(fid))

def summarize(lc):
    fid, ts, te, fs = lc
    maxpres = max(p for _, _, _, _, _, p in fs)
    sts = sorted(set(s for _, s, _, _, _, _ in fs))
    sx = [x for _, _, x, _, _, _ in fs]
    sy = [y for _, _, _, y, _, _ in fs]
    tools = [tl for _, _, _, _, tl, _ in fs]
    return dict(fid=fid, t0=ts, t1=te, dur=te-ts, n=len(fs), maxpres=maxpres,
                sts=sts, cx=sum(sx)//len(sx), cy=sum(sy)//len(sy),
                tool=max(tools), region=("TOP" if sum(sy)/len(sy) < 960 else "BOTTOM"))

acts = [summarize(l) for l in lifecycles if summarize(l)["maxpres"] >= 128]
ghosts = [summarize(l) for l in lifecycles if summarize(l)["maxpres"] < 128]

print(f"\n=== ACTIVE lifecycles (max pres >= 128): {len(acts)} ===")
for a in sorted(acts, key=lambda x: x["t0"]):
    print(f"  f{a['fid']} t={a['t0']:.1f}-{a['t1']:.1f} ({a['dur']:.2f}s n={a['n']}) "
          f"screen=({a['cx']},{a['cy']}) maxpres={a['maxpres']} sts={a['sts']} tool={a['tool']} {a['region']}")

print(f"\n=== GHOST lifecycles (max pres < 128): {len(ghosts)} ===")
from collections import Counter
reg = Counter(g["region"] for g in ghosts)
print("  by region:", dict(reg))
for g in sorted(ghosts, key=lambda x: x["t0"])[:15]:
    print(f"  f{g['fid']} t={g['t0']:.1f}-{g['t1']:.1f} ({g['dur']:.2f}s n={g['n']}) "
          f"screen=({g['cx']},{g['cy']}) maxpres={g['maxpres']} sts={g['sts']} tool={g['tool']} {g['region']}")
if len(ghosts) > 15:
    print(f"  ... and {len(ghosts)-15} more")

# active by region
ar = Counter(a["region"] for a in acts)
print(f"\nACTIVE by region: {dict(ar)}")
print(f"active lifecycle count: {len(acts)} (expect ~15 if all taps delivered)")
