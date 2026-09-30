#!/usr/bin/env python3
"""Call a Home Assistant websocket command (UI-managed config channel).

    ha_ws_call.py '<json command>'   e.g. {"type":"config/script/config/cooldown_shower", ...}
"""
import asyncio
import json
import sys

from moen_hap import load_env
import aiohttp


async def main():
    command = json.loads(sys.argv[1])
    env = load_env(None)
    token = env["HA_TOKEN"]
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect("http://192.168.2.85:8123/api/websocket") as ws:
            msg = json.loads((await ws.receive()).data)
            assert msg["type"] == "auth_required", msg
            await ws.send_json({"type": "auth", "access_token": token})
            msg = json.loads((await ws.receive()).data)
            assert msg["type"] == "auth_ok", msg
            await ws.send_json({"id": 1, **command})
            while True:
                msg = json.loads((await ws.receive()).data)
                print("<<", json.dumps(msg)[:600], flush=True)
                if msg.get("id") == 1:
                    return


if __name__ == "__main__":
    asyncio.run(main())