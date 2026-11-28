#!/bin/sh
# DEBUG (phone side): battery temperature and charge, from the SMC power supply.
for p in /sys/class/power_supply/*; do
  [ -r $p/temp ] && echo "$(basename $p): temp $(cat $p/temp) (0.1 C) capacity $(cat $p/capacity 2>/dev/null)%"
done
