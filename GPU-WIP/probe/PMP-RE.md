# PMP firmware RE notes (D21, pmp-t8015.bin)

## Image
- 0x1EE90 bytes. File 0x00: ARM vector table (`ea000018` -> b 0x68),
  0x20 "uuid" + 16-byte UUID, 0x40-0x5F header, pointers 0x01012974
  and 0x01017308. Code starts at 0x68 in **ARM** mode (mrs/mcr p15 MMU
  setup), Thumb-2 thereafter.
- Linked at **0x01000000**. The AKF remap in the kernel driver
  (`IOP 0 -> AP 0x232500000`, size 0x20000) makes firmware VA X equal to
  AP `sram + (X - 0x01000000)`; the device table the firmware builds at
  VA 0x01014330 is exactly what we read back from `sram + 0x14330`.

## Windows (from DT / pmp@232300000)
    akf     0x232300000  0x08000
    control 0x232400000  0x10000
    sram    0x232500000  0x20000   (firmware image + BSS)
    mbox    0x232308000  0x04000   (apple,t8015-asc-mailbox)

T8015 mailbox register map (drivers/soc/apple/mailbox.c):
    control    0x108 / 0x10c        FULL=BIT(16) EMPTY=BIT(17)
    A2I send   0x800 / 0x808
    A2I recv   0x810 / 0x818
    I2A send   0x820 / 0x828
    I2A recv   0x830 / 0x838

**No literal anywhere in the firmware points at 0x232x_xxxx**, and none
of the mailbox offsets appear as a base+offset literal. The IOP therefore
reaches the mailbox through a remap window whose base is loaded from a
global, not from a constant. Searches by constant are a dead end; the RX
path has to be found through the call graph.

## It is not bare metal
The image contains a small object/registry framework: 16-bit handles
indexed as `array[handle >> 16]` then `<< 2`, `blx` vtable dispatch,
property getters called with `r1 = 10` (selector) and `r2 = index |
0x20000`. Message handling is layered behind that, which is why looking
for a nibble switch (`hi & 0xf0` / `hi & 0x0f`) found nothing.

## Concrete anchors found
- `0x01014000` is loaded once, at `0x0100d1e4`, inside a routine that
  builds page-granular descriptors (4096, cap 0x2000000, mask 0xC0000000).
  Our device table at +0x330 lives inside that region.
- `0x010024a6..0x010024ac`: `movs r0, #32` (endpoint 32),
  `mov.w r3, #131072` (mailbox EMPTY/FULL bit 17), then a call into a
  normal-prologue function -- the best candidate for the message **send**
  wrapper.
- Globals used for state live at 0x01016C00+ (`movw/movt #0x0101,#0x6C00`).

## Tooling limit
Current tooling is a line-oriented capstone dump with relative `bl`
immediates, which is too imprecise for a call graph (targets land
mid-function or in padding depending on how the immediate is
interpreted). Next step should be a small recursive disassembler on top
of libcapstone that records absolute `bl` targets per encoding
(ARM: PC+8, Thumb: PC+4), builds a call graph and xref lists, and then
walks back from the mailbox globals to the RX dispatcher.
