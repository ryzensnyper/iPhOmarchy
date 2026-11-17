#!/usr/bin/env python3
"""d21-touch-decode.py RAW_EVDEV_CAPTURE

Decode a raw evdev capture (concatenated `struct input_event`, 24 bytes each)
from the D21 touchscreen into clean tap events. Collects ABS_MT slots per SYN,
reports DOWN/MOVE/UP with coordinates and pressure, and prints a tap summary.

Usage:
  # on device:  cat /dev/input/event1 > /tmp/touchcap &
  # ... tap ...
  # host:       d21-touch-decode.py touchcap.bin
"""
import struct, sys
from collections import Counter

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
ABS_MT_SLOT = 47
ABS_MT_TRACKING_ID = 57
ABS_MT_POSITION_X = 53
ABS_MT_POSITION_Y = 54
ABS_MT_PRESSURE = 58
ABS_MT_TOUCH_MAJOR = 52
ABS_MT_WIDTH_MAJOR = 0x33
BTN_TOUCH = 0x14a

AXIS = {ABS_MT_POSITION_X:'x', ABS_MT_POSITION_Y:'y', ABS_MT_PRESSURE:'p',
        ABS_MT_TOUCH_MAJOR:'maj', ABS_MT_WIDTH_MAJOR:'wmaj'}

def frames_from(path):
    d = open(path,'rb').read()
    n = len(d)//24
    frames, cur = [], []
    for i in range(n):
        _, _, typ, code, val = struct.unpack_from('<qQhHi', d, i*24)
        if typ == EV_SYN and code == 0:
            frames.append(cur); cur = []
        else:
            cur.append((typ, code, val))
    if cur: frames.append(cur)
    return frames

def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    frames = frames_from(sys.argv[1])
    slots, slot = {}, 0
    events = []
    for fi, fr in enumerate(frames):
        prev = {s:v.get('tid') for s,v in slots.items()}
        for typ, code, val in fr:
            if typ != EV_ABS: continue
            if code == ABS_MT_SLOT: slot = val
            elif code == ABS_MT_TRACKING_ID:
                if val < 0: slots.pop(slot, None)
                else: slots[slot] = {'tid':val}
            elif slot in slots:
                k = AXIS.get(code)
                if k: slots[slot][k] = val
        for s, v in slots.items():
            if prev.get(s) != v.get('tid') and 'tid' in v:
                events.append(('DOWN', fi, s, dict(v)))
        # ups
        gone = [s for s,t in prev.items() if t is not None and s not in slots]
        for s in gone:
            events.append(('UP', fi, s, {}))

    print(f"frames={len(frames)}  events={len(events)}  "
          f"DOWN={sum(1 for e in events if e[0]=='DOWN')}  UP={sum(1 for e in events if e[0]=='UP')}")
    print(f"{'type':5} {'frame':>6} {'slot':>4} {'tid':>4} {'x':>6} {'y':>6} {'pres':>6} {'maj':>8}")
    for typ, fi, s, v in events:
        print(f"{typ:5} {fi:6d} {s:4d} {str(v.get('tid','')):>4} "
              f"{str(v.get('x','')):>6} {str(v.get('y','')):>6} "
              f"{str(v.get('p','')):>6} {str(v.get('maj','')):>8}")
    downs = [(fi,s,v) for t,fi,s,v in events if t=='DOWN']
    if downs:
        xs = [v.get('x') for _,_,v in downs if v.get('x') is not None]
        ys = [v.get('y') for _,_,v in downs if v.get('y') is not None]
        if xs and ys:
            print(f"\nx range {min(xs)}..{max(xs)}  y range {min(ys)}..{max(ys)}  "
                  f"(panel 1080x1920, centre ~540,960)")

if __name__ == '__main__':
    main()
