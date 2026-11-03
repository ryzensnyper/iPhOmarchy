# d21-boot DTB — the IRQ-type fix (2026-11-03)

The deployed boot DTB lives at ~/checkm8-kit/linux-kit/step6/d21-boot.dtb and is
embedded into the pongo payload by step6/make-blob.sh (m1n1.bin | bootargs line |
d21-boot.dtb | Image.gz, self-verifying).

## The bug this fixes
The D21 touchscreen node declared `interrupts-extended = <0x18 0x66 0x02>`
(pinctrl@233100000, hwirq 102, RISING EDGE), but the runtime line is LEVEL-LOW,
so apple_z2 flipped the type at every boot ("D21 touch IRQ -> level-low (was 2)")
and restored it at unload. Any failed/raced boot left the flip applied in the
GPIO irq domain, and from then on EVERY probe failed:

    irq: type mismatch, failed to map hwirq-102 for pinctrl@233100000!
    error -EINVAL: request_irq(0) 0x0 apple_z2_irq ...
    probe with driver apple-z2 failed with error -22

with insmod returning 0 (PROBE_PREFER_ASYNCHRONOUS), so the unit looks "active"
while the driver is UNBOUND: no touch, no recovery, no logs. This is also the
root cause of the "d21-touch auto-start is flaky" symptom. The stale mapping is
kernel-side and clears only on a full reboot.

## The fix
    fdtput -t x step6/d21-boot.dtb /soc/spi@22e404000/touchscreen@0 \
        interrupts-extended 0x18 0x66 0x8     # 2 (edge-rising) -> 8 (LEVEL_LOW)
    BOOTARGS="root=/dev/nvme0n1p3 rootwait rw console=tty0" \
        bash step6/make-blob.sh m1n1-linux-p3-omarchy.bin

⚠️ **CORRECTION (2026-11-04, dance #12): the 2026-11-03 fix wrote 0x4 — which is
LEVEL_HIGH, not level-low (the Linux irqflag encoding: 1=edge-rising, 2=edge-
falling, 4=level-high, 8=level-low). The dance #9 "verification" mis-decoded
the flag. With 0x4 the runtime flip was never a no-op: every boot logged
"touch IRQ -> level-low (was 4)" and every stop restored level-high, so the
mismatch trap stayed armed — proven live on 2026-11-04 when a reload failed
-22 exactly as before (the restore had been skipped by a failed-boot path).
With 0x8 the fwspec type matches the hardware line and the flip is a real
no-op: no divergence, no mismatch, ever.**

With the DT saying level-low, the runtime flip is a no-op and the domain type
never diverges from the fwspec type: no mismatch, ever. Driver-side hardening
(also in 9b718314): err_stop restores the type, the flip is skipped when
stopping, TimeoutStopSec=180 keeps systemd from SIGKILLing rmmod mid-delete.

Artifacts here: d21-boot-irqlevel.dtb (deployed), d21-boot-pre-irqfix.dtb.bak.
Payload: m1n1-linux-p3-omarchy.bin (9724143 B, same size as before the fix).
