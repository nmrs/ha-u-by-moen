#!/bin/bash
# Scenario: turn on a valve (outlet 2) while shower is OFF — cloud vs local behavior.
cd "$(dirname "$0")"
set -e -x
../.venv/bin/python cloud_command.py status            # baseline: off
sleep 5
../.venv/bin/python cloud_command.py outlet 2 on      # raw outlets_set while off — does water start?
../.venv/bin/python hap_write.py --read               # local view after cloud outlet-on
sleep 10
../.venv/bin/python cloud_command.py status           # cloud view after
sleep 5
../.venv/bin/python cloud_command.py off              # cleanup in case water started
sleep 5
../.venv/bin/python cloud_command.py status           # final