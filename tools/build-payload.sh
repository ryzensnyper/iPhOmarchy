#!/bin/bash
# build-payload.sh — assemble the m1n1 boot payload with VERIFICATION GATES.
#
#   build-payload.sh -k <kernel-tree> -d <dtb> -o <output> [-b <bootargs>]
#                     [-m <module> ...]
#
# Gates (any failure ABORTS with a nonzero exit — nothing is written):
#   1. kernel tree + Image.gz must exist and be FRESH (mtime >= vmlinux.o,
#      and Image.gz newer than the tree's Module.symvers — catches a stale
#      artifact copy).
#   2. The kernel version string EMBEDDED IN THE IMAGE BYTES must match the
#      utsrelease the tree would stamp (include/generated/utsrelease.h).
#   3. Every -m module's vermagic git-hash segment must MATCH the kernel's.
#      This is the check that would have caught the 2026-11-04 stale-payload
#      mistake: old kernel g2bde906a7ae3 vs new modules g3b07f3a1e.
#   4. The DTB must decompile cleanly (dtc -I dtb -O dts).
#   5. The assembled layout is re-verified (m1n1 | bootargs | dtb | gzip).
#
# On success: writes <output> + <output>.manifest with component sizes/shas.
set -euo pipefail

KERNEL_TREE="" DTB="" OUT="" BOOTARGS="root=/dev/nvme0n1p3 rootwait rw console=tty0"
MODULES=()
while getopts "k:d:o:b:m:" opt; do case $opt in
    k) KERNEL_TREE=$OPTARG ;; d) DTB=$OPTARG ;; o) OUT=$OPTARG ;;
    b) BOOTARGS=$OPTARG ;; m) MODULES+=("$OPTARG") ;;
    *) echo "usage: $0 -k <tree> -d <dtb> -o <out> [-b bootargs] [-m ko]..." >&2; exit 2 ;;
esac; done
[ -n "$KERNEL_TREE" ] && [ -n "$DTB" ] && [ -n "$OUT" ] || { echo "missing -k/-d/-o" >&2; exit 2; }

KERNEL_TREE=$(readlink -f "$KERNEL_TREE"); DTB=$(readlink -f "$DTB")
OUT=$(readlink -f "$OUT"); M1N1=$(dirname "$(readlink -f "$0")")/m1n1-build/m1n1.bin

fail() { echo "REFUSED: $*" >&2; exit 1; }
[ -f "$M1N1" ] || fail "m1n1.bin not found at $M1N1"
[ -f "$KERNEL_TREE/arch/arm64/boot/Image.gz" ] || fail "no Image.gz in $KERNEL_TREE"

# --- gate 1: freshness -------------------------------------------------------
IMAGE=$KERNEL_TREE/arch/arm64/boot/Image.gz
[ "$IMAGE" -nt "$KERNEL_TREE/vmlinux.o" ] || fail "Image.gz older than vmlinux.o (stale build? run: make -C $KERNEL_TREE LLVM=1 ARCH=arm64 Image.gz)"
[ "$IMAGE" -nt "$KERNEL_TREE/Module.symvers" ] || fail "Image.gz older than Module.symvers (stale?)"

# --- gate 2: embedded version vs the tree's utsrelease -----------------------
UTS=$(sed -n 's/#define UTS_RELEASE "//p' "$KERNEL_TREE/include/generated/utsrelease.h" 2>/dev/null | tr -d '"' || true)
[ -n "$UTS" ] || fail "no utsrelease.h — tree not built?"
EMBEDDED=$(gzip -dc "$IMAGE" | strings | grep -oE '[0-9]+\.[0-9]+\.[0-9]+[^ ]*g[0-9a-f]{7,12}' | head -1 || true)
[ "$EMBEDDED" = "$UTS" ] || fail "Image embeds '$EMBEDDED' but tree stamps '$UTS'"

# --- gate 3: every module's vermagic matches the kernel ----------------------
KHASH=$(echo "$UTS" | grep -oE 'g[0-9a-f]{7,12}$' || true)
[ -n "$KHASH" ] || fail "cannot parse the git-hash from '$UTS'"
for m in "${MODULES[@]:-}"; do
    [ -n "$m" ] || continue
    [ -f "$m" ] || fail "module $m missing"
    V=$(modinfo -F vermagic "$m")
    echo "$V" | grep -q "$KHASH " || echo "$V" | grep -q "${KHASH}\$"[^ ]* || \
        fail "module $(basename "$m") vermagic '$V' does not carry kernel hash $KHASH"
    echo "  ok $(basename "$m"): $V"
done

# --- gate 4: the DTB parses --------------------------------------------------
dtc -I dtb -O dts -o /dev/null "$DTB" 2>/dev/null || fail "DTB $DTB does not parse"

# --- assemble ----------------------------------------------------------------
LINE=$(printf 'chosen.bootargs=%s\n' "$BOOTARGS")
{ cat "$M1N1"; printf '%s\n' "$LINE"; cat "$DTB"; cat "$IMAGE"; } > "$OUT.tmp"

# --- gate 5: layout re-verification ------------------------------------------
python3 - "$OUT.tmp" "$M1N1" "$DTB" "$IMAGE" "$BOOTARGS" <<'PY'
import struct, sys
out, m1n1, dtb, kern, args = sys.argv[1:6]
b = open(out,'rb').read(); m = open(m1n1,'rb').read(); d = open(dtb,'rb').read(); k = open(kern,'rb').read()
off = 0
expected = ('chosen.bootargs=%s\n' % args).encode()
assert b[:len(m)] == m, "m1n1 prefix"; off += len(m)
assert b[off:off+len(expected)] == expected, "bootargs"; off += len(expected)
assert b[off:off+4] == b'\xd0\x0d\xfe\xed', "dtb magic"; off += len(d)
assert b[off:off+2] == b'\x1f\x8b', "kernel gzip"; off += len(k)
assert off == len(b), "trailing bytes"
print("layout ok: m1n1 %d + args %d + dtb %d + kernel %d" % (len(m), len(expected), len(d), len(k)))
PY

mv "$OUT.tmp" "$OUT"
{
    echo "payload: $OUT"
    echo "kernel:  $IMAGE  ($UTS)"
    echo "dtb:     $DTB"
    echo "bootargs: $BOOTARGS"
    echo "sha256:"
    sha256sum "$M1N1" "$DTB" "$IMAGE" "$OUT" | sed 's/^/  /'
    for m in "${MODULES[@]:-}"; do [ -n "$m" ] && sha256sum "$m" | sed 's/^/  /'; done
} > "$OUT.manifest"
cat "$OUT.manifest"
echo "==> wrote $OUT (+ .manifest)"
