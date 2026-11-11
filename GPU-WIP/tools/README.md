# GPU-WIP tools

Pure-Python analysis scripts used for the G10P research. They read local files
and print findings; **none of them contains or ships Apple data**, and none of
them writes to the device.

Every path is an environment-variable override with the original local layout
as the default, so the scripts work on another machine by exporting the
variable instead of editing the file.

| script | what it answers | variables (default = our layout) |
|---|---|---|
| `g10p_words.py` | dump the AGX instruction words of a corpus object, section-aware (the corpus files are Mach-O objects; the words live in `__TEXT,__text`) | `GPU_WIP_CORPUS` (`…/Known Good State/firmware/GPU/ds-g10p`) |
| `g10p_census.py` | census of low-12-bit opcode values over all 492 190 corpus words, annotated with Mesa's opcode names | `GPU_WIP_CORPUS`, `GPU_WIP_REF` (vendored Mesa `agx_opcodes.py`) |
| `agx_table_scan.py` | scan an image inside a dyld subcache for Mesa-shaped `(exact, mask, len_short, len_long)` tables | `GPU_WIP_CACHE` (dyld subcache `.17`) |
| `agxcore_xref.py` | Mach-O/segment/section map of `AGXCompilerCore` + the GPU target-arch strings (`g10p-b0`, …) | `GPU_WIP_CACHE` |
| `kc_fwscan.py` | locate firmware payloads in the iOS kernelcache and check them against a local copy | `GPU_WIP_KC`, `GPU_WIP_SMARTIO` |
| `kc_tags.py` | enumerate the IMG4-ish firmware tags in the kernelcache (`AppleT8015SmartIO`, `AppleT8015PMPFirmware`, …) | `GPU_WIP_KC` |
| `kc_pmp.py` | extract/validate the PMP firmware region and find embedded firmware Mach-Os | `GPU_WIP_KC` |
| `kc_pmp_extract.py` | write `pmp-t8015.bin` (the `AppleT8015PMPFirmware` payload, 127 696 bytes) out of a D21/D22 kernelcache | `GPU_WIP_KC` |
| `kmsg-host.py` | collect the phone's kernel log over the USB network (`/proc/kmsg` → `172.16.42.2:6666`), surviving a reset | port, output file |
| `kc_macho.py` | section-level compare of the local const blob against the kernelcache | `GPU_WIP_KC`, `GPU_WIP_LOCAL` |
| `g10p_solve.py` | **WIP** constraint solver for the A11 length table: frames every corpus object, treating Mesa's public table as the prior and solving the lengths of the A11-only opcodes jointly across the corpus | `GPU_WIP_CORPUS`, `GPU_WIP_REF` |
| `g10p_lengths.py` | **the A11 length table, solved and validated.** Uses Dougall Johnson's `applegpu` descriptor table as the opcode dictionary, measures the 6-byte quantum from the local repetition period, tiles every corpus object with an exact forward-reachability DP, applies a minimal-deviation repair, cross-validates (solve on half / test on the other half), checks the 64-byte function alignment, and emits the table as JSON | `GPU_WIP_CORPUS`, `GPU_WIP_APPLEGPU` (directory holding `applegpu.py`) |
| `g10p_fields.py` | **the A11 field layout.** Frames the corpus with the solved length table, then for every field `applegpu` declares, reports whether A11 uses it at the same position, folds it into the opcode, ignores it, or has no room for it.  `--summary` = the global table, `--op NAME` = one opcode, `--bits` = a per-bit dump | `GPU_WIP_CORPUS`, `GPU_WIP_APPLEGPU` |
| `g10p_constrain.py` | **the branch-constrained solve.** Frames the corpus, then iterates: every branch whose target is not an instruction boundary becomes a length constraint on the opcode that covers it; the constraints are applied (only to the A11-only opcodes) and the corpus is re-framed until stable.  Reports the branch-target hit rate and the branch-offset modulus histogram, and emits `A11-GPU-G10P-LENGTHS.json` | `GPU_WIP_CORPUS`, `GPU_WIP_APPLEGPU` |
| `g10p_branches.py` | **the standalone branch-target validator** for any candidate framing: does each branch's target land on an instruction boundary?  Use it to check a framing that was derived some other way | `GPU_WIP_CORPUS`, `GPU_WIP_APPLEGPU` |
| `g10p_dpcheck.py` | **the exact-DP validator.** Uses forward + backward reachability instead of the greedy walk, so "the object tiles" is a proof.  Compares candidate framings head-to-head on framing-independent metrics: how many `jmp_exec_none` / `jmp_exec_any` instructions the framing identifies, and how often their targets land on a boundary | `GPU_WIP_CORPUS`, `GPU_WIP_APPLEGPU` |

`g10p_constrain.py` is the current instrument; it supersedes `g10p_solve.py`,
which framed only a handful of the 94 objects because the A11 dialect changes
the *length* of far more Mesa opcodes than the two known at the time (`imad`,
`texture_load`).  The "same-source differential" that was supposed to replace
it turned out to be **dead** — the 32-instance groups are not
same-code-different-constants — so the solver was rebuilt around an exact DP
plus a cross-validated minimal-deviation repair (`g10p_lengths.py`), and
finally around branch-target constraints (`g10p_constrain.py`), which are the
strongest of the three because they are semantic rather than structural.

### The `applegpu` reference

`g10p_lengths.py` needs Dougall Johnson's AGX descriptor table
(`github.com/dougallj/applegpu`, BSD 3-Clause), which is **not** committed
here — it is third-party code and stays a local reference like Mesa's
`agx_opcodes.py`.  Fetch it once and point the tool at it:

```sh
git clone --depth 1 https://github.com/dougallj/applegpu.git
export GPU_WIP_APPLEGPU=/path/to/applegpu
```

The table is 161 descriptors / 81 distinct low-16 `(mask, bits)` signatures,
each with an explicit `(short, long)` byte-size pair and a length-bit
position — i.e. it encodes the *framing rule*, not just the opcode bits.  Its
`jmp_exec_none` = `0xc020` is exactly the value measured independently in the
G10P corpus, which is why it is the right dictionary for A11.

Typical use:

```sh
export GPU_WIP_CORPUS=/path/to/ds-g10p
export GPU_WIP_REF=/path/to/reference-agx-isa      # needs Mesa's agx_opcodes.py
export GPU_WIP_APPLEGPU=/path/to/applegpu          # needs applegpu.py
python3 tools/g10p_census.py
python3 tools/g10p_lengths.py --json lengths.json
python3 tools/g10p_fields.py --summary
python3 tools/g10p_constrain.py --iters 12
python3 tools/g10p_branches.py
```

The scripts expect the artefacts they read to exist locally (corpus objects,
the iOS kernelcache, the extracted dyld cache). None of those are committed to
this repository — see the artefact policy in `../README.md`.
