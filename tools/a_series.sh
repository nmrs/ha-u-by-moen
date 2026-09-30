#!/bin/bash
# A-series: official cloud-path characterization run (A1-A4).
# Cloud commands spaced 45s apart; each command opens a Pusher session,
# sends one control event, listens 20s for reported-state events.
cd "$(dirname "$0")"
set -x
../.venv/bin/python cloud_command.py on            # A1: shower_on preset 0
sleep 45
../.venv/bin/python cloud_command.py temp 104      # A2: temperature_set 104F
sleep 45
../.venv/bin/python cloud_command.py outlet 2 on   # A3a: body sprayers on
sleep 45
../.venv/bin/python cloud_command.py outlet 2 off  # A3b: body sprayers off
sleep 45
../.venv/bin/python cloud_command.py off           # A4: shower_off