"""Local HAP control transport for U by Moen (aiohomekit, pairing by IP).

The shower exposes a native HomeKit accessory server on the LAN. We pair
once (setup code) and keep the pairing keys in a JSON file next to
configuration.yaml — no mDNS, no cloud involved in the control path.

Valve semantics (verified against the TS3304, fw 3.3.0 — see
moen-local-transport.md in the home-assistant repo for the full map):
- Writes while the shower is off are "armed" (hidden from readback, applied
  at main-on). The integration deliberately AVOIDS arming: to match cloud
  behavior, valve/temp writes while off are no-ops, and power-on is
  main-on + outlet-1-on (mirrors cloud shower_on preset 0).
- Main Active (iid 9) is the shower on/off. Local main-off clears all
  outlets, like cloud shower_off.
- main=1 with zero active outlets is the device's PAUSE state (cloud:
  paused-by-user).
- Writes while running apply in <=2s. Back-to-back puts on one session are
  safe; concurrent HAP sessions are the suspected crash trigger, so all
  traffic is serialized through one connection with >=10s between puts.
"""
import asyncio
import json
import logging
import os
import time

from aiohomekit.controller import Controller
from aiohomekit.controller.ip.pairing import IpPairing

from .const import HAP_WRITE_MIN_INTERVAL

_LOGGER = logging.getLogger(__name__)

HAP_PAIRING_FILE = "u_by_moen_hap.json"

# Characteristic iids (aid=1) from the shower's accessory map:
MAIN_ACTIVE_IID = 9  # Valve service Active — shower on/off
HEATER_CURRENT_TEMP_IID = 13  # celsius, read
HEATER_TARGET_STATE_IID = 15  # readable but always 0 — dead characteristic, ignore
HEATER_TARGET_TEMP_IID = 16  # celsius, writable
OUTLET_ACTIVE_IIDS = {1: 18, 2: 23, 3: 28, 4: 33}  # outlet position -> Active iid


def c_to_f(celsius: float) -> float:
    return round(celsius * 9 / 5 + 32)


def f_to_c(fahrenheit: float) -> float:
    return round((fahrenheit - 32) * 5 / 9, 5)


class MoenLocal:
    """Direct HAP session with the shower over the LAN."""

    def __init__(self, hass, pairing_data: dict):
        self._controller = Controller()
        self._pairing = IpPairing(self._controller, dict(pairing_data))
        # Serialize ALL HAP traffic through one session. Concurrent sessions
        # are the suspected device-crash trigger; rapid puts on one session
        # are safe (verified), but we still pace writes to be conservative.
        self._lock = asyncio.Lock()
        self._last_write = 0.0

    @classmethod
    def read_pairing_file(cls, hass):
        """Read the pairing JSON (call via async_add_executor_job). Returns dict | None."""
        path = hass.config.path(HAP_PAIRING_FILE)
        if not os.path.isfile(path):
            return None
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError) as err:
            _LOGGER.error("Failed to load %s: %s", path, err)
            return None

    async def _get(self, pairs):
        """Read characteristics (serialized; one retry on transient failure)."""
        async with self._lock:
            try:
                return await self._pairing.get_characteristics(pairs)
            except Exception:
                # Transient transport errors observed (e.g. OSError 49); one
                # spaced retry before surfacing the failure.
                await asyncio.sleep(2)
                return await self._pairing.get_characteristics(pairs)

    async def _put(self, pairs):
        """Write one characteristic pair, serialized and paced."""
        async with self._lock:
            wait = self._last_write + HAP_WRITE_MIN_INTERVAL - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            await self._pairing.put_characteristics(pairs)
            self._last_write = time.monotonic()

    async def read_state(self) -> dict:
        """Read main/outlet/temp state: {'main': bool, 'outlets': {pos: bool}, ...}."""
        pairs = [(1, MAIN_ACTIVE_IID), (1, HEATER_CURRENT_TEMP_IID), (1, HEATER_TARGET_TEMP_IID)]
        pairs += [(1, iid) for iid in OUTLET_ACTIVE_IIDS.values()]
        result = await self._get(pairs)

        def val(iid):
            return result.get((1, iid), {}).get("value", 0)

        outlets = {}
        for pos, iid in OUTLET_ACTIVE_IIDS.items():
            raw = result.get((1, iid), {}).get("value")
            if raw is not None:
                outlets[pos] = bool(raw)
        return {
            "main": bool(val(MAIN_ACTIVE_IID)),
            "outlets": outlets,
            "current_temp_f": c_to_f(float(val(HEATER_CURRENT_TEMP_IID))),
            "target_temp_f": c_to_f(float(val(HEATER_TARGET_TEMP_IID))),
        }

    async def set_main(self, on: bool) -> None:
        """Set main Active. Bare main-on with no outlets parks the shower in
        paused-by-user; use start_shower() to begin a shower (arm + main).
        Local main-off clears all outlets device-side, like cloud shower_off."""
        await self._put([(1, MAIN_ACTIVE_IID, int(bool(on)))])
        _LOGGER.debug("local: main Active=%d", int(on))

    async def set_outlet(self, position: int, active: bool) -> None:
        """Write a single outlet Active characteristic. Caller is responsible
        for only calling this while the shower is running (writes while off
        would be device-side 'armed', which we avoid — see module docstring)."""
        iid = OUTLET_ACTIVE_IIDS.get(position)
        if iid is None:
            raise ValueError(f"Unknown outlet position {position}")
        await self._put([(1, iid, int(active))])
        _LOGGER.debug("local: outlet %d active=%d", position, int(active))

    async def start_shower(self, position: int = 1) -> None:
        """Start the shower the way the device natively expects: arm the
        outlet, then immediately turn main on — back-to-back on one session.
        Verified safe (no wedge) and cloud-equivalent in outcome: outlet
        opens at start, water/heating begins (unlike main-on alone, which
        parks the shower in paused-by-user)."""
        iid = OUTLET_ACTIVE_IIDS.get(position)
        if iid is None:
            raise ValueError(f"Unknown outlet position {position}")
        async with self._lock:
            await self._pairing.put_characteristics([(1, iid, 1)])
            await self._pairing.put_characteristics([(1, MAIN_ACTIVE_IID, 1)])
            self._last_write = time.monotonic()
        _LOGGER.debug("local: shower start (outlet %d armed + main on)", position)

    async def set_target_temp(self, fahrenheit: float) -> None:
        await self._put([(1, HEATER_TARGET_TEMP_IID, f_to_c(fahrenheit))])
        _LOGGER.debug("local: target temp %.1fF", fahrenheit)

    async def close(self) -> None:
        try:
            await self._pairing.close()
        except Exception:  # noqa: BLE001
            pass