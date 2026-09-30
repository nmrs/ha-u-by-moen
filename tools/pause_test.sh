#!/bin/bash
# Pause-state characterization: outlet-off while main on = PAUSED.
# Sample local HAP + cloud REST + Pusher events DURING the pause window.
cd "$(dirname "$0")"
set -e -x
../.venv/bin/python hap_write.py --outlet 2 --state on   # armed
sleep 12
../.venv/bin/python hap_write.py --main on               # water: body sprayers
sleep 15
../.venv/bin/python hap_write.py --outlet 2 --state off  # LAST outlet off -> pause window starts
../.venv/bin/python hap_write.py --read                  # local view during pause
../.venv/bin/python cloud_command.py observe 20          # catch any state_change events
../.venv/bin/python cloud_command.py status              # cloud REST view during pause
sleep 12
../.venv/bin/python hap_write.py --main off              # end pause -> off
sleep 15
../.venv/bin/python cloud_command.py status              # cloud view after off