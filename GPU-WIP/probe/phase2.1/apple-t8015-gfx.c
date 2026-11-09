// SPDX-License-Identifier: GPL-2.0-only
/*
 * Apple T8015 (A11) G10P GPU — Phase 2.1: power-domain consumer only.
 *
 * The G10P is an AGX core whose firmware (the "GFX IOP") must be alive
 * before any AP-side access to the RGX / Fender / IOP windows is safe; an
 * AP read of the unpowered GPU window rebooted this phone to iOS once.
 * This driver exists only to give the GFX power domain a consumer, so that
 * the PMGR power-domain framework enables ps_gfx before anything else can
 * touch the GPU.
 *
 * Phase 2.1 deliberately touches no register:
 *   - the platform core attaches the device to its power domain and powers
 *     the domain on (PD_FLAG_ATTACH_POWER_ON) *before* ->probe() runs;
 *   - ->probe() maps nothing and writes nothing.
 *
 * Later phases grow this driver, not a new one:
 *   - 2.2: allocate the firmware bounce buffer, map the windows, release the
 *          IOP CPU, wait for the RTKit HELLO;
 *   - 2.3: request the Fender power state, read the RGX identity registers.
 */

#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>

struct apple_t8015_gfx {
	struct device *dev;
};

static int apple_t8015_gfx_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct apple_t8015_gfx *gfx;

	gfx = devm_kzalloc(dev, sizeof(*gfx), GFP_KERNEL);
	if (!gfx)
		return -ENOMEM;

	gfx->dev = dev;
	platform_set_drvdata(pdev, gfx);

	/*
	 * By the time we are here the core has run genpd_power_on() for
	 * ps_gfx (PS_TARGET = 0xf, poll PS_ACTUAL, 100 ms).  Deliberately no
	 * ioremap, no readl, no writel: Phase 2.1 only proves the domain.
	 */
	dev_info(dev, "GFX power domain is up; no hardware access in this phase\n");

	return 0;
}

static const struct of_device_id apple_t8015_gfx_of_match[] = {
	{ .compatible = "apple,t8015-gpu" },
	{}
};
MODULE_DEVICE_TABLE(of, apple_t8015_gfx_of_match);

static struct platform_driver apple_t8015_gfx_driver = {
	.probe = apple_t8015_gfx_probe,
	.driver = {
		.name = "apple-t8015-gfx",
		.of_match_table = apple_t8015_gfx_of_match,
	},
};
module_platform_driver(apple_t8015_gfx_driver);

MODULE_AUTHOR("Doug");
MODULE_DESCRIPTION("Apple T8015 (A11) G10P GPU power-domain consumer (Phase 2.1)");
MODULE_LICENSE("GPL");
