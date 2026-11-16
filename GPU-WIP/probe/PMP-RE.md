# PMP firmware RE notes (D21, pmp-t8015.bin)

## Tooling
`/tmp/opencode/recdis.c` (libcapstone): linear sweep in Thumb + ARM, absolute
`bl` targets (ARM PC+8 / Thumb PC+4), `callers`/`callees`/`xref`/`lits`/`dump`/
`check`. Usage: `./recdis pmp-t8015.bin dump 0xADDR 0xADDR`.

**The old `pmp-full-dis.txt` is not usable**: its address->file mapping drifts
(+6 bytes at 0x01011xxx, +14 at 0x01002xxx), so it was made from a different
copy. Every claim below was re-derived from `recdis` on the real image
(md5 9737473b4846681dc3f292b62ba6df03, 0x1EE90 bytes).

## Image
- Vector table at 0: `ea000018` (b 0x68) then **seven `feff ffea` (`b .`)
  handlers**. Only reset is live => **the firmware polls; there are no
  interrupt handlers.**
- Code from 0x68 in ARM mode (mrs/mcr p15 MMU setup), Thumb-2 after.
- Linked at 0x01000000. AKF remap (`IOP 0 -> AP 0x232500000`) makes firmware
  VA X == AP `sram + (X - 0x01000000)`; the device table at 0x01014330 is
  what we read back at `sram+0x14330`. Confirmed.

## Windows (DT pmp@232300000)
    akf     0x232300000  0x08000
    control 0x232400000  0x10000
    sram    0x232500000  0x20000   (image + BSS; image ends 0x0101EE90)
    mbox    0x232308000  0x04000   (apple,t8015-asc-mailbox)

T8015 mailbox (drivers/soc/apple/mailbox.c): control 0x108/0x10c; a2i send
0x800/0x808; a2i recv 0x810/0x818; i2a send 0x820/0x828; i2a recv
0x830/0x838; FULL=BIT(16) EMPTY=BIT(17). No literal in the firmware points
into 0x232x_xxxx, so the IOP reaches MMIO through a pointer held in an
object/global.

## THE MESSAGE DISPATCHER: 0x01003734
Installed as an ops method at object+0x40 by the constructor at 0x010019a8
(`ldr r0,[pc,#0x258]` == 0x01003735, stored via `strd r1,r0,[r4,#0x3c]`).

    ldrd  sl, r1, [r0]        ; sl = msg[31:0], r1 = msg[63:32]
    ubfx  r6, r1, #0xc, #8    ; r6 = msg[51:44]
    cmp   r6, #0x10
    bhi   0x01003bc6          ; > 0x10  -> SILENT DROP (no reply)
    ubfx  fp, r1, #8, #4      ; fp = msg[43:40]
    lsr   r4, sl, #0x10       ; r4 = msg[31:16]
    uxth  r3, sl              ; r3 = msg[15:0]
    tbh   [pc, r6, lsl #1]    ; table at 0x0100378a

Key = (msg[51:48] << 4) | msg[47:44].  Table (17 entries):

    key 0x00 -> 0x010037f8     key 0x08 -> 0x010037ac
    key 0x01 -> 0x01003bc6     key 0x09 -> 0x01003bc6
    key 0x02 -> 0x01003808     key 0x0a -> 0x01003934
    key 0x03 -> 0x01003bc6     key 0x0b -> 0x01003bc6
    key 0x04 -> 0x0100382a     key 0x0c -> 0x01003972
    key 0x05 -> 0x01003bc6     key 0x0d -> 0x01003bc6
    key 0x06 -> 0x010038a0     key 0x0e -> 0x010037ac
    key 0x07 -> 0x01003bc6     key 0x0f -> 0x01003a76
                               key 0x10 -> 0x01003ada

So the implemented keys are 00,02,04,06,08,0a,0c,0e,0f,10. Everything else,
explicitly including 0x11 and every key >= 0x11, exits at 0x01003bc6 with no
reply and no side effect.

### Field layout as used by the handlers
    msg[51:48] class        (dispatch high nibble)
    msg[47:44] command      (dispatch low nibble)
    msg[43:40] fp  = index into a table of 48-byte (case 4) or 32-byte
                    (cases 6,15) records; bounds-checked against
                    [obj+0x18] and a byte at [record+4]
    msg[31:16] r4  = value / 16-bit handle, looked up via 0x0100432c in
                    cases 10 and 12 (0xff == not found)
    msg[15:0]  r3  = size, case 12 requires >= 0x20

Case 4 (0x0100382a) and case 6 (0x010038a0) have the same shape: pick a
record by fp (`r3 + fp*48`), read a byte, compare with r4, store a byte back
at `[record + slot*4]`; case 6 additionally refreshes `[obj+0x120]`. That is
set/read-of-per-device-state, i.e. the PM state commands.

## Why cmd 4 / cmd 6 were always silently dropped
Apple's packet (verified again at 0xfffffff00610b868 in the kext):

    and w8,w20,#0xf ; lsl x23,x8,#0x30     -> cmd at msg[51:48]
    and w8,w25,#0x3f; bfi x23,x8,#0x2a,#6  -> arg2 at msg[47:42]
    lsr x8,x0,#0xc  ; bfi x23,x8,#0x10,#0x1a -> pfn at msg[41:16]
    orr x23,x23,#0x10000000000000          -> bit 52

With that framing, key = (cmd<<4) | arg2[5:2]:
  cmd 0 -> 0x00..0x0f (sub-case by arg2>>2), cmd 1 -> 0x10..0x1f,
  **cmd 4 -> 0x40, cmd 6 -> 0x60  => > 0x10 => instant silent drop.**
That explains #139-#146 uniformly: no ack, no side effects, ~661 ms window
expiry, regardless of endpoint tag, record contents, PFN, or state value.

Conversely our two packets that DID have visible effects map exactly to
implemented keys:
  memory-init reply `bit52|32<<56|dma`  -> key 0x10 -> case 0x01003ada
  (bit52 sets class=1; msg[51:48]=0, msg[47:44]=0)

## Open question / next test
If the firmware keys the command at msg[47:44] (dispatch low nibble) and
class at msg[51:48], then the wire packets that reach cases 4 and 6 are

    hi = (0<<16) | (cmd<<12) | (devidx<<8)        cmd = 4 or 6
    lo = (value<<16) | size                       value = msg[31:16]

i.e. `4<<44` / `6<<44`, NOT `4<<48` / `6<<48` as Apple's kext does. Either
the PMP firmware predates that kext layout, or Apple's cmd4/6 are consumed by
a different handler. One boot with keys 0x04 and 0x06 (devidx 0, value 0,
size 0) discriminates: if key 0x04 produces any ack or state change, the
nibble layout is right and the whole PM path opens.
