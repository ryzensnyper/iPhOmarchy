# RE helpers

Offline helpers used to reverse the D21 kernelcache, the AGX firmware and the
PMP firmware.  They all run on the host (python3 + llvm-mc/llvm-objdump);
none of them touches the phone.

| tool | what it does |
|---|---|
| `xref.py` | find ADRP(+ADD/LDR) cross-references to a VA in the D21 kernelcache; also maps VAs to file offsets |
| `kcdis2.py` | disassemble a VA range of the kernelcache, resolving ADRP targets and annotating C strings |
| `findconst.py` | search a binary for 32/64-bit constants (register addresses) |
| `a64dis.py` | disassemble a raw arm64 binary |
| `thumbdis.py` | disassemble a raw Thumb-2 binary (llvm-mc; 32-bit Thumb instructions need `pmpdis2.sh`) |
| `pmpdis2.sh` | disassemble a Thumb-2 range of the PMP firmware (wraps the raw binary in an ELF so llvm-objdump accepts it) |
| `adt-mailbox.py` | walk the D21 ADT and print every node whose registers land in an address range |

The kernelcache they read is `/tmp/opencode/d21ap-kernelcache.macho` (a copy of
`/home/doug/a11-fw/kc/20H392__iPhone10,2/kernelcache.release.iPhone10,2_5`).
The PMP firmware is `/home/doug/a11-fw/out/pmp-t8015.bin`; the AGX firmware is
`/home/doug/Known Good State/firmware/GPU/g10p.img`.
