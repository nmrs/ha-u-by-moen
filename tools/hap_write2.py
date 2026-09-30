#!/usr/bin/env python3
"""B4/D2 crash probe: replicate the fork's set_outlet write pattern exactly.

One process, ONE HAP session, two put_characteristics calls back-to-back
with zero gap — precisely what custom_components/u_by_moen/local.py
set_outlet() does when arming an outlet and turning main on.

    hap_write2.py --outlet 2 --main on
"""
import argparse
import asyncio
import sys

from moen_hap import (
    MAIN_ACTIVE_IID,
    OUTLET_ACTIVE_IIDS,
    READ_PAIRS,
    fmt_state,
    load_env,
    pairing_from_env,
)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outlet", type=int, choices=[1, 2, 3, 4], required=True)
    ap.add_argument("--main", choices=["on", "off"], required=True)
    ap.add_argument("--env", help="path to .env")
    args = ap.parse_args()

    env = load_env(args.env)
    pairing = pairing_from_env(env)
    try:
        iid = OUTLET_ACTIVE_IIDS[args.outlet]
        pairs1 = [(1, iid, 1 if args.main == "on" else 0)]
        pairs2 = [(1, MAIN_ACTIVE_IID, 1 if args.main == "on" else 0)]
        print(f"PUT1 iid={iid} value={pairs1[0][2]}")
        t0 = asyncio.get_event_loop().time()
        await pairing.put_characteristics(pairs1)
        t1 = asyncio.get_event_loop().time()
        print(f"PUT1 OK (+{t1 - t0:.3f}s) — immediately PUT2 iid={MAIN_ACTIVE_IID} value={pairs2[0][2]}")
        await pairing.put_characteristics(pairs2)
        t2 = asyncio.get_event_loop().time()
        print(f"PUT2 OK (+{t2 - t1:.3f}s)")
        await asyncio.sleep(1)
        result = await pairing.get_characteristics(READ_PAIRS)
        print(f"+1s  {fmt_state(result)}")
    finally:
        try:
            await pairing.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))