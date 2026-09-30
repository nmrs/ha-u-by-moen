#!/usr/bin/env python3
"""Local preset emulation: arm outlet set + target temp + main on, all
back-to-back on ONE session (the start_shower pattern generalized).

    hap_preset.py --temp 86 --outlets 1,2
    hap_preset.py --stop          # main off
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
    ap.add_argument("--temp", type=float, metavar="F", help="target temp to arm")
    ap.add_argument("--outlets", metavar="1,2", help="outlet positions to arm (comma-separated)")
    ap.add_argument("--stop", action="store_true", help="main off")
    ap.add_argument("--env", help="path to .env")
    args = ap.parse_args()
    env = load_env(args.env)
    pairing = pairing_from_env(env)
    try:
        if args.stop:
            await pairing.put_characteristics([(1, MAIN_ACTIVE_IID, 0)])
            print("main off OK")
            await asyncio.sleep(1)
            print(fmt_state(await pairing.get_characteristics(READ_PAIRS)))
            return
        outlets = {int(p) for p in args.outlets.split(",")} if args.outlets else set()
        unknown = outlets - set(OUTLET_ACTIVE_IIDS)
        if unknown or (args.temp is None and not outlets):
            sys.exit("need --temp and/or --outlets (positions 1-4)")
        puts = [(1, iid, 1 if pos in outlets else 0) for pos, iid in OUTLET_ACTIVE_IIDS.items()]
        if args.temp is not None:
            puts.append((1, HEATER_TARGET_TEMP_IID, f_to_c(args.temp)))
        puts.append((1, MAIN_ACTIVE_IID, 1))
        print(f"arm outlets={sorted(outlets)} temp={args.temp}F -> {len(puts)} puts")
        t0 = asyncio.get_event_loop().time()
        for i, p in enumerate(puts, 1):
            await pairing.put_characteristics([p])
        print(f"all {len(puts)} puts OK (+{asyncio.get_event_loop().time() - t0:.3f}s)")
        await asyncio.sleep(1)
        print(fmt_state(await pairing.get_characteristics(READ_PAIRS)))
    finally:
        try:
            await pairing.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))