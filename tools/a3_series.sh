#!/bin/bash
# A3 rerun: outlet on/off while running via cloud path (A1/A2/A4 already captured).
cd "$(dirname "$0")"
set -e -x
../.venv/bin/python cloud_command.py on            # restart shower (preset 0, outlet 1)
sleep 45
../.venv/bin/python cloud_command.py outlet 2 on   # body sprayers on
sleep 45
../.venv/bin/python cloud_command.py outlet 2 off  # body sprayers off
sleep 45
../.venv/bin/python cloud_command.py off