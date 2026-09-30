#!/bin/bash
# D-series: D1 cloud temp-while-off; D2 fork-style back-to-back double-write (crash test)
# + main-off-with-active-outlet (does local main off clear outlets like cloud?).
cd "$(dirname "$0")"
set -e -x
echo "--- D1: cloud temp while off"
../.venv/bin/python cloud_command.py status        # baseline off
../.venv/bin/python cloud_command.py temp 104      # temperature_set while off
../.venv/bin/python cloud_command.py on            # shower_on — is target 104 or 100?
sleep 20
../.venv/bin/python cloud_command.py off
sleep 10
echo "--- D2: fork-style double write (one process, two puts, zero gap)"
../.venv/bin/python hap_write2.py --outlet 2 --main on   # arm outlet + main on, back-to-back
sleep 20
echo "--- D2b: main off while outlet 2 still active"
../.venv/bin/python hap_write.py --main off              # outlets auto-clear locally?
sleep 5
../.venv/bin/python hap_write.py --read
echo "--- wedge check"
../.venv/bin/python hap_write.py --read