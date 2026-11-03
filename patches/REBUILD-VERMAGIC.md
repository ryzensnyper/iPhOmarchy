# Rebuilding apple_z2.ko for the phone — the vermagic rule (2026-11-04)

The payload kernel's vermagic is baked at payload-build time:
`7.3.0-rc1-g2bde906a7ae3 SMP preempt mod_unload aarch64` (hoolock commit
2bde906a7, the "pres_min default 64" commit — the kernel in
`linux-kit/m1n1-linux-p3-omarchy.bin`).  A module built from a NEWER tree
HEAD fails insmod with "version magic ... should be ..." and the unit goes
failed while the OLD module keeps streaming (the stop ran, the start
didn't).

## The rule

Build from the tree, then rewrite the vermagic's git-hash segment to the
running kernel's.  As of 2026-11-04 the working commit hash segment is
12 hex chars, so the swap is same-length:

    make LLVM=1 ARCH=arm64 drivers/input/touchscreen/apple_z2.ko -j8
    python3 - <<'EOF'
    p = 'drivers/input/touchscreen/apple_z2.ko'
    data = open(p,'rb').read()
    # g<build-head-12> -> g2bde906a7ae3 (same 13-byte length)
    import subprocess
    head = subprocess.run(['git','rev-parse','--short=12','HEAD'],
                          capture_output=True, text=True).stdout.strip()
    old = ('g'+head).encode()
    new = b'g2bde906a7ae3'
    assert len(old) == len(new) and data.count(old) == 1
    open(p,'wb').write(data.replace(old, new))
    EOF

This is safe because everything between the kernel-build commit and our
HEAD is self-contained in apple_z2.c (+901 lines) — the module touches no
kernel struct that changed (proven live: the 2026-11-03/04 sessions ran
newer-code modules with this vermagic through dances #13/#14).

If a future commit makes the hash segment a different LENGTH, shift the
whole `vermagic=...` value left and NUL-pad the tail instead — the kernel
strcmp()s the FULL string including the " SMP preempt mod_unload aarch64"
flags; a NUL-truncated prefix FAILS the check (live-learned: "version
magic '7.3.0-rc1-g2bde906a7ae3' should be '...g2bde906a7ae3 SMP ...'").

Push rules unchanged: `sync; sync` + sha256 verify on both ends.
