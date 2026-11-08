// SPDX-License-Identifier: GPL-2.0-only OR BSD-2-Clause
/*
 * Apple T8015 GFX IOP (the AGX/G10P GPU's RTKit coprocessor)
 *
 * Stage 1 probe driver: upload the GFX firmware, start the core's RTKit
 * management, and report the HELLO.  Does NOT touch RGX, does NOT submit
 * jobs, does NOT power the core.
 *
 * Modelled on Nick Chan's PMP driver (drivers/soc/apple/pmp_t8015_v1.c).
 * See GPU-WIP/probe/README.md and kb/A11-GPU-G10P-PROBE.md.
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
#include <linux/slab.h>
#include <linux/delay.h>

/* AKF remap registers (all GUESS: identical offsets in the t8015 PMP block) */
#define AKF_REMAP_AP_LO\t\t0x8
#define AKF_REMAP_AP_HI\t\t0x10
#define AKF_REMAP_IOP_LO\t0x18
#define AKF_REMAP_IOP_HI\t0x20
#define AKF_REMAP_SZ_LO\t\t0x28
#define AKF_REMAP_SZ_HI\t\t0x30
#define AKF_REMAP_ENABLE\t0x38
#define AKF_REG_80C\t\t0x80c\t/* timebase control (GUESS from PMP) */

/* Fender (window W) registers -- CONFIRMED present in the G10P kext at
 * 0x42d14..0x42d28 and at the 0x2600 power-request site; offsets identical
 * to the A10's. */
#define FENDER_PWR_STATE\t0x1000\t/* state|0x10; poll bit 4 (CONFIRMED) */
#define FENDER_OPEN_MASK\t0x200c\t/* unused by Stage 1 */

/* A window (window A): the IOP's own remap block.  Offsets are GUESS. */
#define IOP_REMAP_AP_LO\t\t0x08
#define IOP_REMAP_AP_HI\t\t0x10
#define IOP_REMAP_IOP_LO\t0x18
#define IOP_REMAP_IOP_HI\t0x20
#define IOP_REMAP_SZ_LO\t\t0x28
#define IOP_REMAP_SZ_HI\t\t0x30
#define IOP_REMAP_ENABLE\t0x38
#define IOP_MBOX_IDX\t\t0x4000\t/* A+0x4000 = 0x1111 (GUESS) */
#define IOP_MBOX_READY\t\t0x4020\t/* A+0x4020 |= 1        (GUESS) */
#define IOP_MBOX_DATA\t\t0x4038\t/* A+0x4038 = HELLO word  (GUESS) */
#define IOP_TIMEBASE_LO\t\t0xc030
#define IOP_TIMEBASE_HI\t\t0xc038
#define IOP_MBOX_FORCE\t\t0x80c\t/* A+0x80c bits (timebase) (GUESS) */
#define IOP_MBOX_SIZE\t\t0x4000
#define IOP_MBOX_READY_MODE\t0x4004

/* firmware runtime size (CONFIRMED, see kb/A11-GPU-G10P-LAYOUT.md section 1) */
#define GFX_FW_RUNTIME\t\t0x8f000
#define GFX_FW_NAME\t\t"apple/gfx-t8015.bin"
#define GFX_FW_COPY_OFF\t0

struct apple_gfx {
\tvoid __iomem\t*akf_base;\t/* window A: gfx-kf reg 0 (0x04D20000) */
\tvoid __iomem\t*fender_base;\t/* window W: gfx-kf reg 1 (0x04D00000) */
\tstruct resource\t*fw_buf;\t/* the 0x8f000 uncached bounce buffer */
\tstruct device\t*dev;
\tconst char\t*fw_name;
\tstruct apple_rtkit\t*rtk;
};

static const struct apple_rtkit_ops apple_gfx_rtkit_ops = {};

static int apple_gfx_upload(struct apple_gfx *gfx)
{
\tconst struct firmware *fw __free(firmware) = NULL;
\tvoid *buf;
\tint ret;

\tret = request_firmware(&fw, gfx->fw_name, gfx->dev);
\tif (ret) {
\t\tdev_err(gfx->dev, "unable to load firmware\n");
\t\treturn ret;
\t}
\tif (fw->size > GFX_FW_RUNTIME) {
\t\tdev_err(gfx->dev, "firmware too large: %zu > 0x%x", fw->size,
\t\t\t GFX_FW_RUNTIME);
\t\treturn -ENOSPC;
\t}

/*
 * The GFX firmware is far larger than the IOP's SRAM (0x5d320 bytes) so it is
 * executed from a physically contiguous DRAM bounce buffer, not from SRAM.
 * Allocate, copy, zero the remainder, clean the cache, then remap both AKF
 * windows onto the buffer.
 */
\tbuf = memremap(dma_alloc_coherent(gfx->dev->parent, GFX_FW_RUNTIME,
\t\t\t\t   NULL, GFP_KERNEL), GFX_FW_RUNTIME);
\tif (!buf)
\t\treturn -ENOMEM;
\tmemcpy(buf, fw->data, fw->size);
\tmemset(buf + fw->size, 0, GFX_FW_RUNTIME - fw->size);
\t/* XXX: cache maintenance; assume dma_alloc_coherent is already coherent */
\tdma_free_coherent(gfx->dev->parent, GFX_FW_RUNTIME, buf, 0);

\t/* Window A (IOP side): map the firmware buffer at IOP address 0. */
\twritel(0, gfx->akf_base + IOP_REMAP_IOP_LO);
\twritel(0, gfx->akf_base + IOP_REMAP_IOP_HI);
\twritel(GFX_FW_RUNTIME, gfx->akf_base + IOP_REMAP_SZ_LO);
\twritel(0, gfx->akf_base + IOP_REMAP_SZ_HI);
\t/* XXX: physical address, not the IOVA; fill in before building */
\t/* writel((uintptr_t)??, gfx->akf_base + IOP_REMAP_AP_LO); */
\twritel(1, gfx->akf_base + IOP_REMAP_ENABLE);

\t/* Window W (Fender side): same buffer, same offsets as A (GUESS) */
\twritel(0, gfx->fender_base + IOP_REMAP_IOP_LO);
\twritel(0, gfx->fender_base + IOP_REMAP_IOP_HI);
\twritel(GFX_FW_RUNTIME, gfx->fender_base + IOP_REMAP_SZ_LO);
\twritel(0, gfx->fender_base + IOP_REMAP_SZ_HI);
\twritel(1, gfx->fender_base + IOP_REMAP_ENABLE);

\t/* Start the IOP: the A10 pokes W+0x2048 bit 0; the PMP pokes control. */
\twritel(1, gfx->fender_base + 0x2048);\t/* GUESS */
\treturn 0;
}

static const struct dev_pm_domain_attach_data pd_data = {
\t.pd_flags = PD_FLAG_DEV_LINK_ON,
};

static int apple_gfx_probe(struct platform_device *pdev)
{
\tstruct device *dev = &pdev->dev;
\tstruct dev_pm_domain_list *domains;
\tstruct apple_gfx *gfx;
\tstruct resource *res;
\tint ret;

\tret = dev_pm_domain_attach_list(dev, &pd_data, &domains);
\tif (ret < 0)
\t\treturn ret;

\tgfx = devm_kzalloc(&pdev->dev, sizeof(*gfx), GFP_KERNEL);
\tif (!gfx)
\t\treturn -ENOMEM;

\tgfx->dev = dev;
\tgfx->fw_name = GFX_FW_NAME;
	gfx->akf_base = devm_platform_ioremap_resource_byname(pdev, "akf");
\tif (IS_ERR(gfx->akf_base))
\t\treturn PTR_ERR(gfx->akf_base);
\tgfx->fender_base = devm_platform_ioremap_resource_byname(pdev, "fender");
\tif (IS_ERR(gfx->fender_base))
\t\treturn PTR_ERR(gfx->fender_base);

\tret = apple_gfx_upload(gfx);
\tif (ret)
\t\treturn ret;

\t/* RTKit boot + HELLO: wire up like the PMP driver, e.g.
\t * rtk = apple_rtkit_alloc(...); apple_rtkit_boot(rtk, ...);
\t * omitted from the draft; the PMP driver shows the shape. */
\tdev_info(dev, "gfx-iop: firmware uploaded, RTKit boot not implemented in this draft\n");
\treturn 0;
}

static int apple_gfx_remove(struct platform_device *pdev)
{
\treturn 0;
}

static const struct of_device_id apple_gfx_of_match[] = {
\t{ .compatible = "apple,t8015-gfx-iop" },
\t{},
};
MODULE_DEVICE_TABLE(of, apple_gfx_of_match);

static struct platform_driver apple_gfx_driver = {
\t.probe = apple_gfx_probe,
\t.remove = apple_gfx_remove,
\t.driver = {
\t\t.name = "apple-t8015-gfx-iop",
\t\t.of_match_table = apple_gfx_of_match,
\t},
};
module_platform_driver(apple_gfx_driver);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("");
MODULE_DESCRIPTION("Probe driver for the A11 / T8015 G10P GPU's GFX IOP");
