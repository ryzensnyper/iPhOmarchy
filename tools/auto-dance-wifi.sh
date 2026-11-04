#!/bin/bash
# Auto-dance continuation: wait for pongo (user drives the phone), push payload,
# reconnect + bare bootm, wait for Linux. Progress markers throughout.
cat ~/checkm8-kit/linux-kit/m1n1-linux-p3-omarchy-wifi.bin.manifest 2>/dev/null | head -8
for i in $(seq 1 240); do
  if lsusb | grep -q '05ac:4141'; then echo "PONGO-DETECTED $(date +%T)"; break; fi
  sleep 3
done
lsusb | grep -q '05ac:4141' || { echo "NO-PONGO-TIMEOUT"; exit 1; }
sleep 4
cd ~/checkm8-kit
printf '/send linux-kit/m1n1-linux-p3-omarchy-wifi.bin\nbootm\n' | ./linux-kit/pongoterm > /tmp/opencode/pongo-send.log 2>&1
echo "SEND-DONE $(date +%T): $(tail -2 /tmp/opencode/pongo-send.log | tr '\n' ' ' | cut -c1-120)"
# wait for pongo to re-enumerate (reconnect), then bare bootm
REBACK=0
for i in $(seq 1 60); do
  if lsusb | grep -q '05ac:4141'; then echo "PONGO-BACK $(date +%T)"; REBACK=1; break; fi
  if lsusb | grep -q '05ac:4142'; then echo "LINUX-ALREADY-UP $(date +%T)"; exit 0; fi
  sleep 2
done
if [ "$REBACK" = 1 ]; then
  printf 'bootm\n' | timeout 20 ./linux-kit/pongoterm > /tmp/opencode/pongo-bootm.log 2>&1
  echo "BOOTM-SENT $(date +%T)"
fi
for i in $(seq 1 90); do
  if lsusb | grep -q '05ac:4142'; then echo "LINUX-UP $(date +%T)"; exit 0; fi
  sleep 3
done
echo "LINUX-TIMEOUT $(date +%T)"
