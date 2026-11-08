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
| `kc_macho.py` | section-level compare of the local const blob against the kernelcache | `GPU_WIP_KC`, `GPU_WIP_LOCAL` |

Typical use:

```sh
export GPU_WIP_CORPUS=/path/to/ds-g10p
export GPU_WIP_REF=/path/to/reference-agx-isa      # needs Mesa's agx_opcodes.py
python3 tools/g10p_census.py
```

The scripts expect the artefacts they read to exist locally (corpus objects,
the iOS kernelcache, the extracted dyld cache). None of those are committed to
this repository — see the artefact policy in `../README.md`.
