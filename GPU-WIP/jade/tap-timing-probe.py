#!/usr/bin/env python3
"""tap-timing-probe.py SECONDS OUTFILE

Log raw(ev1) and fixed(ev2) evdev DOWN/UP with ms timestamps + raw frame cadence.
Use to compare a QUICK tap vs a HELD tap and find why short taps are missed.
"""
import os, select, struct, sys, time
EV_SYN, EV_ABS = 0, 3
SLOT, TID, X, Y = 0x2f, 0x39, 0x35, 0x36

def open_ev(p): return os.open(p, os.O_RDONLY | os.O_NONBLOCK)

fds = {'raw': open_ev('/dev/input/event1'), 'fix': open_ev('/dev/input/event2')}
state = {k: {} for k in fds}; slot = {k: 0 for k in fds}
log = []; t0 = time.monotonic()
dur = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
outp = sys.argv[2] if len(sys.argv) > 2 else '/tmp/tap-timing.txt'
raw_frames = 0

while time.monotonic() - t0 < dur:
    r, _, _ = select.select(list(fds.values()), [], [], 0.02)
    for fd in r:
        name = [k for k, v in fds.items() if v == fd][0]
        try: b = os.read(fd, 24 * 512)
        except BlockingIOError: continue
        for i in range(0, len(b) - 23, 24):
            _, _, typ, code, val = struct.unpack_from('<qQhHi', b, i)
            if typ == EV_SYN and code == 0:
                if name == 'raw': raw_frames += 1
                continue
            if typ != EV_ABS: continue
            if code == SLOT: slot[name] = val
            elif code == TID:
                t = time.monotonic() - t0
                s = slot[name]
                if val < 0:
                    if s in state[name]:
                        v = state[name].pop(s)
                        log.append((t, name, 'UP', s, v))
                else:
                    old = state[name].get(s)
                    if old is None or old != val:
                        state[name][s] = val
                        log.append((t, name, 'DOWN', s, val))

with open(outp, 'w') as f:
    f.write(f"# dur={dur}s raw_frames={raw_frames} raw_fps={raw_frames/dur:.2f}\n")
    for t, name, ev, s, tid in log:
        f.write(f"{t:8.3f} {name:4} {ev:4} slot={s} tid={tid}\n")
print(f"raw_frames={raw_frames} over {dur}s = {raw_frames/dur:.2f} fps; events={len(log)} -> {outp}")
