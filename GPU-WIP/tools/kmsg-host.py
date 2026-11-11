#!/usr/bin/env python3
"""Collect the phone's kernel log over the USB network.

The payload's init streams /proc/kmsg to this socket (busybox nc, TCP), so
the log survives a reset that takes the phone's display with it.  Every
connection is appended to the log file; a reconnect after a reset starts a
new file section.
"""
import socket
import sys
import time

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 6666
OUT = sys.argv[2] if len(sys.argv) > 2 else '/tmp/opencode/phone-kmsg.log'

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(('0.0.0.0', PORT))
server.listen(4)
print(f'listening on tcp/{PORT}, writing to {OUT}', flush=True)

with open(OUT, 'ab', buffering=0) as out:
    while True:
        try:
            conn, addr = server.accept()
        except OSError as exc:
            print(f'accept failed: {exc}', flush=True)
            time.sleep(1)
            continue
        print(f'connection from {addr}', flush=True)
        out.write(f'\n===== log from {addr} at {time.strftime("%H:%M:%S")} =====\n'.encode())
        conn.settimeout(1.0)
        last = time.time()
        try:
            while True:
                try:
                    data = conn.recv(65536)
                except socket.timeout:
                    if time.time() - last > 60:
                        break
                    continue
                if not data:
                    break
                last = time.time()
                out.write(data)
        finally:
            conn.close()
            print('connection closed', flush=True)
