# JADE kernel bundle — c2a38a5 + D21 touch (for build / forward-port)

This folder is the **buildable source** behind the JADE Known Good State
(described in `../README.md`). It is text-only: patches and docs, no blobs,
no `.ko`, no firmware or device-private calibration data.

## Why this exists

The `../README.md` records *that* the c2a38a5 kernel ("7.3.0-rc1-orchard-apple-
16k", commit `c2a38a5db829d9cd83dde69c1e0d22566a1e119d`) makes D21 touch
reliable. This folder gives @henricklee / OrchardLinux the pieces to **build
that kernel** and to fold the D21 touch work into the shared `apple_z2` driver.

## Contents

- `0021-Input-apple_z2-Use-the-iPhOmarchy-D21-touch-driver.patch`
  The orchard kernel patch that produces the JADE D21 driver. This is the
  authoritative source: it contains the full D21 touch driver **including**
  the idle fix — the `d21_last_irq` edge-liveness field and the `quiet_ms`
  "idle is not dead" watchdog. It is numbered 0021 in
  `orchard/kernel/patches/devices/t8015/`.

- `0009-c2a38a5-idle-fix.patch`
  The single upstream-style commit `c2a38a5` "Input: apple_z2: Do not treat
  an idle D21 controller as a dead one" (63 lines), for reference. Its content
  is already folded into patch 0021 above; it is included so the specific fix
  that makes touch reliable can be read in isolation. The "patch 0009" label
  in `../README.md` refers to this fix.

- `d21-touch.md`
  Full local bring-up/touch notes from `orchard/docs/bring-up/` (50 KB): the
  root-cause analysis, poke sweeps, roll characterization, and all evidence.

- `RUNBOOK.md`
  The D21 operational runbook from `orchard/docs/bring-up/d21-current-setup/`:
  boot procedure, SSH keys, verification commands, known-good hashes.

## Relationship to upstream (context for the forward-port)

- The JADE driver is built from the orchard **patch layer** (authoritative),
  not from a branch of `OrchardLinux/linux`. Orchard's `main` is generated
  from these patches via `tools/kernel-tree/regenerate`.
- As of 2026-11-12, current `OrchardLinux/linux` main already contains
  Eduardo Martins' T8015 SPI + touch-clock support; those PRs are duplicates
  and should not be re-sent. The genuine D21 gap is the touch driver itself
  (patch 0021) plus the D21 board DTS.
- Per @henricklee: D21 should be forward-ported into the **shared** `apple_z2`
  driver as match data + a few flags (no D21-only driver copy), based on
  Orchard's current shared driver, using iPhone 7 (D11/D111) as the model.
  A separate design proposal is in the local orchard repo
  (`docs/bring-up/d21-apple-z2-matchdata-proposal.md`), not committed here.

## Rebuild the JADE kernel

```sh
cd /home/doug/orchard
./bin/orchard build /home/doug/omarchy-iphone/d21-usb-boot-kg --device d21 \
  --kernel-tree /home/doug/projects/OrchardLinux/trees/d21-c2a38a5 \
  --pongo "/home/doug/Known Good State/loaders/Pongo.bin"
```

Then boot with the phone in PongoOS:

```sh
./bin/orchard run /home/doug/omarchy-iphone/d21-usb-boot-kg --device d21 --no-build -y
```

Pinned hashes are in `../README.md`. Assisted-by: LLM
