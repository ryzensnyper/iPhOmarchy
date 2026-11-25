#!/usr/bin/env python3
"""Write pin-check and pin-pam from orchard's install_device.py (PIN_CHECK, PIN_PAM).

Usage: extract-pin-files.py PATH/TO/install_device.py OUTDIR
"""
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location('install_device', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
out = pathlib.Path(sys.argv[2])
(out / 'pin-check').write_text(module.PIN_CHECK)
(out / 'pin-pam').write_text(module.PIN_PAM)
