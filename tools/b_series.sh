#!/bin/bash
# B-series: controlled local HAP writes (B2 armed-outlet, B3 last-outlet-off, C1 temp-while-running).
# Each step is exactly ONE put via hap_write.py, which enforces >=10s spacing.
cd "$(dirname "$0")"
set -e -x
../.venv/bin/python hap_write.py --outlet 2 --state on   # armed while off
sleep 12
../.venv/bin/python hap_write.py --main on       # water: armed outlet should apply
sleep 15
../.venv/bin/python hap_write.py --temp 106      # temp while running
sleep 12
../.venv/bin/python hap_write.py --outlet 2 --state off  # last outlet off — apply or need main?
sleep 12
../.venv/bin/python hap_write.py --main off      # stop water