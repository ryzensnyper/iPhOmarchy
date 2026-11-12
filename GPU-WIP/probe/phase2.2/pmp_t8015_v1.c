// SPDX-License-Identifier: GPL-2.0-only OR MIT
/*
 * Apple T8015 PMP (Power Management Processor) Driver
 *
 * Copyright 2026 Nick Chan
 */

#include <linux/bitfield.h>
#include <linux/firmware.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_platform.h>
#include <linux/platform_device.h>
#include <linux/pm_domain.h>
#include <linux/soc/apple/rtkit.h>
#include <linux/dma-mapping.h>
#include <linux/ioport.h>
#include <linux/io.h>
#include <linux/delay.h>
#include <linux/init.h>
#include <linux/string.h>
#include <linux/workqueue.h>

#define AKF_REMAP_AP_LO		0x8
#define AKF_REMAP_AP_HI		0x10
#define AKF_REMAP_IOP_LO	0x18
#define AKF_REMAP_IOP_HI	0x20
#define AKF_REMAP_SZ_LO		0x28
#define AKF_REMAP_SZ_HI		0x30
#define AKF_REMAP_ENABLE	0x38
#define AKF_REG_80C		0x80c

/* Diagnostic boot only (the `gpu-diag` bootarg): give the payload's init time
 * to bring up the USB log bridge before the PMP's SRAM is touched. */
#define PMP_DIAG_DELAY_MS	12000

/* DIAG (Phase 2.2 boot #9): boot #8 showed HELLO + EPMAP but no IOP power
 * ACK within mainline's 1 s.  m1n1 waits for that ACK without any timeout, so
 * the PMP is simply slow.  Poll it for this long before giving up, and tell
 * the GFX diagnostic whether the PMP ever became a usable RTKit peer. */
#define PMP_DIAG_READY_POLL_MS	25000

bool apple_t8015_pmp_up;
EXPORT_SYMBOL_GPL(apple_t8015_pmp_up);

/* DIAG (boot #11): the PMP advertises application endpoints (ep 32 =
 * "PMPEndpoint1" in iOS, the PMP v2 client interface).  Let the GPU
 * diagnostic try candidate messages on them; the PMP's own syslog endpoint is
 * started by the RTKit core, so its reaction ("Not implemented", "!clg: %08x")
 * shows up in the Linux log. */
struct apple_rtkit *apple_t8015_pmp_rtk;
EXPORT_SYMBOL_GPL(apple_t8015_pmp_rtk);

int apple_t8015_pmp_send(u8 ep, u64 msg)
{
	if (!apple_t8015_pmp_up || !apple_t8015_pmp_rtk)
		return -ENODEV;

	return apple_rtkit_send_message(apple_t8015_pmp_rtk, ep, msg, NULL, false);
}
EXPORT_SYMBOL_GPL(apple_t8015_pmp_send);

/* DIAG (boot #12): an application endpoint has to be STARTEP'ed before the
 * firmware routes messages to its service; boot #11 sent to ep 32 without it
 * and the PMP stayed silent. */
int apple_t8015_pmp_start_ep(u8 ep)
{
	if (!apple_t8015_pmp_up || !apple_t8015_pmp_rtk)
		return -ENODEV;

	return apple_rtkit_start_ep(apple_t8015_pmp_rtk, ep);
}
EXPORT_SYMBOL_GPL(apple_t8015_pmp_start_ep);

struct apple_pmp {
	void __iomem *akf_base;
	void __iomem *ctl_base;
	void __iomem *sram_base;
	struct resource *sram;
	struct device *dev;
	const char *fw_name;
	struct apple_rtkit *rtk;
	struct delayed_work work;
	bool diag;
};

static const struct apple_rtkit_ops apple_pmp_rtkit_ops = {};

static void apple_pmp_diag(struct apple_pmp *pmp, const char *what)
{
	if (!pmp->diag)
		return;
	dev_info(pmp->dev, "PMP-DIAG %s\n", what);
	msleep(1000);
}

static int apple_pmp_upload_firmware(struct apple_pmp *pmp)
{
	const struct firmware *fw __free(firmware) = NULL;
	int ret;

	apple_pmp_diag(pmp, "0/4: firmware copy to SRAM");
	ret = request_firmware(&fw, pmp->fw_name, pmp->dev);
	if (ret) {
		dev_err(pmp->dev, "unable to load firmware\n");
		return ret;
	}

	if (fw->size > resource_size(pmp->sram)) {
		dev_err(pmp->dev, "firmware larger than SRAM: %zu > %llu",
			fw->size, resource_size(pmp->sram));
		return -ENOSPC;
	}

	memcpy_toio(pmp->sram_base, fw->data, fw->size);

	apple_pmp_diag(pmp, "1/4: AKF remap (SRAM at 0x0)");
	/* Map PMP SRAM to its reset vector (0x0) */
	writel(0, pmp->akf_base + AKF_REMAP_IOP_LO);
	writel(0, pmp->akf_base + AKF_REMAP_IOP_HI);
	writel(resource_size(pmp->sram) & 0xffffffff, pmp->akf_base + AKF_REMAP_SZ_LO);
	writel((resource_size(pmp->sram) >> 32) & 0xffffffff,
		pmp->akf_base + AKF_REMAP_SZ_HI);
	writel((uintptr_t)pmp->sram->start & 0xffffffff,
		pmp->akf_base + AKF_REMAP_AP_LO);
	writel(((uintptr_t)pmp->sram->start >> 32) & 0xffffffff,
		pmp->akf_base + AKF_REMAP_AP_HI);
	writel(1, pmp->akf_base + AKF_REMAP_ENABLE);

	/* Unknown */
	writel(0, pmp->akf_base + AKF_REG_80C);
	writel(2, pmp->akf_base + AKF_REG_80C);

	/* Start PMP */
	apple_pmp_diag(pmp, "2/4: start (control = 1)");
	writel(1, pmp->ctl_base);

	return 0;
}

static int apple_pmp_boot(struct apple_pmp *pmp)
{
	int ret;

	ret = apple_pmp_upload_firmware(pmp);
	if (ret)
		return ret;

	apple_pmp_diag(pmp, "3/4: RTKit init");
	pmp->rtk = devm_apple_rtkit_init(pmp->dev, pmp, NULL, 0,
					 &apple_pmp_rtkit_ops);
	if (IS_ERR(pmp->rtk))
		return dev_err_probe(pmp->dev, PTR_ERR(pmp->rtk),
				     "Failed to initialize RTKit");

	if (dma_set_mask_and_coherent(pmp->dev, DMA_BIT_MASK(64))) {
		ret = -ENXIO;
		return ret;
	}

	apple_pmp_diag(pmp, "4/4: RTKit wake (waiting for HELLO)");
	ret = apple_rtkit_wake(pmp->rtk);
	if (ret)
		dev_err(pmp->dev, "RTKit wake returned %d (continuing)\n", ret);

	/* The handshake may still be in flight (slow firmware): keep polling
	 * until the PMP reports itself running, or give up. */
	for (int i = 0; i < PMP_DIAG_READY_POLL_MS / 500; i++) {
		if (apple_rtkit_is_running(pmp->rtk))
			break;
		msleep(500);

		/*
		 * mainline only sends SET_AP_PWR_STATE(ON) at the very end of
		 * a successful boot().  The firmware validates that message
		 * ("Invalid AP power: %d"), and the PMP will not gate anything
		 * for an AP that never declared itself on, so send it by hand
		 * if boot() aborted early.  Type 0xb sits in bits 59:52, the
		 * power state (ON = 0x20) in bits 15:0.
		 */
		if (i == 4 && !apple_rtkit_is_running(pmp->rtk)) {
			u64 msg = (0xbULL << 52) | 0x20;

			dev_info(pmp->dev, "PMP-DIAG: forcing SET_AP_PWR_STATE(ON)\n");
			apple_rtkit_send_message(pmp->rtk, 0, msg, NULL, false);
		}
	}

	apple_t8015_pmp_up = apple_rtkit_is_running(pmp->rtk);
	if (!apple_t8015_pmp_up) {
		dev_err(pmp->dev, "PMP did not come up (wake=%d)\n", ret);
		return ret ?: -ETIME;
	}

	dev_info(pmp->dev, "PMP is up (AP power state ON, RTKit peer running)\n");
	apple_t8015_pmp_rtk = pmp->rtk;

	return 0;
}

static void apple_pmp_boot_work(struct work_struct *work)
{
	struct apple_pmp *pmp =
		container_of(to_delayed_work(work), struct apple_pmp, work);

	apple_pmp_boot(pmp);
}

static const struct dev_pm_domain_attach_data pd_data = {
	.pd_flags = PD_FLAG_DEV_LINK_ON,
};

static int apple_pmp_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct dev_pm_domain_list *domains;
	struct apple_pmp *pmp;
	struct resource *res;
	int ret;

	ret = dev_pm_domain_attach_list(dev, &pd_data, &domains);
	if (ret < 0)
		return ret;

	pmp = devm_kzalloc(&pdev->dev, sizeof(*pmp), GFP_KERNEL);
	if (!pmp)
		return -ENOMEM;

	pmp->dev = dev;

	pmp->akf_base = devm_platform_ioremap_resource_byname(pdev, "akf");
	if (IS_ERR(pmp->akf_base))
		return PTR_ERR(pmp->akf_base);

	pmp->ctl_base = devm_platform_ioremap_resource_byname(pdev, "control");
	if (IS_ERR(pmp->ctl_base))
		return PTR_ERR(pmp->ctl_base);

	res = platform_get_resource_byname(pdev, IORESOURCE_MEM, "sram");
	if (IS_ERR(res))
		return PTR_ERR(res);

	pmp->sram = res;
	pmp->sram_base = devm_ioremap_resource(&pdev->dev, res);
	if (IS_ERR(pmp->sram_base))
		return PTR_ERR(pmp->sram_base);

	ret = device_property_read_string(dev, "firmware-name", &pmp->fw_name);
	if (ret)
		return dev_err_probe(dev, ret, "unable to get firmware name\n");

	pmp->diag = strstr(saved_command_line, "gpu-diag") != NULL;
	if (pmp->diag) {
		INIT_DELAYED_WORK(&pmp->work, apple_pmp_boot_work);
		schedule_delayed_work(&pmp->work,
				      msecs_to_jiffies(PMP_DIAG_DELAY_MS));
		dev_info(dev, "PMP-DIAG: bring-up in %u s\n",
			 PMP_DIAG_DELAY_MS / 1000);
		return 0;
	}

	return apple_pmp_boot(pmp);
}

static const struct of_device_id apple_pmp_of_match[] = {
	{ .compatible = "apple,t8015-pmp-v1" },
	{}
};
MODULE_DEVICE_TABLE(of, apple_pmp_of_match);


static struct platform_driver apple_pmp_driver = {
	.driver = {
		.name = "pmp-t8015-v1",
		.of_match_table = apple_pmp_of_match,
	},
	.probe = apple_pmp_probe,
};
module_platform_driver(apple_pmp_driver);

MODULE_AUTHOR("Nick Chan <towinchenmi@gmail.com>");
MODULE_LICENSE("Dual MIT/GPL");
MODULE_DESCRIPTION("Apple T8015 PMP driver");
