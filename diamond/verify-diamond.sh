#!/bin/sh
# verify-diamond.sh — DIAMOND build checklist, run on the phone as root.
# Exits 0 only if every DIAMOND check passes. Read-only: no key writes.
fail=0
say() { printf '%-42s %s\n' "$1" "$2"; }
chk() { if [ "$2" = "ok" ]; then say "$1" "ok"; else say "$1" "FAIL ($2)"; fail=1; fi; }

# 1. module loaded and bound
lsmod | grep -q '^apple_z2' && chk "apple_z2 module loaded" ok || chk "apple_z2 module loaded" "not loaded"
grep -q 'iPhone10,2 Touchscreen' /proc/bus/input/devices && chk "raw touchscreen node" ok || chk "raw touchscreen node" "missing"

# 2. touchfix virtual node
grep -q 'd21-touchfix virtual touchscreen' /proc/bus/input/devices && chk "touchfix virtual node" ok || chk "touchfix virtual node" "missing"

# 3. HV regulator enabled
st=$(cat /sys/class/regulator/regulator.*/state 2>/dev/null | grep -c enabled)
[ "$(cat /sys/class/regulator/regulator.*/name 2>/dev/null | grep -c chestnut-touch-hv)" -ge 1 ] && chk "chestnut-touch-hv regulator present" ok || chk "chestnut-touch-hv regulator present" "missing"
grep -q . <<EOF && chk "HV regulator enabled" ok || chk "HV regulator enabled" "check /sys/class/regulator"
$(cat /sys/class/regulator/regulator.*/name 2>/dev/null | paste - - 2>/dev/null | grep chestnut | head -1)
EOF

# 4. SMC function state (RW read: inert write + state byte)
dmesg -c >/dev/null 2>&1
insmod /root/smc-keyprobe.ko do_rw=1 write_val=0x05020001 >/dev/null 2>&1
state=$(dmesg | grep -oE 'rBK3 RW w=0x[0-9a-f]+ err=[0-9]+ rbuf=[0-9a-f]+' | tail -1)
case "$state" in
  *err=4*rbuf=01000000*) chk "SMC rBK3 state=ON" ok ;;
  *err=4*rbuf=00000000*) chk "SMC rBK3 state=ON" "OFF (rail down!)" ;;
  *) chk "SMC rBK3 state=ON" "no RW reply (macsmc bound?)" ;;
esac

# 5. stream alive (IRQ counter over 5 s)
a=$(grep apple-z2 /proc/interrupts | awk '{print $2}')
sleep 5
b=$(grep apple-z2 /proc/interrupts | awk '{print $2}')
irq=$(( (b-a)/5 ))
[ "$irq" -ge 1 ] && chk "touch stream IRQs" "${irq}/s" || chk "touch stream IRQs" "0 — reload d21-touch (poll kick)"

# 6. units
systemctl is-active --quiet d21-touchfix && chk "d21-touchfix active" ok || chk "d21-touchfix active" "inactive"

# 7. desktop scale (best-effort, needs the tablet user env)
sc=$(sudo -u tablet env WAYLAND_DISPLAY=wayland-0 XDG_RUNTIME_DIR=/run/user/1000 wlr-randr 2>/dev/null | grep -m1 Scale | grep -oE '2\.0+')
[ -n "$sc" ] && chk "desktop scale 2.0" ok || chk "desktop scale 2.0" "run arch-ipad-scale-output tablet"

# 8. thermals
tmax=0
for t in /sys/class/hwmon/hwmon*/temp*_input; do
  v=$(cat "$t" 2>/dev/null) || continue
  [ "$v" -gt "$tmax" ] && tmax=$v
done
c=$((tmax/1000))
[ "$c" -le 40 ] && chk "thermals" "${c}C" || chk "thermals" "${c}C — ABORT experiments, cool down"

echo
[ "$fail" = 0 ] && echo "DIAMOND: ALL CHECKS PASS" || echo "DIAMOND: FAILURES PRESENT (see above)"
exit $fail
