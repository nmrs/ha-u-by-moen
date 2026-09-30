#!/usr/bin/env python3
"""Send official cloud (Pusher) control events to the U by Moen shower.

Reuses the fork's own MoenApi — same protocol the official app/integration
cloud fallback uses. Establishes cloud-path ground truth for the local
transport comparison.

    cloud_command.py on|off
    cloud_command.py temp 104
    cloud_command.py outlet 2 on
    cloud_command.py preset 1
    cloud_command.py observe 60     # connect + subscribe, print events, no command
"""
import asyncio
import logging
import sys
import types
from pathlib import Path

# Import u_by_moen.api WITHOUT executing the package __init__.py (which
# imports homeassistant). Register the package with __path__ first, so
# relative imports inside api.py resolve normally.
_PKG = Path(__file__).resolve().parent.parent / "custom_components" / "u_by_moen"
_pkg_mod = types.ModuleType("u_by_moen")
_pkg_mod.__path__ = [str(_PKG)]
sys.modules["u_by_moen"] = _pkg_mod

import aiohttp  # noqa: E402

from moen_hap import load_env  # noqa: E402
from u_by_moen.api import MoenApi  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cloud_command")

LISTEN_SECONDS = 20  # keep ws open after sending to catch reported-state events


async def run(args, env):
    api = MoenApi(env["MOEN_USERNAME"], env["MOEN_PASSWORD"], aiohttp.ClientSession())
    token = await api.authenticate()
    log.info("authenticated (token len %d)", len(token))
    devices = await api.get_devices()
    if not devices:
        sys.exit("no devices found")
    serial = devices[0]["serial_number"]
    details = await api.get_device_details(serial)
    channel_id = details.get("channel")
    mode = details.get("mode")
    log.info("device %s channel=%s mode=%s", serial, channel_id, mode)

    await api.get_pusher_credentials()
    if not await api.connect_pusher():
        sys.exit("pusher connect failed")

    async def on_event(event, data):
        log.info("EVENT %s %s", event, data)

    if not await api.subscribe_to_channel(channel_id, on_event):
        sys.exit("subscribe failed")

    if args.cmd == "status":
        log.info("CLOUD DETAIL mode=%s target=%s current=%s active_preset=%s outlets=%s",
                 details.get("mode"), details.get("target_temperature"),
                 details.get("current_temperature"), details.get("active_preset"),
                 [(o.get("position"), o.get("active")) for o in details.get("outlets", [])])
        await asyncio.sleep(1)
    elif args.cmd == "observe":
        await asyncio.sleep(float(args.arg[0]) if args.arg else 60)
    elif args.cmd == "on":
        await api.set_shower_mode(serial, "on", preset="0")
        await asyncio.sleep(LISTEN_SECONDS)
    elif args.cmd == "off":
        await api.set_shower_mode(serial, "off")
        await asyncio.sleep(LISTEN_SECONDS)
    elif args.cmd == "temp":
        await api.set_target_temperature(serial, float(args.arg[0]))
        await asyncio.sleep(LISTEN_SECONDS)
    elif args.cmd == "outlet":
        pos, state = int(args.arg[0]), args.arg[1] == "on"
        await api.set_outlet_state(serial, pos, state)
        await asyncio.sleep(LISTEN_SECONDS)
    elif args.cmd == "preset":
        await api.activate_preset(serial, int(args.arg[0]))
        await asyncio.sleep(LISTEN_SECONDS)
    else:
        sys.exit(f"unknown command {args.cmd}")

    await api.disconnect_pusher()


async def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["on", "off", "temp", "outlet", "preset", "observe", "status"])
    ap.add_argument("arg", nargs="*", help="value(s) for temp/outlet/preset/observe")
    ap.add_argument("--env", help="path to .env")
    args = ap.parse_args()
    env = load_env(args.env)
    await run(args, env)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))