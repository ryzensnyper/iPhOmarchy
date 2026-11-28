#!/usr/bin/env python3
# DEBUG (phone side): arm the hardware watchdog for a test window.
#   wdt.py arm SECS    feed /dev/watchdog every 5 s with a SECS timeout until /run/wdt.stop exists,
#                      then disarm cleanly (magic close). If the kernel freezes, the SoC resets.
import fcntl, os, struct, sys, time
WDIOC_SETTIMEOUT = 0xc0045706
WDIOC_GETTIMEOUT = 0x80045707
secs = int(sys.argv[2]) if len(sys.argv) > 2 else 30
try:
    os.unlink("/run/wdt.stop")
except FileNotFoundError:
    pass
fd = os.open("/dev/watchdog", os.O_WRONLY)
try:
    fcntl.ioctl(fd, WDIOC_SETTIMEOUT, struct.pack("<i", secs))
except OSError as e:
    print("settimeout:", e)
t = struct.unpack("<i", fcntl.ioctl(fd, WDIOC_GETTIMEOUT, struct.pack("<i", 0)))[0]
print("watchdog armed, timeout %d s" % t, flush=True)
while not os.path.exists("/run/wdt.stop"):
    os.write(fd, b"k")
    time.sleep(5)
os.write(fd, b"V")      # magic close: disarm
os.close(fd)
print("watchdog disarmed", flush=True)
