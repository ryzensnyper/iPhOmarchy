#!/bin/bash
# disassemble a Thumb-2 range of the PMP firmware
F=/home/doug/a11-fw/out/pmp-t8015.bin
S=$1; N=$2
python3 - "$F" "$S" "$N" <<'PY'
import subprocess, sys
f, s, n = sys.argv[1], int(sys.argv[2],0), int(sys.argv[3])
d = open(f,'rb').read()[s:s+n]
open('/tmp/opencode/_chunk.bin','wb').write(d)
out = subprocess.run(['llvm-objdump','-D','--triple=thumbv7','--adjust-vma=%#x'%(0x01000000+s),
                      '-b','binary','/tmp/opencode/_chunk.bin'], capture_output=True, text=True)
print(out.stdout)
PY
