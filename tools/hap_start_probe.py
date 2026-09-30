#!/usr/bin/env python3
"""Rig probe of the proposed start_shower() sequence: clear armed outlets,
arm outlet 1, arm target 100F, main on — all back-to-back on ONE session.

    hap_start_probe.py            # start
    hap_start_probe.py --stop     # main off
"""
import argparse
import asyncio
import sys

from moen_hap import (
    HEATER_TARGET_TEMP_IID,
    MAIN_ACTIVE_IID,
    OUTLET_ACTIVE_IIDS,
    READ_PAIRS,
    fmt_state,
    f_to_c,
    load_env,
    pairing_from_env,
)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stop", action="store_true")
    args = ap.parse_args()
    env = load_env(args.env if hasattr(args, "env") else None)
    pairing = pairing_from_env(env)
    try:
        if args.stop:
            await pairing.put_characteristics([(1, MAIN_ACTIVE_IID, 0)])
            print("main off OK")
            await asyncio.sleep(1)
            print(fmt_state(await pairing.get_characteristics(READ_PAIRS)))
            return
        puts = []
        for pos, iid in OUTLET_ACTIVE_IIDS.items():
            puts.append((1, iid, 1 if pos == 1 else 0))  # clear armed, arm outlet 1
        puts.append((1, HEATER_TARGET_TEMP_IID, f_to_c(100)))  # cloud default target
        puts.append((1, MAIN_ACTIVE_IID, 1))
        t0 = asyncio.get_event_loop().time()
        for i, p in enumerate(puts, 1):
            await pairing.put_characteristics([p])
            t = asyncio.get_event_loop().time()
            print(f"put {i}/6 OK (+{t - t0:.3f}s)")
        await asyncio.sleep(1)
        print(fmt_state(await pairing.get_characteristics(READ_PAIRS)))
    finally:
        try:
            await pairing.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))