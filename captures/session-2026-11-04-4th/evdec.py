#!/usr/bin/env python3
"""Decode evdev raw captures (24-B records, LE) into BTN_TOUCH/slot summary."""
import struct, sys

EVENTS = {0x01: "KEY", 0x03: "ABS", 0x00: "SYN"}
KEYS = {330: "BTN_TOUCH", 325: "BTN_TOOL_FINGER"}
ABSS = {47: "ABS_MT_SLOT", 57: "ABS_MT_TRACKING_ID", 53: "ABS_MT_POSITION_X",
        54: "ABS_MT_POSITION_Y", 330: None}

def decode(path, label):
    data = open(path, "rb").read()
    n = len(data) // 24
    downs = ups = 0
    slots = {}
    events = []
    for i in range(n):
        sec, usec, etype, code, val = struct.unpack_from("<QQHHi", data, i * 24)
        events.append((sec + usec / 1e6, etype, code, val))
        if etype == 1 and code == 330:
            if val == 1: downs += 1
            elif val == 0: ups += 1
        if etype == 3 and code == 47:
            slots[val] = slots.get(val, 0) + 1
    print(f"== {label}: {n} events, BTN_TOUCH downs={downs} ups={ups}")
    # print BTN_TOUCH event sequence with timestamps relative to first
    if events:
        t0 = events[0][0]
        for t, etype, code, val in events:
            if etype == 1 and code == 330:
                print(f"   t={t-t0:7.2f} BTN_TOUCH {'DOWN' if val else 'UP  '}")
    return downs, ups

d1, u1 = decode(sys.argv[1], "event1 (driver raw out)")
d2, u2 = decode(sys.argv[2], "event2 (touchfix -> desktop)")
print(f"\nPIPELINE: attempted 15 taps -> driver downs {d1} -> desktop downs {d2}")
