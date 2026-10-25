import io, struct, sys, zipfile, urllib.request

URL = "https://updates.cdn-apple.com/2025FallFCS/fullrestores/122-76738/B6C604B4-548E-401F-BBFF-916E3FFDF235/iPhone_5.5_P3_16.7.16_20H392_Restore.ipsw"

class HTTPRange(io.RawIOBase):
    def __init__(self, url):
        self.url = url
        self.pos = 0
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as r:
            self.size = int(r.headers["Content-Length"])
    def seek(self, off, whence=0):
        if whence == 0: self.pos = off
        elif whence == 1: self.pos += off
        elif whence == 2: self.pos = self.size + off
        return self.pos
    def tell(self): return self.pos
    def readable(self): return True
    def seekable(self): return True
    def read(self, n=-1):
        if n is None or n < 0: n = self.size - self.pos
        if n <= 0: return b""
        end = min(self.pos + n, self.size) - 1
        req = urllib.request.Request(self.url, headers={"Range": "bytes=%d-%d" % (self.pos, end)})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        self.pos += len(data)
        return data
    def readinto(self, b):
        d = self.read(len(b)); b[:len(d)] = d; return len(d)

print("opening remote ipsw (size from HEAD)...", flush=True)
raw = HTTPRange(URL)
print("size = %.2f GB" % (raw.size / 2**30), flush=True)
zf = zipfile.ZipFile(io.BufferedReader(raw, buffer_size=1 << 20))
names = [n for n in zf.namelist() if "DeviceTree" in n and n.endswith(".im4p")]
print("DeviceTree entries:", names, flush=True)
if not names:
    sys.exit("no DeviceTree im4p found")
name = names[0]
for cand in names:
    if "d21" in cand.lower():
        name = cand
print("extracting:", name, flush=True)
data = zf.read(name)
open("/tmp/opencode/dtree.im4p", "wb").write(data)
print("wrote dtree.im4p %d bytes" % len(data), flush=True)

# IM4P: "IM4P" u32 hlen, header, payload
assert data[:4] == b"IM4P", data[:8]
hlen = struct.unpack(">I", data[4:8])[0]
header = data[8:8 + hlen]
payload = data[8 + hlen:]
print("header:", header[:160], flush=True)
open("/tmp/opencode/dt.bin", "wb").write(payload)
print("payload (raw ADT candidate) %d bytes, first bytes %r" % (len(payload), payload[:8]), flush=True)
