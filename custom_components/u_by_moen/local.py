"""Local HAP control transport for U by Moen (aiohomekit, pairing by IP).

The shower exposes a native HomeKit accessory server on the LAN. We pair
once (setup code) and keep the pairing keys in a JSON file next to
configuration.yaml — no mDNS, no cloud involved in the control path.

Valve semantics (verified against the TS3304, fw 3.3.0):
- Outlet Active writes while the shower is off are "armed" and apply when
  the main Active characteristic turns on.
- Main Active (iid 9) is the shower on/off.
- Outlets are additive while the shower is running.
- Turning off the last active outlet requires the main to go off as well.
"""
import asyncio
import json
import logging
import os

from aiohomekit.controller import Controller
from aiohomekit.controller.ip.pairing import IpPairing

_LOGGER = logging.getLogger(__name__)

HAP_PAIRING_FILE = "u_by_moen_hap.json"

# Characteristic iids (aid=1) from the shower's accessory map:
MAIN_ACTIVE_IID = 9  # Valve service Active — shower on/off
HEATER_CURRENT_TEMP_IID = 13  # celsius, read
HEATER_TARGET_STATE_IID = 15  # writable
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
        self._lock = asyncio.Lock()

    @classmethod
    def load_from_config(cls, hass):
        """Return a MoenLocal if the pairing file exists, else None."""
        path = hass.config.path(HAP_PAIRING_FILE)
        if not os.path.isfile(path):
            return None
        try:
            with open(path) as f:
                pairing_data = json.load(f)
            return cls(hass, pairing_data)
        except (OSError, ValueError) as err:
            _LOGGER.error("Failed to load %s: %s", path, err)
            return None

    async def _get(self, pairs):
        return await self._pairing.get_characteristics(pairs)

    async def _put(self, pairs):
        await self._pairing.put_characteristics(pairs)

    async def read_state(self) -> dict:
        """Read main/outlet/temp state: {'main': bool, 'outlets': {pos: bool}, ...}."""
        pairs = [(1, MAIN_ACTIVE_IID), (1, HEATER_CURRENT_TEMP_IID), (1, HEATER_TARGET_TEMP_IID)]
        pairs += [(1, iid) for iid in OUTLET_ACTIVE_IIDS.values()]
        result = await self._get(pairs)

        def val(aid, iid):
            return result.get((1, iid), {}).get("value", 0)

        outlets = {pos: bool(val) for pos, iid in OUTLET_ACTIVE_IIDS.items() if (val := result.get((1, iid), {}).get("value")) is not None}
        return {
            "main": bool(val(1, MAIN_ACTIVE_IID)),
            "outlets": outlets,
            "current_temp_f": c_to_f(float(val(1, HEATER_CURRENT_TEMP_IID))),
            "target_temp_f": c_to_f(float(val(1, HEATER_TARGET_TEMP_IID))),
        }

    async def set_main(self, on: bool) -> None:
        await self._put([(1, MAIN_ACTIVE_IID, int(bool(on)))])
        _LOGGER.debug("local: main Active=%d", int(on))

    async def set_outlet(self, position: int, active: bool, main_is_on: bool) -> None:
        """Set an outlet. Arms + starts main when shower is off; additive when running."""
        iid = OUTLET_ACTIVE_IIDS.get(position)
        if iid is None:
            raise ValueError(f"Unknown outlet position {position}")
        await self._put([(1, iid, int(active))])
        if active and not main_is_on:
            # Armed outlet applies when the main turns on (verified behavior)
            await self._put([(1, MAIN_ACTIVE_IID, 1)])
            _LOGGER.debug("local: outlet %d armed, main on", position)
        else:
            _LOGGER.debug("local: outlet %d active=%d", position, int(active))

    async def set_target_temp(self, fahrenheit: float) -> None:
        await self._put([(1, HEATER_TARGET_TEMP_IID, f_to_c(fahrenheit))])
        _LOGGER.debug("local: target temp %.1fF", fahrenheit)

    async def close(self) -> None:
        try:
            await self._pairing.close()
        except Exception:  # noqa: BLE001
            pass