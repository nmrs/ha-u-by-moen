#!/bin/bash
# E-test: does a local temp write while off get armed (applied at main-on),
# or is main-on's 104F purely device memory? 96F is distinctive (no preset is 96).
cd "$(dirname "$0")"
set -e -x
../.venv/bin/python hap_write.py --temp 96        # while off — hidden from readback?
sleep 12
../.venv/bin/python hap_write.py --main on        # target 96 (armed) or 104 (memory)?
sleep 10
../.venv/bin/python hap_write.py --main off