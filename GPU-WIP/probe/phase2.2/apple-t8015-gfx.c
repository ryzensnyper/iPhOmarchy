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
 * Boot #9 sequence (see the boot #8 notes below): the PMP is booted first by
 * pmp_t8015_v1.c and must report itself running, because the GPU's gates
 * (GFX-SGX/GFX-KF/GFX-BUSY, all "no_ps" in the ADT) have no PMGR register of
 * their own -- the PMP owns them.  Only then does the AP touch the block:
 * ps/DVFS read-back, a ps_gfx off->on transition (the pmgr "dock fifo agent"
 * signal), the mailbox read, the RTKit handshake, and finally the RGX read.
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
#include <linux/delay.h>
#include <linux/init.h>
#include <linux/ioport.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_address.h>
#include <linux/platform_device.h>
#include <linux/workqueue.h>
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
	struct delayed_work work;
};

/*
 * Diagnostic (Phase 2.2): the bring-up runs this long after the probe, so
 * the payload's init has brought up the USB gadget that carries the kernel
 * log to the host before the first GFX access resets the phone.
 */
#define GFX_BOOT_DELAY_MS	22000	/* after the PMP diagnostic boot at 12 s */

/*
 * DIAG (Phase 2.2 boot #9): in boot #8 the PMP answered HELLO at 18.9 s and
 * then mainline's 1 s waits expired, so the AP never declared itself powered
 * on ("SET_AP_PWR_STATE(ON)" never left the AP) and no gate could be
 * requested.  Boot #9 boots the PMP from pmp_t8015_v1.c, waits here for it to
 * report itself running, and only then touches the GPU block.
 */
#define GFX_PMP_READY_WAIT_MS	40000
extern bool apple_t8015_pmp_up;

/* PMGR DVFS ("perf") block: two candidate layouts (see the dump below). */
#define PMGR_DVFS_LOW		0x100	/* perf base 0 + 0x100 */
#define PMGR_DVFS_HIGH		0xb4100	/* perf-regs[0].offset + 0x100 */
#define PMGR_DVFS_COUNT		140	/* perf-regs[0].size */

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

/*
 * Diagnostic (Phase 2.2 boot #5): print the step and hold it on the console
 * for three seconds before the access it describes.  The faulting access
 * resets the phone at once (the display is cleared), so the line has to be
 * readable *before* it, not after.
 */
static void apple_t8015_gfx_stage(struct apple_t8015_gfx *gfx, const char *what)
{
	dev_info(gfx->dev, "GFX-STAGE %s\n", what);
	msleep(2000);
}

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

	apple_t8015_gfx_stage(gfx, "7/13: Fender window copy");
	for (i = 0; i < ARRAY_SIZE(fields); i++)
		writel(fields[i], gfx->fender + FENDER_WINDOW + 4 * i);

	apple_t8015_gfx_stage(gfx, "8/13: IOP window copy");
	for (i = 0; i < ARRAY_SIZE(fields); i++)
		writel(fields[i], gfx->iop + IOP_WINDOW + 8 * i);

	apple_t8015_gfx_stage(gfx, "9/13: IOP window enable");
	writel(1, gfx->iop + IOP_WINDOW_ENABLE);
}

/*
 * Diagnostic (Phase 2.2): what does the PMGR itself say about ps_gfx?  The
 * register is the one the power-domain driver writes: PS_TARGET is the
 * requested state, PS_ACTUAL the reached one, and the two "was" bits say
 * whether the block was clock- or power-gated when the domain came up.
 * Reading it is harmless: the PMGR is always on.
 */
static void apple_t8015_gfx_dump_ps(struct apple_t8015_gfx *gfx)
{
	struct device_node *ps_node, *pmgr_node;
	void __iomem *pmgr;
	u32 offset = 0, val;
	int i;

	ps_node = of_parse_phandle(gfx->dev->of_node, "power-domains", 0);
	if (!ps_node) {
		dev_info(gfx->dev, "ps_gfx: no power-domains phandle\n");
		return;
	}
	if (of_property_read_u32(ps_node, "reg", &offset)) {
		dev_info(gfx->dev, "ps_gfx: no reg on %pOF\n", ps_node);
		return;
	}
	pmgr_node = of_get_parent(ps_node);
	if (!pmgr_node) {
		dev_info(gfx->dev, "ps_gfx: no parent for %pOF\n", ps_node);
		return;
	}
	pmgr = of_iomap(pmgr_node, 0);
	if (!pmgr) {
		dev_info(gfx->dev, "ps_gfx: cannot map %pOF\n", pmgr_node);
		return;
	}

	val = readl(pmgr + offset);
	dev_info(gfx->dev,
		 "ps_gfx: PS @%#x = %#x (auto %d, was clkgated %d, was pwrgated %d, actual %#x, target %#x)\n",
		 offset, val, !!(val & BIT(28)), !!(val & BIT(9)), !!(val & BIT(8)),
		 (val >> 4) & 0xf, val & 0xf);

	/* Neighbours: the rest of the 0x80300 bank, so the console says which
	 * device states are active around the GFX one. */
	for (i = 0; i < 32; i++) {
		u32 off = 0x80300 + i * 8;

		val = readl(pmgr + off);
		if (!val)
			continue;
		dev_info(gfx->dev, "  ps bank @%#x = %#x (auto %d, clk %d, pwr %d, actual %#x, target %#x)\n",
			 off, val, !!(val & BIT(28)), !!(val & BIT(9)), !!(val & BIT(8)),
			 (val >> 4) & 0xf, val & 0xf);
	}
}

/*
 * The pmgr node, mapped for read.  The *DT* maps PMGR as 0x8c000 (the A10's
 * size), while the ADT says the block is 16 MiB and the DVFS/perf registers
 * live at +0xb4000 -- outside the DT's window, which is why boot #9 took a
 * level-3 translation fault at 0x2320b4350.  Map the whole 1 MiB needed
 * (ps banks to +0x88000, clock at +0x78000, perf block to +0xb4d00) instead.
 */
#define PMGR_DIAG_MAP_SIZE	SZ_1M

static void __iomem *apple_t8015_gfx_map_pmgr(struct apple_t8015_gfx *gfx)
{
	struct device_node *ps_node, *pmgr_node;
	struct resource res;

	ps_node = of_parse_phandle(gfx->dev->of_node, "power-domains", 0);
	if (!ps_node)
		return NULL;
	pmgr_node = of_get_parent(ps_node);
	if (!pmgr_node)
		return NULL;
	if (of_address_to_resource(pmgr_node, 0, &res))
		return NULL;

	return ioremap(res.start, PMGR_DIAG_MAP_SIZE);
}

/*
 * Diagnostic (Phase 2.2 boot #9): the ADT gives every DVFS domain a "perf"
 * register (pmgr/perf-regs + pmgr/power-domains).  The GFX domain is
 * perf_block 0, perf_idx 0x2c.  If the GPU's clock is simply unconfigured,
 * that register is where it shows; both candidate bases are dumped because
 * m1n1's own decoder disagrees with the ADT offsets.  Reads only.
 */
static const struct { const char *name; u32 idx; } __maybe_unused dvfs_known[] = {
	{ "dvfs-MCC", 0x25 }, { "dvfs-DCS01", 0x26 }, { "dvfs-ACS", 0x28 },
	{ "dvfs-DISP0_GP", 0x29 }, { "dvfs-PMP", 0x2a },
	{ "dvfs-PMS_SRAM", 0x2b }, { "dvfs-GFX", 0x2c },
	{ "dvfs-SEP", 0x2d }, { "dvfs-ANS2", 0x2f },
	{ "dev-MSR", 0x11 }, { "dev-PMP", 0x12 }, { "dev-PMS_SRAM", 0x13 },
	{ "dev-PCIE", 0x14 }, { "dev-GFX", 0x16 }, { "dev-SEP", 0x17 },
};

/* One of the two candidate perf windows (see the block comment).  Kept for
 * the next DVFS attempt; boot #12 reads the bridge windows instead. */
static void __maybe_unused
apple_t8015_gfx_dump_dvfs_win(struct apple_t8015_gfx *gfx,
			      u32 base, const char *tag)
{
	void __iomem *pmgr = apple_t8015_gfx_map_pmgr(gfx);
	unsigned int i, k;

	if (!pmgr) {
		dev_info(gfx->dev, "dvfs: cannot map PMGR\n");
		return;
	}

	for (k = 0; k < ARRAY_SIZE(dvfs_known); k++)
		dev_info(gfx->dev, "dvfs-%-4s %-9s @%#x = %#010x\n", tag,
			 dvfs_known[k].name, base + dvfs_known[k].idx * 0x10,
			 readl(pmgr + base + dvfs_known[k].idx * 0x10));

	for (i = 0; i < PMGR_DVFS_COUNT; i++) {
		u32 val = readl(pmgr + base + i * 0x10);

		if (val)
			dev_info(gfx->dev, "  dvfs-%s[%#x] @%#x = %#010x\n",
				 tag, i, base + i * 0x10, val);
	}
}

/*
 * DIAG (Phase 2.2 boot #11): candidates for the gate request itself.  The
 * ADT's function-* properties (30:clkG(), 30:pwrG()) are implemented on the
 * AP side, and the PMP firmware's own clock-gate handler (VA 0x0100e920)
 * decodes one 32-bit word with the 8-bit device index in bits 12..19.  The
 * wrapper is unknown, so send a few plausible encodings to the PMP's first
 * application endpoint (32 = iOS's "PMPEndpoint1") and let the firmware's
 * syslog tell us what it made of them.
 */
extern int apple_t8015_pmp_send(u8 ep, u64 msg);
extern int apple_t8015_pmp_start_ep(u8 ep);

/*
 * DIAG (Phase 2.2 boot #12): the PMGR "bridge" windows.  bridge-reg-index=19
 * in the ADT means bridge b is pmgr reg[19+b]; GFX is group 8, so the GPU's
 * own power/clock block ("AGX_PMGR" in ApplePMGR's block table) is
 * 0x05000000/0x9000.  ApplePMGR has readGFXClkGenReg/writeGFXClkGenReg, so
 * this window holds the GPU clock generator that nothing in Linux programs.
 * Compare it with the DISP0_BE bridge (group 7, 0x19000000), which is
 * demonstrably clocked and running (simplefb drives the panel).
 */
#define GFX_BRIDGE_ADDR		0x05000000UL
#define GFX_BRIDGE_SIZE		0x9000UL
#define DISP0_BRIDGE_ADDR	0x19000000UL
#define DISP0_BRIDGE_SIZE	0x9000UL

static void apple_t8015_gfx_dump_bridge(struct apple_t8015_gfx *gfx,
					const char *tag, phys_addr_t addr,
					size_t size)
{
	void __iomem *win;
	unsigned int i, nz = 0;

	win = devm_ioremap(gfx->dev, addr, size);
	if (!win) {
		dev_info(gfx->dev, "bridge %s: cannot map %pa\n", tag, &addr);
		return;
	}

	/* First 0x80 bytes verbatim: that is where a target/actual or
	 * enable/divider pair normally sits. */
	for (i = 0; i < 0x20; i += 4)
		dev_info(gfx->dev, "bridge %s @%pa+%#04x = %#010x\n",
			 tag, &addr, i, readl(win + i));

	for (i = 0x20; i < size; i += 4) {
		u32 val = readl(win + i);

		if (!val)
			continue;
		nz++;
		if (nz <= 40)
			dev_info(gfx->dev, "bridge %s nz @%#06x = %#010x\n",
				 tag, i, val);
	}
	dev_info(gfx->dev, "bridge %s: %u non-zero words in %#zx bytes\n",
		 tag, nz, size);
}

static void apple_t8015_gfx_probe_bridges(struct apple_t8015_gfx *gfx)
{
	apple_t8015_gfx_dump_bridge(gfx, "disp0(7)", DISP0_BRIDGE_ADDR,
				    DISP0_BRIDGE_SIZE);
	apple_t8015_gfx_dump_bridge(gfx, "gfx(8)", GFX_BRIDGE_ADDR,
				    GFX_BRIDGE_SIZE);
}

static void apple_t8015_gfx_try_pmp_calls(struct apple_t8015_gfx *gfx)
{
	static const struct { const char *what; u64 msg; } cand[] = {
		{ "clg-word GFX-SGX(148)", 0x0fULL | (148ULL << 12) },
		{ "clg-word GFX-BUSY(123)", 0x0fULL | (123ULL << 12) },
		{ "clg-word GFX-KF(149)", 0x0fULL | (149ULL << 12) },
		{ "clg-word GFX(124)", 0x0fULL | (124ULL << 12) },
		{ "fn30 arg=148", (30ULL << 32) | 148 },
		{ "fn30 arg=124", (30ULL << 32) | 124 },
	};
	unsigned int i;
	int ret;

	/* Boot #12: start the endpoint first -- boot #11 sent to ep 32 while
	 * it was still stopped. */
	ret = apple_t8015_pmp_start_ep(32);
	dev_info(gfx->dev, "pmp-call STARTEP(32) -> %d\n", ret);
	msleep(1500);

	for (i = 0; i < ARRAY_SIZE(cand); i++) {
		dev_info(gfx->dev, "pmp-call %-22s msg=%#llx -> %d\n",
			 cand[i].what, cand[i].msg,
			 apple_t8015_pmp_send(32, cand[i].msg));
		msleep(1500);
	}
}

/*
 * Diagnostic (Phase 2.2 boot #9): the pmgr node declares itself a "dock fifo
 * agent", so a power-state transition is what tells the PMP about the GPU.
 * Boot #8 powered the domain while the PMP was still mid-handshake; power it
 * down and back up now that the PMP is up, so the transition is re-sent.
 */
static bool apple_t8015_gfx_retoggle_ps(struct apple_t8015_gfx *gfx)
{
	struct device_node *ps_node;
	void __iomem *pmgr = apple_t8015_gfx_map_pmgr(gfx);
	u32 offset = 0, val;
	int i;

	if (!pmgr)
		return true;
	ps_node = of_parse_phandle(gfx->dev->of_node, "power-domains", 0);
	if (!ps_node || of_property_read_u32(ps_node, "reg", &offset)) {
		dev_info(gfx->dev, "retoggle: no ps_gfx offset\n");
		return true;
	}

	val = readl(pmgr + offset);
	dev_info(gfx->dev, "retoggle: before = %#010x\n", val);

	/* Same field set m1n1's pmgr_set_mode() touches. */
	writel((val & ~(BIT(28) | BIT(9) | BIT(8) | 0xf)), pmgr + offset);
	msleep(20);

	val = readl(pmgr + offset);
	writel((val & ~(BIT(28) | BIT(9) | BIT(8) | 0xf)) | 0xf, pmgr + offset);
	for (i = 0; i < 50; i++) {
		val = readl(pmgr + offset);
		if (((val >> 4) & 0xf) == 0xf)
			break;
		msleep(10);
	}
	dev_info(gfx->dev,
		 "retoggle: after = %#010x (auto %d, clk %d, pwr %d, actual %#x, target %#x, %d ms)\n",
		 val, !!(val & BIT(28)), !!(val & BIT(9)), !!(val & BIT(8)),
		 (val >> 4) & 0xf, val & 0xf, i * 10);

	/* If the domain did not come back, the GPU block is dark by our own
	 * doing: any access below would hang the bus, so stop here. */
	if (((val >> 4) & 0xf) != 0xf) {
		dev_err(gfx->dev,
			"retoggle: ps_gfx stuck at actual %#x; GPU accesses skipped\n",
			(val >> 4) & 0xf);
		return false;
	}

	return true;
}

/*
 * Diagnostic (Phase 2.2): does the RGX core answer?  The mailbox read that
 * killed boot #5 and #6 is inside the IOP sub-block; reading the core ID of
 * the GPU itself tells a dark power domain from a dark IOP sub-block.
 */
static void apple_t8015_gfx_probe_rgx(struct apple_t8015_gfx *gfx)
{
	u32 id = readl(gfx->rgx + 0x18);
	u32 rev = readl(gfx->rgx + 0x20);

	dev_info(gfx->dev, "rgx: core id %#x revision %#x\n", id, rev);
}

/*
 * Diagnostic (Phase 2.2): is the mailbox page itself readable?  The mailbox
 * device owns 0x4d24000 (IOP+0x4000); this maps it without claiming it and
 * only reads the A2I control register, which the G10P kext reads as well.
 * If the block is clocked and powered this returns a value; if it is not,
 * the read hangs the bus like the write did.
 */
static void apple_t8015_gfx_probe_mailbox(struct apple_t8015_gfx *gfx)
{
	struct device_node *mbox_node = NULL;
	struct resource res;
	void __iomem *mbox;
	u32 phandle = 0, val;

	if (of_property_read_u32(gfx->dev->of_node, "mboxes", &phandle))
		return;
	mbox_node = of_find_node_by_phandle(phandle);
	if (!mbox_node)
		return;
	if (of_address_to_resource(mbox_node, 0, &res))
		return;
	mbox = devm_ioremap(gfx->dev, res.start, SZ_4K);
	if (!mbox)
		return;
	val = readl(mbox + 0x08);
	dev_info(gfx->dev,
		"mailbox: A2I control @%pa+0x08 = %#x (empty bit %d, full bit %d)\n",
		&res.start, val, !!(val & BIT(17)), !!(val & BIT(16)));
}

/*
 * The GFX bring-up: the mailbox first (it is what receives HELLO), then the
 * firmware window in both copies, then the IOP's run bit, then the RTKit
 * handshake.  Every step is announced and held on the console, because the
 * access that faults resets the phone and takes the display with it.
 */
static void apple_t8015_gfx_boot_work(struct work_struct *work)
{
	struct apple_t8015_gfx *gfx =
		container_of(to_delayed_work(work), struct apple_t8015_gfx, work);
	struct device *dev = gfx->dev;
	int ret, i;

	/* Boot #9: everything below is only meaningful once the PMP -- the
	 * block that owns this GPU's gates -- is a running RTKit peer. */
	apple_t8015_gfx_stage(gfx, "0/13: wait for the PMP to come up");
	for (i = 0; i < GFX_PMP_READY_WAIT_MS / 500; i++) {
		if (apple_t8015_pmp_up)
			break;
		msleep(500);
	}
	dev_info(dev, "GFX-DIAG: PMP %s after %d ms\n",
		 apple_t8015_pmp_up ? "is up" : "never came up", i * 500);

	apple_t8015_gfx_stage(gfx, "1/13: ps_gfx power state (PMGR read)");
	apple_t8015_gfx_dump_ps(gfx);

	/*
	 * Boot #12: the GPU's own PMGR block (bridge 8 of 13) and the display's
	 * bridge (group 7) as a known-clocked reference.  Both are read-only;
	 * when the GPU port is down this window is where that shows.
	 */
	apple_t8015_gfx_stage(gfx, "2/13: PMGR bridge windows (GFX 0x5000000 / DISP0 0x19000000)");
	apple_t8015_gfx_probe_bridges(gfx);

	apple_t8015_gfx_stage(gfx, "3/13: PMP endpoint 32 STARTEP + candidates");
	apple_t8015_gfx_try_pmp_calls(gfx);

	apple_t8015_gfx_stage(gfx, "4/13: ps_gfx off->on (re-send the gate request)");
	if (!apple_t8015_gfx_retoggle_ps(gfx))
		return;

	apple_t8015_gfx_stage(gfx, "5/13: mailbox register read (IOP+0x4008)");
	apple_t8015_gfx_probe_mailbox(gfx);

	apple_t8015_gfx_stage(gfx, "6/13: mailbox (RTKit) init");
	gfx->rtk = devm_apple_rtkit_init(dev, gfx, NULL, 0,
					 &apple_t8015_gfx_rtkit_ops);
	if (IS_ERR(gfx->rtk)) {
		dev_err(dev, "RTKit init failed\n");
		return;
	}

	apple_t8015_gfx_set_window(gfx);
	apple_t8015_gfx_stage(gfx, "10/13: release the IOP (run bit)");
	writel(readl(gfx->fender + FENDER_RUN) | FENDER_RUN_ENABLE,
	       gfx->fender + FENDER_RUN);
	dev_info(dev, "GFX IOP released; waiting for RTKit HELLO\n");

	ret = apple_rtkit_wake(gfx->rtk);
	if (ret) {
		/*
		 * Keep the domain up and the machine alive: report.  The IOP
		 * is left running, so a later stage (Phase 2.3) can retry.
		 */
		dev_err(dev, "GFX firmware did not answer (%d)\n", ret);
	} else {
		dev_info(dev, "GFX firmware is up; RTKit handshake complete\n");

		/* Endpoints are only active if the firmware advertised them. */
		ret = apple_rtkit_start_ep(gfx->rtk, GFX_EP_AGX_INIT);
		if (ret)
			dev_warn(dev, "AGX init endpoint unavailable: %d\n", ret);
		ret = apple_rtkit_start_ep(gfx->rtk, GFX_EP_AGX_DOORBELL);
		if (ret)
			dev_warn(dev, "AGX doorbell endpoint unavailable: %d\n",
				 ret);
	}

	/* Phase 2.3 precursor, last because a dark RGX window hangs the bus. */
	apple_t8015_gfx_stage(gfx, "11/13: RGX core id read (0x4000000+0x18)");
	apple_t8015_gfx_probe_rgx(gfx);
}

static int apple_t8015_gfx_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	const struct firmware *fw __free(firmware) = NULL;
	const char *fw_name = "apple/gfx-t8015.bin";
	struct apple_t8015_gfx *gfx;
	struct resource *res;
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
	/*
	 * The IOP window contains the mailbox page at +0x4000, which the
	 * mailbox device has already claimed; request_mem_region() on the
	 * whole window fails with -EBUSY.  A plain ioremap is enough: the
	 * window registers live at +0x08..+0x38, so only the first page is
	 * mapped and the mailbox's page is never touched.
	 */
	res = platform_get_resource_byname(pdev, IORESOURCE_MEM, "iop");
	if (!res || resource_size(res) < SZ_4K)
		return -EINVAL;
	gfx->iop = devm_ioremap(dev, res->start, SZ_4K);
	if (!gfx->iop)
		return -ENOMEM;

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

	/*
	 * The hardware sequence runs from a work item: the probe must return
	 * before the payload's init starts (the init brings up the USB gadget
	 * that carries the kernel log to the host), and the access that
	 * resets the phone must happen after that gadget is up.  It sits
	 * behind the PMP's diagnostic boot: if the PMP is what performs the
	 * GPU's clock/power gating, the mailbox only answers once it runs.
	 */
	INIT_DELAYED_WORK(&gfx->work, apple_t8015_gfx_boot_work);
	schedule_delayed_work(&gfx->work, msecs_to_jiffies(GFX_BOOT_DELAY_MS));
	dev_info(dev, "GFX-DIAG: IOP bring-up in %u s\n", GFX_BOOT_DELAY_MS / 1000);

	return 0;
}

static const struct of_device_id apple_t8015_gfx_of_match[] = {
	{ .compatible = "apple,t8015-gpu" },
	{}
};
MODULE_DEVICE_TABLE(of, apple_t8015_gfx_of_match);

static void apple_t8015_gfx_remove(struct platform_device *pdev)
{
	struct apple_t8015_gfx *gfx = platform_get_drvdata(pdev);

	cancel_delayed_work_sync(&gfx->work);
}

static struct platform_driver apple_t8015_gfx_driver = {
	.probe = apple_t8015_gfx_probe,
	.remove = apple_t8015_gfx_remove,
	.driver = {
		.name = "apple-t8015-gfx",
		.of_match_table = apple_t8015_gfx_of_match,
	},
};
/*
 * Diagnostic (Phase 2.2 boot #4): the driver registers at late_initcall, not
 * at device_initcall.  drivers/soc/ links before drivers/gpu/, so a
 * device_initcall probe runs *before* simpledrm has registered the
 * framebuffer: the VT console cannot show anything yet, which is why boot
 * #3 produced no text at all.  At late_initcall the framebuffer exists and
 * the console is live, so a bus stall leaves its last line on the screen.
 */
static int __init apple_t8015_gfx_driver_init(void)
{
	return platform_driver_register(&apple_t8015_gfx_driver);
}

static void __exit apple_t8015_gfx_driver_exit(void)
{
	platform_driver_unregister(&apple_t8015_gfx_driver);
}

late_initcall(apple_t8015_gfx_driver_init);
module_exit(apple_t8015_gfx_driver_exit);

MODULE_AUTHOR("Doug");
MODULE_DESCRIPTION("Apple T8015 (A11) G10P GPU — GFX IOP boot (Phase 2.2)");
MODULE_LICENSE("GPL");
