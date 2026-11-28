# A11 (G10P) GPU — where we are and what's next

*Updated 2026-11-29.* For how to run the tests, see [RUNBOOK.md](RUNBOOK.md). The detailed
firmware and kext evidence is in
[probe/PMP-PROTOCOL-RECONCILED.md](probe/PMP-PROTOCOL-RECONCILED.md).

## Where we are

**The first null compute job completed on the A11 GPU under Linux (2026-11-29, job 11):**

```
powervr 204000000.gpu: null compute job 1: 0, stamp 1, fault 0
compute submitted 1 done 1 pending 0
```

- **Firmware crash, oops, MMU fault:** none.
- **Unload:** `rmmod` was clean.
- **Battery:** 29.7 °C before and after.
- **Watchdog:** armed for the test and never fired.

What works:

| step | state |
|---|---|
| Fender power, RGX identity | works |
| GFX-KF (RTKit v12) firmware boot from RAM, init accepted | works |
| Driver probe (`powervr`, `apple,t8015-gpu`), runtime PM | works |
| Compute job queued from the host ring into the scheduler pool | works |
| Firmware powers the GPU unit and runs the microsequence (start → wait → finalize → end) | works |
| Stamp written, job retired, context dropped from the queue | **works (new)** |
| A real shader (PDS/USC) writing memory | not started |
| Fragment/geometry (render) jobs | not started |
| Mesa userspace | not started |

### The last two blockers (both fixed with values the iOS kext uses)

1. **Each engine had zero units, so the GPU was never powered.** The
   firmware copies `P+0x1600/+0x1604/+0x1608` into its engine table
   (fw `0x197c0`, `0xcc80`). The power-on loop (fw `0x3a80`) only powers units
   in that mask. The AGXG10P kext writes `(1 << n) - 1` there. We use 1 unit
   per engine, which matches what the A10 needs (commit `8e00d466843a`).
2. **The context state's idle pointer was null.** When a job retires,
   fw `0x65f6` walks the queue's context list and reads `*[ctx+0]`. A null
   pointer crashed the firmware right after the stamp was written. The kext
   sets `+0` to a per-context word, `+4` to a context number and `+8` to 0
   (commit `786063cf4e0d`).

### Kernel series (local branch `gpu/t8015-g10p`, not pushed)

```
786063cf4e0d drm/imagination: Give the G10P context state an idle word
8e00d466843a drm/imagination: Give each G10P engine one unit to power
a8f8fd3391e4 WIP: drm/imagination: Ask the G10P firmware to power the GPU up
d695e5e6b56f drm/imagination: Write G10P compute jobs as the AGXG10P kext does
60d698e5a898 drm/imagination: Give the A11 G10P queues their context lists
de821bf0665a drm/imagination: Give the A11 G10P firmware its TLB generations
2d00a8de3d83 drm/imagination: Use the G10P work-ring entry format
90ef92156ee4 DEBUG: drm/imagination: apple: debugfs null compute job
6e6d617ae9cd drm/imagination: Queue compute jobs on the A11 (T8015)
035ab29bb167 drm/imagination: Give the A11 (T8015) GPU an ID
4d3180815bbd arm64: dts: apple: t8015: Add the GPU
f2374c12a556 drm/imagination: Boot the A11 (T8015) G10P GFX firmware
```

The base is OrchardLinux/linux `6e58c497fa30`. Upstream `main` has moved since
then: it now has A8 compute and render, A7 boot, and the A10 settle-time change.

### Known unknowns

- **The real unit counts.** The kext reads `n0/n1/n2` from its GPU config
  object (`+0x38c/+0x390/+0x394`), and `n0` is also the number of 20-byte unit
  records. They aren't in the ADT. We use 1 for now, which works.
- **Whether the WIP ring-12 power request (`a8f8fd3391e4`) is needed.** iOS
  never sends command `0xe` from the host, so it probably isn't.
- **`ctx+0xc`.** The kext fills it from config (`min(cfg[+0x1900]|[+0x54c],
  cfg[+0x1908])`). We leave it at 0, which marks the context done at once.

## Path forward

In order:

1. **Clean up the null job.**
   - Test without `a8f8fd3391e4` and drop it if the job still passes.
   - Run several jobs back to back, then a module reload followed by another job.
   - Find the real unit counts in the kernelcache.
2. **Squash and send upstream.** Fold the series into reviewable commits, without the
   DEBUG/WIP ones, and rebase on current OrchardLinux/linux `main`. That means
   the shared 8 Plus/8 dtsi and a D211 entry. Then open a PR through the
   ryzensnyper fork, when asked.
3. **Run a real compute shader.** Start from the A10's first working dispatch
   (OrchardLinux/gpu `a10/COMPUTE.md`, run 66): Apple's CDM record, PDS
   program and an empty USC kernel. Point the stream at it and expect a
   completion with no fault. Then try a store-marker kernel that writes a known
   value to memory. The A11 ISA framing (6-byte quantum) and field layout in
   `kb/` are the encoding reference.
4. **Wire job completion to the firmware's IRQ and event ring.** At the moment
   the driver waits on the stamp.
5. **Fragment and geometry jobs, then Mesa** (`src/imagination` with a G10P
   variant), and only after that a desktop.

Rough estimate: the null job is done; a real compute shader is about 30–40 %
of the way; a desktop is about 5–10 %.
