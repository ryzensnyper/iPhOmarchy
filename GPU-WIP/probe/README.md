# G10P probe kit (Stage 1 / Stage 2)

Driver + DT binding + install/rollback scripts for the first hardware probe of
the A11 / T8015 G10P GPU path, as planned in
[`kb/A11-GPU-G10P-PROBE.md`](../kb/A11-GPU-G10P-PROBE.md).

**Status: DRAFT, not built, not installed, not run.**

The only offset in the driver's boot path that is verified against the G10P
kext (see the probe KB, §4) is the Fender `+0x1000` power-request register.
Everything else is marked `GUESS` — same-silicon transplants from the A10 and
from the working t8015 PMP driver — and each one is listed in `STATUS.md`.
Before writing anything to the device:

* every `GUESS` must be either verified on the bench (Stage 1, read-only), or
  resolved by one more RE pass on the kext, or marked impossible-to-avoid and
  accepted consciously;
* the firmware must be copied and checksummed;
* rollback must be rehearsed: `./rollback.sh` must restore the phone to
  simplefb-only and the display must come up afterwards.

Nothing here was produced by writing to the device.
