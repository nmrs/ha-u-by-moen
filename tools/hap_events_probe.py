#!/usr/bin/env python3
"""Probe: does the TS3304 actually emit HAP event notifications?

1. Prints the perms of the characteristics we care about (looking for "ev").
2. Subscribes and holds a persistent connection, printing pushed events live.

Press physical buttons on the console while this runs to see if events arrive.

    hap_events_probe.py --watch 120
"""
import argparse
import asyncio
import sys
import time
from datetime import datetime

from aiohomekit.exceptions import AccessoryDisconnectedError

from moen_hap import READ_IIDS, OUTLET_ACTIVE_IIDS, MAIN_ACTIVE_IID, HEATER_CURRENT_TEMP_IID, HEATER_TARGET_TEMP_IID, load_env, pairing_from_env

NAMES = {
    MAIN_ACTIVE_IID: "main",
    HEATER_CURRENT_TEMP_IID: "cur_temp",
    HEATER_TARGET_TEMP_IID: "tgt_temp",
    **{iid: f"outlet{pos}" for pos, iid in OUTLET_ACTIVE_IIDS.items()},
}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", type=float, default=120)
    ap.add_argument("--env", help="path to .env")
    args = ap.parse_args()

    env = load_env(args.env)
    pairing = pairing_from_env(env)

    accs = await pairing.list_accessories_and_characteristics()
    perms_by_iid = {}
    for acc in accs:
        acc_aid = acc.get("aid")
        for svc in acc.get("services", []):
            for ch in svc.get("characteristics", []):
                if acc_aid == 1 and ch.get("iid") in NAMES:
                    perms_by_iid[ch["iid"]] = ch.get("perms", [])
    for iid in sorted(perms_by_iid):
        print(f"iid {iid:3d} ({NAMES[iid]:9s}) perms={perms_by_iid[iid]}", flush=True)
    if not all("ev" in perms_by_iid.get(i, []) for i in perms_by_iid):
        print("NOTE: some characteristics lack 'ev' permission", flush=True)

    def on_event(formatted):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"{ts}  EVENT {formatted}", flush=True)

    pairing.listeners.add(on_event)
    pairs = [(1, iid) for iid in READ_IIDS if iid in perms_by_iid and "ev" in perms_by_iid[iid]]
    print(f"subscribing to: {[(NAMES.get(i, i)) for _, i in pairs]}", flush=True)
    try:
        result = await pairing.subscribe(pairs)
        if result is None:
            print("device does NOT support push (supports_subscribe=False)", flush=True)
    except AccessoryDisconnectedError as err:
        print(f"disconnected during subscribe: {err}", flush=True)

    end = time.monotonic() + args.watch
    while time.monotonic() < end:
        await asyncio.sleep(1)
    try:
        await pairing.unsubscribe(pairs)
        await pairing.close()
    except Exception:  # noqa: BLE001
        pass
    print("done", flush=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))