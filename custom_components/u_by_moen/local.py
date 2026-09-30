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

    # Minimum seconds between coordinator pushes driven ONLY by streaming
    # current-temp events (they arrive ~2s apart while running; state
    # changes like main/outlets always push immediately).
    TEMP_EVENT_THROTTLE = 5.0

    def __init__(self, hass, pairing_data: dict):
        self._controller = Controller()
        self._pairing = IpPairing(self._controller, dict(pairing_data))
        self._hass = hass
        # Serialize ALL HAP traffic through one session. Concurrent sessions
        # are the suspected device-crash trigger; rapid puts on one session
        # are safe (verified), but we still pace writes to be conservative.
        self._lock = asyncio.Lock()
        self._last_write = 0.0
        # Latest known local state, updated by both reads and pushed events:
        # {'main': bool, 'outlets': {pos: bool}, 'current_temp_f': float,
        #  'target_temp_f': float} — consumed by the coordinator overlay.
        self.latest_state: dict | None = None
        self._subscribed = False
        self._last_temp_push = 0.0
        self._event_listener = None

    def _absorb(self, values: dict) -> None:
        """Fold raw {(aid, iid): {'value': v}} into latest_state."""
        def raw(iid):
            return values.get((1, iid), {}).get("value")

        if self.latest_state is None:
            self.latest_state = {
                "main": False,
                "outlets": {pos: False for pos in OUTLET_ACTIVE_IIDS},
                "current_temp_f": 0.0,
                "target_temp_f": 0.0,
            }
        if (v := raw(MAIN_ACTIVE_IID)) is not None:
            self.latest_state["main"] = bool(v)
        for pos, iid in OUTLET_ACTIVE_IIDS.items():
            if (v := raw(iid)) is not None:
                self.latest_state["outlets"][pos] = bool(v)
        if (v := raw(HEATER_CURRENT_TEMP_IID)) is not None:
            self.latest_state["current_temp_f"] = c_to_f(float(v))
        if (v := raw(HEATER_TARGET_TEMP_IID)) is not None:
            self.latest_state["target_temp_f"] = c_to_f(float(v))

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
                result = await self._pairing.get_characteristics(pairs)
            except Exception:
                # Transient transport errors observed (e.g. OSError 49); one
                # spaced retry before surfacing the failure.
                await asyncio.sleep(2)
                result = await self._pairing.get_characteristics(pairs)
        self._absorb(result)
        return result

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
        Verified safe (no wedge; six back-to-back puts fine) and
        cloud-equivalent in outcome.

        Also CLEARS any stale armed outlets/target first: armed writes
        persist across main on/off cycles on this device (main-off clears
        active outlets but not the armed set — they re-apply at the next
        main-on, as observed 2026-09-30 with a stale armed outlet 2 + temp).
        Target is set to 100F, matching cloud shower_on preset 0."""
        iid = OUTLET_ACTIVE_IIDS.get(position)
        if iid is None:
            raise ValueError(f"Unknown outlet position {position}")
        async with self._lock:
            puts = [(1, i, 1 if pos == position else 0) for pos, i in OUTLET_ACTIVE_IIDS.items()]
            puts.append((1, HEATER_TARGET_TEMP_IID, f_to_c(100)))
            puts.append((1, MAIN_ACTIVE_IID, 1))
            for pair in puts:
                await self._pairing.put_characteristics([pair])
            self._last_write = time.monotonic()
        _LOGGER.debug("local: shower start (clear armed, outlet %d + temp 100F + main on)", position)

    async def apply_preset(self, outlets: list[int], target_temp_f: float | None) -> None:
        """Activate a preset locally — one session, back-to-back puts.

        Shower off: arms the full outlet set + temp, then main on (start).
        Shower running: rewrites all outlet Actives to the preset's set
        (additive/deselecting as needed) + target temp; main stays on.
        cloud shower_set extras (greeting/timer/notifications) have no local
        representation and are not applied."""
        wanted = set(outlets)
        unknown = wanted - set(OUTLET_ACTIVE_IIDS)
        if unknown:
            raise ValueError(f"Unknown outlet positions {sorted(unknown)}")
        if target_temp_f is None and not wanted:
            raise ValueError("apply_preset needs outlets and/or target_temp_f")
        main_on = bool(self.latest_state and self.latest_state.get("main"))
        async with self._lock:
            puts = [(1, iid, 1 if pos in wanted else 0) for pos, iid in OUTLET_ACTIVE_IIDS.items()]
            if target_temp_f is not None:
                puts.append((1, HEATER_TARGET_TEMP_IID, f_to_c(target_temp_f)))
            if not main_on:
                puts.append((1, MAIN_ACTIVE_IID, 1))
            for pair in puts:
                await self._pairing.put_characteristics([pair])
            self._last_write = time.monotonic()
        _LOGGER.debug("local: preset applied (outlets=%s temp=%s, main_was_on=%s)", sorted(wanted), target_temp_f, main_on)

    async def set_target_temp(self, fahrenheit: float) -> None:
        await self._put([(1, HEATER_TARGET_TEMP_IID, f_to_c(fahrenheit))])
        _LOGGER.debug("local: target temp %.1fF", fahrenheit)

    async def start_event_stream(self, notify) -> bool:
        """Subscribe to HAP push events (device advertises ev on all our
        characteristics; verified live 2026-09-30) and push state into the
        coordinator. `notify` is an async callable receiving nothing — the
        caller (coordinator) reads self.latest_state. Returns True when
        subscribed. The 30s poll remains as the backstop."""
        if self._subscribed:
            return True
        pairs = [(1, iid) for iid in (MAIN_ACTIVE_IID, HEATER_CURRENT_TEMP_IID, HEATER_TARGET_TEMP_IID, *OUTLET_ACTIVE_IIDS.values())]

        def on_event(values: dict) -> None:
            if values in (None, {}):  # EMPTY_EVENT = connection restored
                return
            self._absorb(values)
            state_chars = any(k[1] != HEATER_CURRENT_TEMP_IID for k in values)
            now = time.monotonic()
            if not state_chars and now - self._last_temp_push < self.TEMP_EVENT_THROTTLE:
                return  # temp-only burst, throttled
            self._last_temp_push = now
            if state_chars:
                _LOGGER.info(
                    "HAP event: main=%s outlets=%s",
                    self.latest_state["main"],
                    self.latest_state["outlets"],
                )
            hass = getattr(self, "_hass", None)
            if hass is not None:
                hass.async_create_task(notify())
            else:
                notify()

        self._event_listener = on_event
        self._pairing.listeners.add(on_event)
        try:
            result = await self._pairing.subscribe(pairs)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("HAP event subscription failed, falling back to 30s polling: %s", err)
            self._pairing.listeners.discard(on_event)
            self._event_listener = None
            return False
        self._subscribed = True
        if result is None:
            # Device reports it does not support push (aiohomekit flag)
            _LOGGER.info("Shower reports no HAP push support; keeping 30s polling only")
            self._pairing.listeners.discard(on_event)
            self._event_listener = None
            self._subscribed = False
            return False
        _LOGGER.info("HAP event stream active (local push, no cloud)")
        return True

    async def stop_event_stream(self) -> None:
        if not self._subscribed:
            return
        if self._event_listener is not None:
            self._pairing.listeners.discard(self._event_listener)
            self._event_listener = None
        self._subscribed = False
        try:
            await self._pairing.close()
        except Exception:  # noqa: BLE001
            pass

    async def close(self) -> None:
        try:
            await self._pairing.close()
        except Exception:  # noqa: BLE001
            pass