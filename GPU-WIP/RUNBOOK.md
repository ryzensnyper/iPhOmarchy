# A11 (G10P) GPU — test runbook

How the null-compute tests on the iPhone 8 Plus (D21, T8015) are set up and
run. The first null compute job completed on 2026-11-29 with this procedure.
For the current state and next steps, see [STATUS.md](STATUS.md).

## 1. What you need

| item | where it comes from | in git? |
|---|---|---|
| Kernel tree with the G10P driver | branch `gpu/t8015-g10p` of a local OrchardLinux/linux worktree (driver: `drivers/gpu/drm/imagination/pvr_apple_t8015.c`, `pvr_apple_g10p_layout.c`) | not pushed yet |
| Orchard build tool | a plain checkout of OrchardLinux/orchard `main` | — |
| GFX firmware `apple/gfx-t8015.bin` | extracted from the iOS 16.7.x `iPhone10,2` kernelcache (`AGXFirmwareKextG10PRTBuddy` image, sha256 `bd7b98e2…`), see `tools/kc_fwscan.py` | **never**: it goes onto the phone in RAM only |
| Phone-side scripts | [`device/`](device/) | yes |
| SSH to the phone | the Orchard RAM-boot key, USB network `172.16.42.1` | key is private |

## 2. Build

```sh
cd <orchard checkout>
./bin/orchard build <omarchy-iphone>/d21-desktop-main --device d21 \
  --kernel <linux worktree on gpu/t8015-g10p> --pongo <Pongo.bin>
```

The module lands at
`<linux worktree>/.orchard-out/apple-16k/output/drivers/gpu/drm/imagination/powervr.ko`.
Check `modinfo -F vermagic powervr.ko` = `7.3.0-rc1-orchard-apple-16k`, the
same as the booted kernel. You only need a new boot when the kernel itself
changes. Driver-only changes are tested by reloading the module.

## 3. Boot (only when the kernel changes)

1. Put the phone in PongoOS (USB `05ac:4141`).
2. `./bin/orchard run <omarchy-iphone>/d21-desktop-main --device d21 --no-build -y`
3. Wait until systemd is up (the first SSH answer can come from the busybox
   initramfs), then copy over the scripts and the firmware (RAM only). The phone has no
   scp/sftp, so pipe files over ssh:

```sh
O=(-i <key> -o IdentitiesOnly=yes -o ConnectTimeout=5 \
   -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
P=root@172.16.42.1
ssh $O $P 'mkdir -p /run/t /run/gfxfw/apple'
for f in device/*; do ssh $O $P "cat > /run/t/${f##*/}" < $f; done
ssh $O $P 'cat > /run/gfxfw/apple/gfx-t8015.bin' < gfx-t8015.bin
```

## 4. One test run (always this sequence)

Always bound every command with `timeout`. If the phone doesn't answer, it is
usually asleep: wake it, then retry.

```sh
# 0. stop the phone from sleeping during the test
ssh $O $P '/bin/systemctl mask --runtime sleep.target suspend.target'
# 1. temperature before (battery, 0.1 °C)
ssh $O $P 'sh /run/t/gpu-temp.sh'
# 2. push the module and check its hash
ssh $O $P 'cat > /run/powervr.ko' < powervr.ko
ssh $O $P 'sha256sum /run/powervr.ko'
# 3. arm the SoC watchdog: a hang resets the phone within 30 s
ssh $O $P 'rm -f /run/wdt.stop; setsid nohup python3 /run/t/wdt.py arm 30 \
           > /run/t/wdt.log 2>&1 < /dev/null & sleep 3; cat /run/t/wdt.log'
# 4. load at the lowest perf state, run ONE null job, dump the heap
ssh $O $P 'sh /run/t/gpu-load-ko.sh; sh /run/t/gpu-null-compute.sh; \
           python3 /run/t/gpu-heapstate.py'
# 5. unload (powers the GPU off), disarm the watchdog, temperature after
ssh $O $P 'timeout 30 rmmod powervr; touch /run/wdt.stop; sleep 7; \
           tail -1 /run/t/wdt.log; sh /run/t/gpu-temp.sh'
# 6. let the phone sleep again
ssh $O $P '/bin/systemctl unmask --runtime sleep.target suspend.target'
```

### Reading the result

| output | meaning |
|---|---|
| `null compute job 1: 0, stamp 1, fault 0` and `done 1` | **pass**: the firmware ran the job and wrote its stamp |
| `-110, stamp 0` | timeout: the job was never run, or never finished |
| `RTKit: co-processor has crashed` + crashlog | firmware panic. The PC is in `r15` of the exception dump; look it up in the firmware disassembly |
| `stamp` line of `gpu-heapstate.py` | `+0 = 1` means the end of the microsequence ran |
| `pool +0` | scheduling-pool entry state: 1 = queued, 3 = finished |

## 5. Safety rules (after a red-screen scare on 2026-11-29)

- Load powervr with `apple_perf_state=1`, the lowest power state.
- Arm the watchdog before every load.
- Check the battery temperature before and after (about 29–30 °C so far).
- Run one job per test, then `rmmod`.
- Stop at the first oddity and don't retry blind.
- Never fake GPU power state or firmware fields from the host.
- If a hung test leaves a red screen, reboot. It took two reboots to get back
  to normal iOS.
- Firmware, kernelcache bytes, `.ko` files and device-specific data never go
  into git.
