#!/usr/bin/env python3
"""Single controlled HAP write to the U by Moen shower.

Exactly ONE characteristic put per invocation, with a cross-invocation
spacing check (lockfile) — the shower's HAP server is fragile and rapid
writes crash it.

    hap_write.py --temp 104            # target temp, F (converted to C)
    hap_write.py --main on|off
    hap_write.py --outlet 1 on|off     # single outlet put, nothing else
    hap_write.py --raw IID VALUE       # raw iid + value (e.g. --raw 15 1)
    hap_write.py --read                # read-only, ignores spacing lock
"""
import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

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

LOCK = Path.home() / ".moen_hap_write_lock"
DEFAULT_GAP = 10.0  # seconds between ANY two writes


def check_spacing(gap):
    """Refuse to write if the previous write (by any invocation) is too recent."""
    now = time.time()
    if LOCK.exists():
        try:
            last = json.loads(LOCK.read_text()).get("ts", 0)
        except (OSError, ValueError):
            last = 0
        wait = last + gap - now
        if wait > 0:
            sys.exit(f"REFUSING: last HAP write {now - last:.1f}s ago, "
                     f"min gap {gap:.0f}s — wait {wait:.1f}s (or --min-gap 0 to override)")
    LOCK.write_text(json.dumps({"ts": now}))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--temp", type=float, metavar="F", help="target temp in F (single put)")
    ap.add_argument("--main", choices=["on", "off"], help="main Active (single put)")
    ap.add_argument("--outlet", type=int, choices=[1, 2, 3, 4], help="outlet position (single put)")
    ap.add_argument("--state", choices=["on", "off"], help="with --outlet")
    ap.add_argument("--raw", type=int, metavar="IID", help="raw iid to put")
    ap.add_argument("--raw-value", metavar="VALUE", help="with --raw")
    ap.add_argument("--read", action="store_true", help="read-only state print")
    ap.add_argument("--min-gap", type=float, default=DEFAULT_GAP, help="spacing seconds (default 10)")
    ap.add_argument("--env", help="path to .env")
    args = ap.parse_args()

    env = load_env(args.env)
    pairing = pairing_from_env(env)
    try:
        if args.read:
            result = await pairing.get_characteristics(READ_PAIRS)
            print(fmt_state(result))
            return

        if args.temp is not None:
            pairs = [(1, HEATER_TARGET_TEMP_IID, f_to_c(args.temp))]
            print(f"PUT iid={HEATER_TARGET_TEMP_IID} value={pairs[0][2]} ({args.temp}F)")
        elif args.main:
            pairs = [(1, MAIN_ACTIVE_IID, 1 if args.main == "on" else 0)]
            print(f"PUT iid={MAIN_ACTIVE_IID} value={pairs[0][2]}")
        elif args.outlet is not None and args.state:
            iid = OUTLET_ACTIVE_IIDS[args.outlet]
            pairs = [(1, iid, 1 if args.state == "on" else 0)]
            print(f"PUT iid={iid} (outlet {args.outlet}) value={pairs[0][2]}")
        elif args.raw and args.raw_value is not None:
            try:
                value = int(args.raw_value)
            except ValueError:
                value = float(args.raw_value)
            pairs = [(1, args.raw, value)]
            print(f"PUT iid={args.raw} value={value!r}")
        else:
            ap.error("choose exactly one of --temp/--main/--outlet+--state/--raw+--raw-value/--read")

        check_spacing(args.min_gap)
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        await pairing.put_characteristics(pairs)
        print(f"{ts}  write OK")
        await asyncio.sleep(1)
        result = await pairing.get_characteristics(READ_PAIRS)
        print(f"{ts}+1s  {fmt_state(result)}")
    finally:
        try:
            await pairing.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))