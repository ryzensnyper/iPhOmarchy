// SPDX-License-Identifier: GPL-2.0-only
/*
 * Apple T8015 (A11) G10P GPU — Phase 2.2: boot the GFX IOP.
 *
 * The G10P's firmware runs on the "gfx-kf" A7 IOP and speaks RTKit over the
 * IOP mailbox.  The AP must not touch the RGX window until that firmware is
 * alive (an AP read of the unpowered window already rebooted this phone to
 * iOS once).  This phase therefore does exactly one thing: start the IOP and
 * wait for RTKit's HELLO/EPMAP handshake.  It sends no AGX init data, does
 * not power the core, and does not read or write any RGX register.
 *
 * Sequence:
 *   1. ps_gfx is powered on by the platform core, before ->probe() (2.1);
 *   2. the mailbox is started through the RTKit library, so the HELLO cannot
 *      arrive before we listen;
 *   3. a 1 MiB coherent window is programmed into both copies of the window
 *      register block (Fender, 4-byte stride; IOP, 8-byte stride) and the
 *      IOP's window-enable bit is set;
 *   4. the firmware is copied into the window (image + zeroed BSS) and the
 *      IOP CPU is released with the Fender run bit;
 *   5. apple_rtkit_wake() sends the IOP power-state request and waits for
 *      HELLO / EPMAP / the ACK — expect "RTKit: Initializing (protocol
 *      version 12)" in the log;
 *   6. STARTEP is sent for the two AGX endpoints (0x20 init, 0x21 doorbell),
 *      without sending the init page itself.
 *
 * Gate: if apple/gfx-t8015.bin is not in the payload, probe returns 0
 * without starting anything — the Phase 2.1 behaviour.  The firmware blob is
 * a separate, reviewed install step (install-firmware.sh).
 *
 * References (same tree): drivers/soc/apple/pmp_t8015_v1.c (proven on this
 * hardware: RTKit, AKF window, run bit) and
 * drivers/gpu/drm/imagination/pvr_apple.c (the G10P window/run/RTKit layout;
 * never booted on hardware).
 */

#include <linux/dma-mapping.h>
#include <linux/firmware.h>
#include <linux/io.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/sizes.h>
#include <linux/soc/apple/rtkit.h>

#define GFX_WINDOW_SIZE		SZ_1M
#define GFX_FW_RUNTIME		0x8f000	/* image + firmware runtime data */
#define GFX_WINDOW_NEXT		0x98000	/* RTKit buffers live below this (2.3: init page) */

/* Fender: the firmware window (4-byte stride) and the CPU run bit. */
#define FENDER_WINDOW		0x200c
#define FENDER_RUN		0x2048
#define FENDER_RUN_ENABLE	BIT(0)

/* IOP: the same window block at an 8-byte stride, then the enable bit. */
#define IOP_WINDOW		0x0008
#define IOP_WINDOW_ENABLE	0x0038

#define GFX_EP_AGX_INIT		0x20
#define GFX_EP_AGX_DOORBELL	0x21

struct apple_t8015_gfx {
	struct device *dev;
	void __iomem *rgx;	/* mapped for 2.3; never dereferenced here */
	void __iomem *fender;
	void __iomem *iop;
	struct apple_rtkit *rtk;
	void *win;
	dma_addr_t win_dma;
	size_t win_next;
};

/*
 * RTKit's crashlog/ioremport/oslog/syslog buffers must be addressable by the
 * firmware, so they are carved out of the window it already knows about
 * (same policy as pvr_apple_shmem_setup()).
 */
static int apple_t8015_gfx_shmem_setup(void *cookie, struct apple_rtkit_shmem *bfr)
{
	struct apple_t8015_gfx *gfx = cookie;
	size_t size = ALIGN(bfr->size, SZ_4K);

	if (bfr->iova) {
		if (bfr->iova + bfr->size > GFX_WINDOW_SIZE)
			return -EINVAL;
		bfr->buffer = (u8 *)gfx->win + bfr->iova;
		bfr->is_mapped = true;
		return 0;
	}
	if (gfx->win_next + size > GFX_WINDOW_NEXT)
		return -ENOMEM;
	bfr->iova = gfx->win_next;
	bfr->buffer = (u8 *)gfx->win + gfx->win_next;
	gfx->win_next += size;
	return 0;
}

static void apple_t8015_gfx_shmem_destroy(void *cookie, struct apple_rtkit_shmem *bfr)
{
	/* Carved from the window, which lives as long as the device. */
}

static void apple_t8015_gfx_crashed(void *cookie, const void *crashlog, size_t size)
{
	struct apple_t8015_gfx *gfx = cookie;

	dev_err(gfx->dev, "GFX firmware crashed (%zu-byte crashlog)\n", size);
	if (crashlog)
		print_hex_dump(KERN_ERR, "gfx-crashlog: ", DUMP_PREFIX_OFFSET,
			       16, 4, crashlog, size, false);
}

static void apple_t8015_gfx_recv_message(void *cookie, u8 endpoint, u64 message)
{
	struct apple_t8015_gfx *gfx = cookie;

	dev_dbg(gfx->dev, "GFX firmware ep %#x: %#016llx\n", endpoint, message);
}

static const struct apple_rtkit_ops apple_t8015_gfx_rtkit_ops = {
	.crashed = apple_t8015_gfx_crashed,
	.recv_message = apple_t8015_gfx_recv_message,
	.shmem_setup = apple_t8015_gfx_shmem_setup,
	.shmem_destroy = apple_t8015_gfx_shmem_destroy,
};

/* The window is programmed in two copies: Fender (4-byte) and IOP (8-byte). */
static void apple_t8015_gfx_set_window(struct apple_t8015_gfx *gfx)
{
	const u32 fields[] = {
		lower_32_bits(gfx->win_dma),
		upper_32_bits(gfx->win_dma),
		0,
		0,
		GFX_WINDOW_SIZE,
		0,
	};
	unsigned int i;

	for (i = 0; i < ARRAY_SIZE(fields); i++) {
		writel(fields[i], gfx->fender + FENDER_WINDOW + 4 * i);
		writel(fields[i], gfx->iop + IOP_WINDOW + 8 * i);
	}
	writel(1, gfx->iop + IOP_WINDOW_ENABLE);
}

static int apple_t8015_gfx_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	const struct firmware *fw __free(firmware) = NULL;
	const char *fw_name = "apple/gfx-t8015.bin";
	struct apple_t8015_gfx *gfx;
	int ret;

	gfx = devm_kzalloc(dev, sizeof(*gfx), GFP_KERNEL);
	if (!gfx)
		return -ENOMEM;
	gfx->dev = dev;
	platform_set_drvdata(pdev, gfx);

	/* ps_gfx was powered on by the platform core before ->probe(). */
	dev_info(dev, "GFX power domain is up\n");

	/*
	 * Map the three windows.  A mapping is not an access: rgx stays
	 * unused until Phase 2.3, and only fender/iop are written here.
	 */
	gfx->rgx = devm_platform_ioremap_resource_byname(pdev, "rgx");
	if (IS_ERR(gfx->rgx))
		return PTR_ERR(gfx->rgx);
	gfx->fender = devm_platform_ioremap_resource_byname(pdev, "fender");
	if (IS_ERR(gfx->fender))
		return PTR_ERR(gfx->fender);
	gfx->iop = devm_platform_ioremap_resource_byname(pdev, "iop");
	if (IS_ERR(gfx->iop))
		return PTR_ERR(gfx->iop);

	/*
	 * Start the mailbox first: it is what receives HELLO.  If the mailbox
	 * device has not probed yet this returns -EPROBE_DEFER, and the big
	 * allocations below are never made on the retry path.
	 */
	gfx->rtk = devm_apple_rtkit_init(dev, gfx, NULL, 0,
					 &apple_t8015_gfx_rtkit_ops);
	if (IS_ERR(gfx->rtk))
		return dev_err_probe(dev, PTR_ERR(gfx->rtk), "RTKit init failed\n");

	ret = dma_set_mask_and_coherent(dev, DMA_BIT_MASK(40));
	if (ret)
		return dev_err_probe(dev, ret, "40-bit DMA mask not supported\n");

	gfx->win = dmam_alloc_coherent(dev, GFX_WINDOW_SIZE, &gfx->win_dma,
				       GFP_KERNEL);
	if (!gfx->win)
		return -ENOMEM;
	if (!IS_ALIGNED(gfx->win_dma, SZ_16K))
		return dev_err_probe(dev, -EINVAL,
				     "firmware window %pad is not 16 KiB aligned\n",
				     &gfx->win_dma);
	gfx->win_next = GFX_FW_RUNTIME;

	of_property_read_string(dev->of_node, "firmware-name", &fw_name);
	ret = request_firmware(&fw, fw_name, dev);
	if (ret) {
		if (ret == -ENOENT) {
			/* Build-time gate: no blob means a Phase 2.1 boot. */
			dev_info(dev, "%s not installed; IOP not started\n", fw_name);
			return 0;
		}
		return dev_err_probe(dev, ret, "cannot load %s\n", fw_name);
	}
	if (fw->size > GFX_FW_RUNTIME) {
		dev_err(dev, "firmware too large: %zu > %#x\n", fw->size,
			GFX_FW_RUNTIME);
		return -EINVAL;
	}
	memcpy(gfx->win, fw->data, fw->size);
	/* The image does not cover the runtime size: zero the firmware's BSS. */
	memset((u8 *)gfx->win + fw->size, 0, GFX_FW_RUNTIME - fw->size);
	dev_info(dev, "firmware %zu bytes in a %#x-byte window at %pad\n",
		 fw->size, GFX_WINDOW_SIZE, &gfx->win_dma);

	apple_t8015_gfx_set_window(gfx);
	writel(readl(gfx->fender + FENDER_RUN) | FENDER_RUN_ENABLE,
	       gfx->fender + FENDER_RUN);
	dev_info(dev, "GFX IOP released; waiting for RTKit HELLO\n");

	ret = apple_rtkit_wake(gfx->rtk);
	if (ret) {
		/*
		 * Keep the domain up and the machine alive: stop the IOP and
		 * report.  Probe still succeeds, so the device stays bound and
		 * the failure is visible in dmesg.
		 */
		dev_err(dev, "GFX firmware did not answer (%d); IOP stopped\n", ret);
		writel(readl(gfx->fender + FENDER_RUN) & ~FENDER_RUN_ENABLE,
		       gfx->fender + FENDER_RUN);
		return 0;
	}
	dev_info(dev, "GFX firmware is up; RTKit handshake complete\n");

	/* Endpoints are active only if the firmware advertised them in EPMAP. */
	ret = apple_rtkit_start_ep(gfx->rtk, GFX_EP_AGX_INIT);
	if (ret)
		dev_warn(dev, "AGX init endpoint unavailable: %d\n", ret);
	ret = apple_rtkit_start_ep(gfx->rtk, GFX_EP_AGX_DOORBELL);
	if (ret)
		dev_warn(dev, "AGX doorbell endpoint unavailable: %d\n", ret);

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
MODULE_DESCRIPTION("Apple T8015 (A11) G10P GPU — GFX IOP boot (Phase 2.2)");
MODULE_LICENSE("GPL");
