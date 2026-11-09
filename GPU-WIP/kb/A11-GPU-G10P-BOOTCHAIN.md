# A11 / T8015 GPU — the D21 boot chain, the kernel tree, and the Phase-2.1 traps

*(Written 2026-11-09.  **Nothing in this document has been executed on the
hardware.**  Everything here was established by read-only inspection: SSH
commands on the phone (`uname`, `dmesg`, `/proc/config.gz`, `pm_genpd`
debugfs), and `git` / file reads on the host.  No register was touched, no
file on the phone was written, no kernel was rebuilt.)*

This document answers the question the previous session left open — *which
kernel tree builds the image this phone is actually running?* — and records
the traps that the answer exposes for Phase 2.1.

---

## 1. The booting image: `d21-touchgood` @ `c2a38a5d`

**Resolved: the tree is `d21-touchgood`.**  The *specific commit* that
builds the running kernel is the known-good snapshot commit
`c2a38a5db829` ("Input: apple_z2: Do not treat an idle D21 controller as a
dead one"), not the tree's current HEAD.

Evidence chain, each link independently checked:

| # | fact | source |
|---|---|---|
| 1 | The running kernel is `7.3.0-rc1-orchard-apple-16k`, built `2026-10-22T00:00:00Z` by `orchard@builder` | phone `/proc/version`, `dmesg` line 2 |
| 2 | `Known Good State/README.md` names that exact release as the working kernel, and pins the kernel branch to `c2a38a5db829` | `Known Good State/README.md` §"Exact commits" |
| 3 | The known-good rebuild recipe is `git worktree add --detach …/trees/d21-touchgood c2a38a5db829` — i.e. **the known-good payload was built from the `d21-touchgood` tree at that commit** | `Known Good State/README.md` §"Rebuild from this snapshot" |
| 4 | `c2a38a5db829` exists in `d21-touchgood` and is the last touch commit | `git -C …/d21-touchgood log -1 c2a38a5db829` |
| 5 | The tree's HEAD is `b7c9bc0c791b`, exactly two commits ahead of the known-good commit — the two G10P driver commits `bbdbdb19353e` and `b7c9bc0c791b` | `git log c2a38a5d..b7c9bc0c` |
| 6 | The tree's platform defconfig is `arch/arm64/configs/orchard_apple16k_defconfig`, and it contains `CONFIG_DRM_POWERVR_APPLE=y` — which the *running* kernel's `/proc/config.gz` also shows | tree defconfig vs. phone `/proc/config.gz` |

The release string is not a tree artefact: the orchard build system passes
`--localversion -orchard-<platform>` (`src/orchard/kernel.py:314`), and the
D21's platform is `apple-16k` (`devices/d21/device.toml`:
`platform = "apple-16k"`).  So **a rebuild of any tree produces the same
release string `7.3.0-rc1-orchard-apple-16k`** — see §5 for why that matters.

### What is *not* the booting image

`/boot` on the phone holds two systemd-boot slots,
`omarchy-a-d21-79b01d66` and `omarchy-a-d21-fd04fe70`, each with a
`7.3.0-rc1-g2bde906a7ae3/` directory.  Commit `2bde906a7ae3` exists in
**`hoolock/linux`**, not in any `d21-*` tree.  Those kernels carry a
LOCALVERSION_AUTO style release (`-g<hash>`) and a different config
(`CONFIG_LOCALVERSION_AUTO` is *not* set in the running kernel), and the
running kernel's release string does not match them.

**They are not what the phone is running.**  The phone boots the RAM
payload (`orchard run` → Pongo → m1n1 → payload), not the `/boot` slots.
The `/boot` slots are the older "installed Omarchy A" path and can be
ignored for GPU work — but they are also a trap: a kernel from that path
would be a *different* tree with different drivers.

### The build/boot commands (for the record)

```sh
# build (host, RAM payload):
cd /home/doug/orchard
./bin/orchard build /home/doug/omarchy-iphone/d21-desktop-boot \
    --device d21 \
    --kernel-tree /home/doug/projects/OrchardLinux/trees/d21-touchgood \
    --pongo "/home/doug/Known Good State/loaders/Pongo.bin"

# boot the built payload (this is the action that needs a "go";
# --no-build reuses out/apple-16k/linux.bin and does not touch the tree):
./bin/orchard run /home/doug/omarchy-iphone/d21-desktop-boot \
    --device d21 --no-build \
    --pongo "/home/doug/Known Good State/loaders/Pongo.bin" -y

# recovery boot — the *frozen* known-good payload.  Copy it into the
# build's out/ first: --no-build reads that file, NOT payload/linux.bin.
cp "/home/doug/Known Good State/payload/linux.bin" \
   /home/doug/omarchy-iphone/d21-desktop-boot/out/apple-16k/linux.bin
sha256sum /home/doug/omarchy-iphone/d21-desktop-boot/out/apple-16k/linux.bin
# must be f44886c1dd7c94de475b1dbfa8a5a9636259172cd37a8df4c5e4a1fe30fb5b53
./bin/orchard run /home/doug/omarchy-iphone/d21-desktop-boot \
    --device d21 --no-build \
    --pongo "/home/doug/Known Good State/loaders/Pongo.bin" -y
```

**`--no-build` pins the build output, not `payload/linux.bin`.**  While
`out/apple-16k/linux.bin` was a copy of the known-good image the two were the
same; the 2026-11-09 Phase-2.1 build replaced it
(sha256 `1f790b08…`, copy kept at `/tmp/opencode/phase2.1-linux.bin`), so the
copy step above is now mandatory.  The frozen payload in `Known Good State/`
was not touched.  Also, a `--kernel-tree …` boot **rebuilds** from whatever
branch is checked out there, so it is not a recovery path once the tree
carries GPU work.

---

## 2. `ps_gfx` — verified (the caveat from the handoff, resolved)

The handoff asked to verify the `ps_gfx` node before trusting
`0x23280338`.  Verified in `d21-touchgood`
(`arch/arm64/boot/dts/apple/t8015-pmgr.dtsi:696`):

```dts
ps_gfx: power-controller@80338 {
        compatible = "apple,t8015-pmgr-pwrstate", "apple,pmgr-pwrstate";
        reg = <0x80338 4>;
        #power-domain-cells = <0>;
        #reset-cells = <0>;
        label = "gfx";
};
```

* The `reg` is **PMGR-relative** (`0x80338`), not absolute.  The PMGR node
  is `power-management@232000000`, so the absolute address is
  `0x232000000 + 0x80338 = 0x23280338`.  The handoff's number is right.
* The driver is `drivers/pmdomain/apple/pmgr-pwrstate.c`, built **in**
  (`CONFIG_APPLE_PMGR_PWRSTATE=y` in the running kernel).
* On the running phone the domain exists and is **off and unused**:
  `/sys/kernel/debug/pm_genpd/gfx/current_state` → `off-0`, and
  `/sys/kernel/debug/pm_genpd/gfx/devices` is empty.

What "powering it on" actually does (`pmgr-pwrstate.c`):
`apple_pmgr_ps_power_on()` → `apple_pmgr_ps_set(PS_ACTIVE = 0xf)` writes
`PS_TARGET = 0xf` (`GENMASK(3,0)`) into the PMGR register at `0x80338`,
then polls `PS_ACTUAL` (`GENMASK(7,4)`) until it reads `0xf`, with a
**100 ms** timeout (`APPLE_PMGR_PS_SET_TIMEOUT`).  With
`apple,manual-pm` absent, `APPLE_PMGR_AUTO_ENABLE` (bit 28) is also set, so
the domain powers itself back off when the last device referencing it goes
away.

**Phase 2.1 therefore needs no new power-domain code at all** — it needs a
*consumer* device whose DT node names `power-domains = <&ps_gfx>`.

---

## 3. TRAP 1 — `apple,t8010-gpu` in the PowerVR match table

`drivers/gpu/drm/imagination/pvr_drv.c` (both at the running kernel's
`c2a38a5d` and at the tree's HEAD):

```c
static const struct of_device_id dt_match[] = {
#if IS_ENABLED(CONFIG_DRM_POWERVR_APPLE)
        {
                /* only match: the t8015-gpu DT node ships with the D21 GPU bring-up */
                .compatible = "apple,t8010-gpu",
                .data = &pvr_device_data_apple,
        },
#endif
```

The comment says *t8015*, the string says *t8010*.  Two consequences:

1. **A D21 DT node with `compatible = "apple,t8010-gpu"` binds the full
   PowerVR/Apple driver** — the one that maps the firmware windows, boots
   the GFX firmware and talks RTKit.  That is exactly what Stage 2.2 must
   *earn*, not something that may happen by accident during Phase 2.1.
2. The match is compiled in whenever `CONFIG_DRM_POWERVR_APPLE=y`, and it
   is `y` in the running kernel (`/proc/config.gz`:
   `CONFIG_DRM_POWERVR=m`, `CONFIG_DRM_POWERVR_APPLE=y`,
   `CONFIG_APPLE_RTKIT=y`).

**TRAP 1b — the payload cold-plugs every device.**  The RAM payload's
`init` (`Known Good State/payload/init`) does:

```sh
echo /usr/libexec/module-hotplug > /proc/sys/kernel/hotplug
coldplug() {
    for alias in /sys/bus/*/devices/*/modalias; do
        [ -r "$alias" ] && modprobe -qb "$(cat "$alias")" 2>/dev/null || true
    done
}
coldplug
```

So a DT node whose compatible matches a module is **modprobed
automatically at boot**, with no chance to review the state first.  The
`powervr` module is not loaded today (the D21 DT has no GPU node at all);
`lsmod` shows only `apple_z2`, `nvme_apple`, `nvme_core`.

**Rule for Phase 2.1:** the new node must use a compatible that **no**
in-tree driver matches — `"apple,t8015-gpu"` is free (the KB already notes
that the `apple,t8015-gpu` match "is deliberately not added"), and it is
what the Stage-2 sketch uses.  Our Phase-2.1 driver should bind a
*different*, own compatible (or the same one, but only one driver may own
it — see §6).

---

## 4. TRAP 2 — the mailbox node writes registers at probe

The A10 GFX mailbox is described by the in-tree
`drivers/soc/apple/mailbox.c`, variant `apple_mbox_a7iop_hw`, matched by
`"apple,t8010-a7iop-mailbox"`:

| register | offset from the mailbox base |
|---|---|
| IRQ mask set | `+0x00` |
| IRQ mask clear | `+0x04` |
| A2I control / send | `+0x08` / `+0x10` |
| I2A control / recv | `+0x20` / `+0x38` |

and `apple_mbox_a7iop_probe()` writes the mask registers **at probe**
(`writel_relaxed(irq_mask_all, regs + irq_mask_set)`).

The mailbox base is therefore *inside* the GFX IOP window:

| | IOP window | mailbox base |
|---|---|---|
| A10 (T8010) | `0x01d20000` size `0x4000` | `0x01d24000` = IOP `+0x4000` |
| A11 (T8015) | `0x04d20000` size `0x20000` | **`0x04d24000` = IOP `+0x4000`** |

`0x04d24000` is confirmed from three independent sources:
the A10's identical relative layout (`mbox@201d24000` in `t8010.dtsi`);
the G10P kext RE (`A11-GPU-FINDINGS.md` §9f: the MAILBOX_SET/CLR pairs are
written at `IOP+0x4000` and `IOP+0xc00`); and the ADT's GFX interrupt set
`[260,259,262,261]`, which is the same four-IRQ A7IOP mailbox pattern the
driver expects.

**Consequence for Phase 2.1:** do **not** add the mailbox node in 2.1.  The
mailbox driver writes to the IOP window at probe; 2.1 must touch no GPU
register at all.  The mailbox node belongs to 2.2.

Also note the A11 mailbox window (`0x04d24000`, size `0x1000`) lies
*inside* the A11 IOP window (`0x04d20000` … `0x04d40000`), whereas on the
A10 the two are adjacent.  Two nodes mapping the same physical pages is
legal in DT and harmless if both use `devm_platform_ioremap_resource()`
(device memory, uncached), but it is a difference from the A10 worth
remembering when the IOP driver maps its window.

---

## 5. TRAP 3 — a boot rewrites the phone's module tree

The payload's `init` copies the running release's module tree into the
**installed root on NVMe**:

```sh
release=$(uname -r)
mkdir -p "/newroot/usr/lib/modules/$release"
cp -a "/lib/modules/$release/." "/newroot/usr/lib/modules/$release/"
```

Because the rebuild keeps the same release string
(`7.3.0-rc1-orchard-apple-16k`, §1), a Phase-2.1 boot **overwrites** the
module tree of that release on the phone's storage rather than adding a new
directory.  Two consequences:

* The phone's storage *is* modified by a Phase-2.1 boot (one directory of
  modules).  That is inherent to the known-good payload's design, not to
  anything the GPU work does — but it must be disclosed before the go, and
  it means the phone's module tree is no longer the pristine known-good
  copy after a GPU-boot experiment.
* Recovery is unaffected: the *kernel image* lives in the RAM payload
  (`--no-build` pins the sha256), not on NVMe.  The module tree on NVMe is
  only used by the installed system's own driver loading.

The payload also copies the touch firmware container into the installed root
if it is missing — it is already there, so no change.

---

## 6. ADT ground truth for the two new nodes

From the live ADT capture (`/home/doug/omarchy-iphone/adt/adt.txt`):

`sgx` (the RGX core):

```
compatible = [gpu,t8015]      device_type = sgx
reg = 0x04000000 size 0x100000   (RGX)
      0x04D00000 size 0x20000    (Fender)
interrupts = [255,256,257,258,263]   interrupt-parent = 28 (AIC)
clock-gates = [148,123]   power-gates = [148,123]   clock-ids = [265]
```

`gfx-kf` (the GFX coprocessor):

```
compatible = [iop-gfx,t8015]   device_type = gfx-kf   role = GFX
reg = 0x04D20000 size 0x20000   (IOP / AKF window)
      0x04D00000 size 0x20000   (Fender, shared with sgx)
interrupts = [260,259,262,261]   interrupt-parent = 28 (AIC)
clock-gates = [149]   power-gates = [149]   clock-ids = [269]
iop-version = 1
```

The Stage-2 sketch's addresses and sizes match the ADT exactly
(RGX `0x04000000/0x100000`, Fender `0x04D00000/0x20000`,
IOP `0x04D20000/0x20000`).  The mailbox base `0x04D24000` is the only
addition (§4).

---

## 7. Summary of what changed in the KB

* the "which tree" question is **closed** (§1);
* `ps_gfx` is **verified** (§2) — `reg` is PMGR-relative `0x80338`,
  absolute `0x23280338`, driver built-in, domain currently `off-0`;
* three traps are recorded: the `apple,t8010-gpu` match + payload coldplug
  (§3), the mailbox writing registers at probe (§4), and the module-tree
  write on every boot (§5);
* the mailbox base is no longer a GUESS: `0x04D24000` (§4).

**Nothing else moved.**  The G10P ISA work, the layout work and the
firmware inventory are untouched by this document.
