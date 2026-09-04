"""Switch platform for U by Moen."""
import asyncio
import logging
from typing import Any, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    ATTR_OUTLETS,
    MODE_OFF,
    MODE_PAUSED_BY_PRESET,
    ICON_SHOWER,
    ICON_OUTLET,
)
from .coordinator import MoenDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Outlet icon mappings based on icon_index from API
OUTLET_ICONS = {
    0: "mdi:shower-head",  # Shower head
    1: "mdi:shower",  # Rain shower
    2: "mdi:water",  # Hand shower
    3: "mdi:spray",  # Body spray
    4: "mdi:water-pump",  # Pump/valve
    5: "mdi:waves",  # Water feature
    6: "mdi:bathtub",  # Tub spout
}


def _local_transport(coordinator):
    """Return the optional local HAP transport from the coordinator."""
    return getattr(coordinator, "local", None)


def _main_is_on(device_data: dict) -> bool:
    """True when the shower is running (any non-off mode)."""
    mode = device_data.get("mode", MODE_OFF)
    return mode not in (MODE_OFF, MODE_PAUSED_BY_PRESET)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Moen switch entities."""
    coordinator: MoenDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    api = hass.data[DOMAIN][entry.entry_id]["api"]

    entities = []
    for serial_number, device_data in coordinator.data.items():
        # Add main shower on/off switch
        entities.append(MoenShowerSwitch(coordinator, api, serial_number))

        # Add outlet switches
        outlets = device_data.get(ATTR_OUTLETS, [])
        for outlet in outlets:
            position = outlet.get("position")
            if position:
                entities.append(
                    MoenOutletSwitch(coordinator, api, serial_number, position)
                )

    async_add_entities(entities)


class MoenShowerSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Moen shower on/off switch."""

    _attr_icon = ICON_SHOWER

    def __init__(
        self,
        coordinator: MoenDataUpdateCoordinator,
        api,
        serial_number: str,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._api = api
        self._serial_number = serial_number
        self._attr_unique_id = f"{serial_number}_power"
        self._optimistic_state = None  # None means use coordinator data

    @property
    def device_info(self):
        """Return device information."""
        device_data = self.coordinator.data[self._serial_number]
        return {
            "identifiers": {(DOMAIN, self._serial_number)},
            "name": device_data.get("name", f"Moen Shower {self._serial_number}"),
            "manufacturer": "Moen",
            "model": "U by Moen Shower",
            "sw_version": device_data.get("current_firmware_version"),
        }

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        device_data = self.coordinator.data[self._serial_number]
        device_name = device_data.get("name", f"Shower {self._serial_number}")
        return f"{device_name} Power"

    @property
    def is_on(self) -> bool:
        """Return true if the shower is on."""
        # If we have an optimistic state (command just sent), use that
        if self._optimistic_state is not None:
            return self._optimistic_state
        # Otherwise use coordinator data
        device_data = self.coordinator.data[self._serial_number]
        mode = device_data.get("mode", MODE_OFF)
        # Treat paused-by-preset like off so UI exposes resume option
        return mode not in (MODE_OFF, MODE_PAUSED_BY_PRESET)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the shower on."""
        self._optimistic_state = True  # Optimistically assume it worked
        self.async_write_ha_state()  # Update UI immediately
        local = _local_transport(self.coordinator)
        if local:
            try:
                await local.set_main(True)
                return
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Local main-on failed, falling back to cloud: %s", err)
        device_data = self.coordinator.data[self._serial_number]
        mode = device_data.get("mode", MODE_OFF)
        active_preset = device_data.get("active_preset")
        if mode == MODE_PAUSED_BY_PRESET:
            await self._api.resume_shower(self._serial_number, active_preset)
        else:
            await self._api.set_shower_mode(self._serial_number, "on")
        # State will be confirmed via Pusher client-state-reported event

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the shower off."""
        self._optimistic_state = False  # Optimistically assume it worked
        self.async_write_ha_state()  # Update UI immediately
        local = _local_transport(self.coordinator)
        if local:
            try:
                await local.set_main(False)
                return
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Local main-off failed, falling back to cloud: %s", err)
        await self._api.set_shower_mode(self._serial_number, MODE_OFF)
        # State will be confirmed via Pusher client-state-reported event

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # When coordinator updates (Pusher event), clear optimistic state
        # so we use the actual confirmed state from the device
        self._optimistic_state = None
        super()._handle_coordinator_update()


class MoenOutletSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Moen shower outlet switch."""

    def __init__(
        self,
        coordinator: MoenDataUpdateCoordinator,
        api,
        serial_number: str,
        outlet_position: int,
    ) -> None:
        """Initialize the outlet switch."""
        super().__init__(coordinator)
        self._api = api
        self._serial_number = serial_number
        self._outlet_position = outlet_position
        self._attr_unique_id = f"{serial_number}_outlet_{outlet_position}"
        self._optimistic_state = None  # None means use coordinator data

    @property
    def device_info(self):
        """Return device information."""
        device_data = self.coordinator.data[self._serial_number]
        return {
            "identifiers": {(DOMAIN, self._serial_number)},
            "name": device_data.get("name", f"Moen Shower {self._serial_number}"),
            "manufacturer": "Moen",
            "model": "U by Moen Shower",
            "sw_version": device_data.get("current_firmware_version"),
        }

    @property
    def name(self) -> str:
        """Return the name of the outlet switch."""
        device_data = self.coordinator.data[self._serial_number]
        device_name = device_data.get("name", f"Shower {self._serial_number}")
        return f"{device_name} Valve {self._outlet_position}"

    @property
    def icon(self) -> str:
        """Return the icon for this outlet."""
        outlet = self._get_outlet_data()
        if outlet:
            icon_index = outlet.get("icon_index", 0)
            return OUTLET_ICONS.get(icon_index, ICON_OUTLET)
        return ICON_OUTLET

    @property
    def is_on(self) -> bool:
        """Return true if the outlet is active."""
        # If we have an optimistic state (command just sent), use that
        if self._optimistic_state is not None:
            return self._optimistic_state
        # Otherwise use coordinator data
        outlet = self._get_outlet_data()
        if outlet:
            return outlet.get("active", False)
        return False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the outlet on."""
        self._optimistic_state = True  # Optimistically assume it worked
        self.async_write_ha_state()  # Update UI immediately

        device_data = self.coordinator.data[self._serial_number]
        local = _local_transport(self.coordinator)
        if local:
            try:
                await local.set_outlet(
                    self._outlet_position, True, main_is_on=_main_is_on(device_data)
                )
                return
            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "Local valve %d on failed, falling back to cloud: %s",
                    self._outlet_position,
                    err,
                )

        current_mode = device_data.get("mode", MODE_OFF)

        # If shower is off, turn it on with this outlet
        if current_mode == MODE_OFF:
            _LOGGER.debug("Shower is off, turning on with outlet %d", self._outlet_position)
            await self._api.set_shower_mode(self._serial_number, "on")
            # Wait for the device to leave 'off' before commanding outlets —
            # the device ignores outlet commands until it reports itself on.
            try:
                await asyncio.wait_for(
                    self._wait_for_running(), timeout=10
                )
            except TimeoutError:
                _LOGGER.warning(
                    "Shower did not report running in time; sending outlets_set anyway"
                )
        elif current_mode == MODE_PAUSED_BY_PRESET:
            _LOGGER.debug(
                "Shower paused by preset, resuming before enabling outlet %d",
                self._outlet_position,
            )
            await self._api.resume_shower(
                self._serial_number, device_data.get("active_preset")
            )
            await asyncio.sleep(0.5)

        # Get current outlet states from coordinator (has real-time data from Pusher)
        device_data = self.coordinator.data[self._serial_number]
        outlets = device_data.get(ATTR_OUTLETS, [])

        # Build new outlet states list with this outlet turned on, keeping others as-is
        new_outlet_states = []
        for outlet in outlets:
            pos = outlet.get("position")
            # Turn on this outlet, keep others in their current state
            if pos == self._outlet_position:
                new_outlet_states.append({"position": pos, "active": True})
            else:
                new_outlet_states.append({"position": pos, "active": outlet.get("active", False)})

        # Get device channel for sending command
        device_details = await self._api.get_device_details(self._serial_number)
        channel_id = device_details.get("channel")
        if channel_id:
            await self._api.send_control_event(channel_id, "outlets_set", {"outlets": new_outlet_states})
        # State will be confirmed via Pusher client-state-reported event

    async def _wait_for_running(self) -> None:
        """Poll coordinator data until the shower reports a non-off mode."""
        async def _running() -> bool:
            data = self.coordinator.data[self._serial_number]
            return data.get("mode", MODE_OFF) not in (MODE_OFF, MODE_PAUSED_BY_PRESET)

        async def _request_refresh() -> None:
            await self.coordinator.async_request_refresh()

        # Poll: request a coordinator refresh (which merges a fresh local HAP
        # read) at most ~2x/second until the device reports it is running.
        deadline = asyncio.get_event_loop().time() + 10
        while asyncio.get_event_loop().time() < deadline:
            try:
                await _request_refresh()
            except Exception:  # noqa: BLE001
                pass
            if _main_is_on(self.coordinator.data[self._serial_number]):
                return
            await asyncio.sleep(0.5)
        raise TimeoutError("Shower did not report running state")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the outlet off."""
        self._optimistic_state = False  # Optimistically assume it worked
        self.async_write_ha_state()  # Update UI immediately

        device_data = self.coordinator.data[self._serial_number]
        local = _local_transport(self.coordinator)
        if local:
            try:
                await local.set_outlet(self._outlet_position, False, main_is_on=True)
                # If this was the only active outlet, stop the shower entirely
                outlets = device_data.get(ATTR_OUTLETS, [])
                active_others = [
                    o
                    for o in outlets
                    if o.get("active") and o.get("position") != self._outlet_position
                ]
                if not active_others:
                    await local.set_main(False)
                return
            except Exception as err:  # noqa: BLE001
                _LOGGER.error(
                    "Local valve %d off failed, falling back to cloud: %s",
                    self._outlet_position,
                    err,
                )

        outlets = device_data.get(ATTR_OUTLETS, [])

        # Count how many outlets are currently active
        active_outlets = [o for o in outlets if o.get("active", False)]

        # If this is the only active outlet, turn off the entire shower
        if len(active_outlets) == 1 and active_outlets[0].get("position") == self._outlet_position:
            _LOGGER.debug("This is the only active outlet, turning off entire shower")
            await self._api.set_shower_mode(self._serial_number, MODE_OFF)
        else:
            # Otherwise, just turn off this outlet (keep others as-is)
            _LOGGER.debug("Multiple outlets active, turning off only outlet %d", self._outlet_position)

            # Build new outlet states list with this outlet turned off, keeping others as-is
            new_outlet_states = []
            for outlet in outlets:
                pos = outlet.get("position")
                # Turn off this outlet, keep others in their current state
                if pos == self._outlet_position:
                    new_outlet_states.append({"position": pos, "active": False})
                else:
                    new_outlet_states.append({"position": pos, "active": outlet.get("active", False)})

            # Get device channel for sending command
            device_details = await self._api.get_device_details(self._serial_number)
            channel_id = device_details.get("channel")
            if channel_id:
                await self._api.send_control_event(channel_id, "outlets_set", {"outlets": new_outlet_states})
        # State will be confirmed via Pusher client-state-reported event

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # When coordinator updates (Pusher event), clear optimistic state
        # so we use the actual confirmed state from the device
        self._optimistic_state = None
        super()._handle_coordinator_update()

    def _get_outlet_data(self) -> Optional[dict]:
        """Get the outlet data for this position."""
        device_data = self.coordinator.data[self._serial_number]
        outlets = device_data.get(ATTR_OUTLETS, [])
        for outlet in outlets:
            if outlet.get("position") == self._outlet_position:
                return outlet
        return None