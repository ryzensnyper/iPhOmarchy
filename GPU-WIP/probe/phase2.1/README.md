# Phase 2.1 patch kit — GFX power domain behind a real consumer

**Status: draft, NOT applied.  The kernel tree has not been touched.  The
phone has not been touched.**  This kit exists so the whole Phase 2.1 change
can be reviewed before the "go" that would put it in the tree and build it.

Context: `../kb/A11-GPU-G10P-STAGE2.md` (Phase 2.1) and
`../kb/A11-GPU-G10P-BOOTCHAIN.md` (verified facts + the three traps).

## What it changes (5 files in `d21-touchgood`)

| # | file | change |
|---|---|---|
| 1 | `arch/arm64/boot/dts/apple/t8015.dtsi` | add the `gpu@4000000` node — content in `t8015-gpu.dtsi` here |
| 2 | `drivers/soc/apple/Kconfig` | add the `APPLE_T8015_GFX` symbol (below) |
| 3 | `drivers/soc/apple/Makefile` | `obj-$(CONFIG_APPLE_T8015_GFX) += apple-t8015-gfx.o` |
| 4 | `drivers/soc/apple/apple-t8015-gfx.c` | new — `apple-t8015-gfx.c` here |
| 5 | `arch/arm64/configs/orchard_apple16k_defconfig` | `CONFIG_APPLE_T8015_GFX=y` |

Kconfig block (after `APPLE_PMP_T8015_V1`):

```kconfig
config APPLE_T8015_GFX
	tristate "Apple T8015 (A11) G10P GPU power domain"
	depends on ARCH_APPLE || COMPILE_TEST
	depends on PM
	help
	  Enable the GFX power domain of the Apple T8015 (A11) SoC and hold it
	  on.  The G10P GPU's firmware (the GFX IOP) must be alive before any
	  AP-side access to the GPU windows is safe, so the power domain is
	  brought up first, on its own.

	  This driver deliberately performs no hardware access beyond the
	  power-domain request made by the platform core.

	  Say Y here for the D21 GPU bring-up.
```

## What runs on the phone (the only write)

The platform core, in `__platform_driver_probe()`:

1. `dev_pm_domain_attach(dev, PD_FLAG_ATTACH_POWER_ON | PD_FLAG_DETACH_POWER_OFF)`
2. → `genpd_dev_pm_attach()` → `genpd_power_on(pd, 0)`
3. → `apple_pmgr_ps_power_on()`: write `PS_TARGET = 0xf` at PMGR+`0x80338`,
   poll `PS_ACTUAL == 0xf` (100 ms timeout).
4. *then* `apple_t8015_gfx_probe()` runs — it maps nothing, writes nothing.

That is one PMGR power-state write, through the PMGR framework, to the
*power controller* — not to any GPU, Fender or IOP register.  If the domain
does not come up, `genpd_dev_pm_attach()` returns `-EPROBE_DEFER`, the driver
does not probe, and the boot continues.

## Verification after the boot ("go")

```sh
cat /proc/uptime; uname -a
dmesg | grep -i "gfx power domain\|gfx.*pwrstate\|apple-t8015-gfx"
cat /sys/kernel/debug/pm_genpd/gfx/current_state      # expect: on
cat /sys/kernel/debug/pm_genpd/gfx/devices            # expect: our device
cat /sys/class/graphics/fb0/virtual_size              # expect: 1080,1920
grep -i z2 /proc/interrupts                           # expect: counter climbing
cat /proc/modules | grep -i powervr                   # expect: nothing
```

Success = `current_state` reads `on`, our device is listed, and nothing else
changed.  The driver's `dev_info` line is the dmesg marker.

## Rollback

`git checkout -- arch/arm64/boot/dts/apple/t8015.dtsi drivers/soc/apple/...`
or `git reset --hard c2a38a5d` on the tree, then reboot the known-good
payload (`--no-build`, sha256 `f44886c1…`).  Nothing on the phone's storage
holds this kernel.

## Open choices (flagged for the reviewer)

* **Compatible**: the node uses `"apple,t8015-gpu"`, which matches no
  driver.  The in-tree PowerVR entry is `"apple,t8010-gpu"` (its comment
  says t8015) and would load the full AGX driver through coldplug — keep
  them apart until 2.2.
* **No mailbox node** in 2.1: the in-tree mailbox driver writes at probe.
* **Driver home**: `drivers/soc/apple/`, next to `pmp_t8015_v1.c` (the
  template) and the RTKit library.  Phase 2.2 extends this file rather than
  adding a second driver.
* The `rgx` window is described in the node from the start even though 2.1
  does not map it, so 2.3's identity reads need no DT change.
