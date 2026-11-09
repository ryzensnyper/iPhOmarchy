#!/bin/sh
# Phase 2.1 verification -- READ-ONLY.  Run this from the host after the
# Phase-2.1 kernel is booted.  It reads sysfs/debugfs/dmesg only; it never
# writes a register and never touches the GPU windows.
#
#   sh verify.sh
#
# Every SSH call is bounded.  Exit status is 0 only if every check passes.

set -u
KEY="${KEY:-$HOME/.ssh/id_hoolock}"
HOST="${HOST:-root@172.16.42.1}"
SSH="ssh -i $KEY -o ConnectTimeout=8 -o BatchMode=yes $HOST"
fails=0

say() { printf '\n== %s\n' "$1"; }
ok()  { printf '  PASS  %s\n' "$1"; }
bad() { printf '  FAIL  %s\n' "$1"; fails=$((fails + 1)); }

say "identity"
timeout -k 5 20 $SSH 'cat /proc/uptime; uname -a; cat /proc/sys/kernel/random/boot_id' \
    || { echo "SSH failed"; exit 2; }

say "phase 2.1 marker in dmesg"
M=$(timeout -k 5 20 $SSH 'dmesg | grep -i "GFX power domain is up"' || true)
if [ -n "$M" ]; then ok "$M"; else bad "driver probe message not found"; fi

say "gfx power domain"
ST=$(timeout -k 5 20 $SSH 'cat /sys/kernel/debug/pm_genpd/gfx/current_state' || true)
case "$ST" in
    on*) ok "current_state = $ST" ;;
    *)   bad "current_state = '$ST' (expected on*)" ;;
esac
DEV=$(timeout -k 5 20 $SSH 'cat /sys/kernel/debug/pm_genpd/gfx/devices' || true)
if [ -n "$DEV" ]; then ok "devices = $DEV"; else bad "no device listed in gfx domain"; fi

say "powervr must NOT be loaded"
PV=$(timeout -k 5 20 $SSH 'cat /proc/modules | grep -i powervr' || true)
if [ -z "$PV" ]; then ok "powervr not loaded"; else bad "powervr loaded: $PV"; fi

say "display (simplefb, unchanged)"
FB=$(timeout -k 5 20 $SSH 'cat /sys/class/graphics/fb0/virtual_size; cat /sys/class/graphics/fb0/bits_per_pixel; cat /sys/class/graphics/fb0/name' || true)
if printf '%s' "$FB" | grep -q '1080,1920'; then ok "fb0 1080x1920"; else bad "fb0: $FB"; fi
printf '%s\n' "$FB" | sed 's/^/        /'

say "touch (apple-z2 IRQ)"
T=$(timeout -k 5 20 $SSH 'grep -i z2 /proc/interrupts' || true)
if [ -n "$T" ]; then ok "$T"; else bad "apple-z2 IRQ line missing"; fi

say "storage"
NV=$(timeout -k 5 20 $SSH 'ls /dev/nvme0n1p3 && cat /proc/mounts | grep " / " ' || true)
if [ -n "$NV" ]; then ok "NVMe root present"; else bad "NVMe root missing"; fi

say "dmesg tail"
timeout -k 5 20 $SSH 'dmesg | tail -20' || true

printf '\n== result: '
if [ "$fails" -eq 0 ]; then echo "ALL PASS"; else echo "$fails FAILURE(S)"; fi
exit "$fails"
