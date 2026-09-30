#!/usr/bin/env python3
"""Read-only HAP observer for the U by Moen shower.

Polls the shower's characteristics (same iids the integration reads) and
prints timestamped state. Never writes, never pairs.

    hap_observe.py --once
    hap_observe.py --watch 120 --interval 2
"""
import argparse
import asyncio
import sys
import time
from datetime import datetime, timezone

from moen_hap import READ_PAIRS, fmt_state, load_env, pairing_from_env


async def read_once(pairing):
    result = await pairing.get_characteristics(READ_PAIRS)
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]
    print(f"{ts}  {fmt_state(result)}", flush=True)
    return result


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="single read and exit")
    ap.add_argument("--watch", type=float, metavar="SECONDS", help="watch duration")
    ap.add_argument("--interval", type=float, default=2.0, help="poll interval (default 2s)")
    ap.add_argument("--env", help="path to .env (default ../home-assistant/.env)")
    args = ap.parse_args()

    env = load_env(args.env)
    pairing = pairing_from_env(env)
    try:
        if args.once:
            await read_once(pairing)
            return
        if not args.watch:
            ap.error("use --once or --watch SECONDS")
        end = time.monotonic() + args.watch
        while time.monotonic() < end:
            try:
                await read_once(pairing)
            except Exception as err:  # noqa: BLE001
                print(f"READ ERROR: {err!r}", flush=True)
            await asyncio.sleep(args.interval)
    finally:
        try:
            await pairing.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))