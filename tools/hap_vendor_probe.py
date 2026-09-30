#!/usr/bin/env python3
"""Probe the TS3304's hidden vendor service (iid 38-42, UUID 00000010-...-001D4B474349).

- Reads iid 38 once and prints the raw value.
- Subscribes to iid 38 (and standard state chars) and prints events live.

Press preset buttons on the console while this runs.

    hap_vendor_probe.py --watch 180
"""
import argparse
import asyncio
import sys
import time
from datetime import datetime

from moen_hap import load_env, pairing_from_env

VENDOR_READ = (1, 38)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", type=float, default=180)
    ap.add_argument("--env", help="path to .env")
    args = ap.parse_args()

    env = load_env(args.env)
    pairing = pairing_from_env(env)
    try:
        result = await pairing.get_characteristics([VENDOR_READ])
        entry = result.get(VENDOR_READ, {})
        print(f"iid 38 read: status={entry.get('status')} value={entry.get('value')!r}", flush=True)

        def on_event(formatted):
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"{ts}  EVENT {formatted}", flush=True)

        pairing.listeners.add(on_event)
        await pairing.subscribe([VENDOR_READ])
        end = time.monotonic() + args.watch
        while time.monotonic() < end:
            await asyncio.sleep(1)
        try:
            await pairing.unsubscribe([VENDOR_READ])
            await pairing.close()
        except Exception:  # noqa: BLE001
            pass
        print("done", flush=True)
    finally:
        try:
            await pairing.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))