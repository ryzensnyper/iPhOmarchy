#!/bin/sh
# Phase 2.2 verification -- READ-ONLY.  Run this from the host after the
# Phase-2.2 kernel is booted.  Reads sysfs/debugfs/dmesg only; never writes a
# register and never touches the GPU windows.
#
#   sh verify.sh
#
# Exit status is 0 only if every hard check passes.

set -u
KEY="${KEY:-$HOME/.ssh/id_hoolock}"
HOST="${HOST:-root@172.16.42.1}"
SSH="ssh -i $KEY -o ConnectTimeout=8 -o BatchMode=yes $HOST"
fails=0

say() { printf '\n== %s\n' "$1"; }
ok()  { printf '  PASS  %s\n' "$1"; }
bad() { printf '  FAIL  %s\n' "$1"; fails=$((fails + 1)); }
warn() { printf '  WARN  %s\n' "$1"; }

say "identity"
timeout -k 5 20 $SSH 'cat /proc/uptime; uname -a' \
    || { echo "SSH failed"; exit 2; }

say "RTKit HELLO (the Phase 2.2 success criterion)"
M=$(timeout -k 5 20 $SSH 'dmesg | grep "RTKit: Initializing"' || true)
if [ -n "$M" ]; then ok "$M"; else bad "no RTKit HELLO line"; fi

say "driver boot markers"
I=$(timeout -k 5 20 $SSH 'dmesg | grep "GFX IOP released"' || true)
F=$(timeout -k 5 20 $SSH 'dmesg | grep "GFX firmware is up"' || true)
[ -n "$I" ] && ok "$I" || bad "IOP was never released"
[ -n "$F" ] && ok "$F" || bad "no 'firmware is up' marker"

say "firmware crash"
C=$(timeout -k 5 20 $SSH 'dmesg | grep -i "GFX firmware crashed"' || true)
if [ -z "$C" ]; then ok "no crash reported"; else bad "$C"; fi

say "RTKit protocol oddities"
U=$(timeout -k 5 20 $SSH 'dmesg | grep -i "unknown management message"' || true)
if [ -z "$U" ]; then ok "no unknown management messages"; else warn "$U"; fi

say "gfx power domain"
ST=$(timeout -k 5 20 $SSH 'cat /sys/kernel/debug/pm_genpd/gfx/current_state' || true)
case "$ST" in on*) ok "current_state = $ST" ;; *) bad "current_state = '$ST'" ;; esac
DEV=$(timeout -k 5 20 $SSH 'cat /sys/kernel/debug/pm_genpd/gfx/devices' || true)
printf '%s\n' "$DEV" | grep -q '4000000.gpu' && ok "gpu consumer present" || bad "gpu not in the domain"
printf '%s\n' "$DEV" | grep -q '4d24000.mbox' && ok "mailbox consumer present" || bad "mbox not in the domain"

say "mailbox device"
DRV=$(timeout -k 5 20 $SSH 'readlink -f /sys/bus/platform/devices/4d24000.mbox/driver' || true)
case "$DRV" in *apple-mailbox*) ok "bound to $DRV" ;; *) bad "mbox driver: '$DRV'" ;; esac
IRQ=$(timeout -k 5 20 $SSH 'grep -i "apple-mailbox" /proc/interrupts' || true)
if [ -n "$IRQ" ]; then ok "$IRQ"; else bad "no apple-mailbox IRQ lines"; fi

say "powervr must NOT be loaded"
PV=$(timeout -k 5 20 $SSH 'grep -i powervr /proc/modules' || true)
if [ -z "$PV" ]; then ok "powervr not loaded"; else bad "powervr loaded: $PV"; fi

say "display (simplefb, unchanged)"
FB=$(timeout -k 5 20 $SSH 'cat /sys/class/graphics/fb0/virtual_size; cat /sys/class/graphics/fb0/bits_per_pixel; cat /sys/class/graphics/fb0/name' || true)
if printf '%s' "$FB" | grep -q '1080,1920'; then ok "fb0 1080x1920"; else bad "fb0: $FB"; fi

say "touch (apple-z2 IRQ)"
T=$(timeout -k 5 20 $SSH 'grep -i z2 /proc/interrupts' || true)
if [ -n "$T" ]; then ok "$T"; else bad "apple-z2 IRQ missing"; fi

say "storage"
NV=$(timeout -k 5 20 $SSH 'ls /dev/nvme0n1p3 && grep " / " /proc/mounts' || true)
if [ -n "$NV" ]; then ok "NVMe root present"; else bad "NVMe root missing"; fi

say "kernel health"
K=$(timeout -k 5 20 $SSH 'dmesg | grep -iE "Unable to handle kernel|Internal error|Oops|Kernel panic"' || true)
if [ -z "$K" ]; then ok "no oops/panic"; else bad "$K"; fi

printf '\n== result: '
if [ "$fails" -eq 0 ]; then echo "ALL PASS"; else echo "$fails FAILURE(S)"; fi
exit "$fails"
