"""Switch platform for U by Moen."""
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
    MODE_PAUSED_BY_USER,
    RUNNING_MODES,
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


def _is_running(device_data: dict) -> bool:
    """True only when the shower is actively running water (adjusting/ready)."""
    return device_data.get("mode", MODE_OFF) in RUNNING_MODES


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
        # Treat paused-by-preset / paused-by-user like off so UI exposes resume
        return mode not in (MODE_OFF, MODE_PAUSED_BY_PRESET, MODE_PAUSED_BY_USER)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the shower on."""
        device_data = self.coordinator.data[self._serial_number]
        mode = device_data.get("mode", MODE_OFF)
        local = _local_transport(self.coordinator)

        if _is_running(device_data):
            _LOGGER.debug("Power on ignored — shower already running")
            return

        # Paused (paused-by-user / paused-by-preset): resume by opening the
        # default outlet (local) or cloud resume. Main is already on.
        paused = mode in (MODE_PAUSED_BY_PRESET, MODE_PAUSED_BY_USER)
        if local and not paused:
            try:
                # Arm outlet 1 + main on, back-to-back — the device-native
                # local start (verified safe; mirrors cloud shower_on which
                # opens outlet 1). A bare main-on would park in paused-by-user.
                await local.start_shower(1)
                self._optimistic_state = True
                self.async_write_ha_state()
                return
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Local start failed, falling back to cloud: %s", err)
        elif local and paused:
            try:
                await local.set_outlet(1, True)
                self._optimistic_state = True
                self.async_write_ha_state()
                return
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Local resume failed, falling back to cloud: %s", err)

        self._optimistic_state = True
        self.async_write_ha_state()
        active_preset = device_data.get("active_preset")
        if paused:
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
                _LOGGER.warning("Local main-off failed, falling back to cloud: %s", err)
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
    def available(self) -> bool:
        """Valve controls are only available while the shower is running —
        the Moen app hides valve buttons when off and the physical console
        ignores them; we match that instead of lying about state."""
        if self._optimistic_state is not None:
            return True
        return _is_running(self.coordinator.data[self._serial_number])

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
        """Turn the outlet on. No-op while the shower is not running —
        device-side writes while off would be silently 'armed' (applied at
        next main-on), which diverges from cloud semantics (ignored)."""
        device_data = self.coordinator.data[self._serial_number]
        if not _is_running(device_data):
            _LOGGER.warning(
                "Valve %d on ignored — shower is not running (mode=%s); "
                "turn the shower power on first",
                self._outlet_position,
                device_data.get("mode", MODE_OFF),
            )
            return

        self._optimistic_state = True  # Command accepted — safe to be optimistic
        self.async_write_ha_state()  # Update UI immediately

        local = _local_transport(self.coordinator)
        if local:
            try:
                await local.set_outlet(self._outlet_position, True)
                return
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Local valve %d on failed, falling back to cloud: %s",
                    self._outlet_position,
                    err,
                )

        # Cloud fallback: full outlet array (shower is running, so outlets_set applies)
        await self._cloud_set_outlets(True)
        # State will be confirmed via Pusher client-state-reported event

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the outlet off. No-op while the shower is not running."""
        device_data = self.coordinator.data[self._serial_number]
        if not _is_running(device_data):
            _LOGGER.warning(
                "Valve %d off ignored — shower is not running (mode=%s)",
                self._outlet_position,
                device_data.get("mode", MODE_OFF),
            )
            return

        self._optimistic_state = False
        self.async_write_ha_state()  # Update UI immediately

        local = _local_transport(self.coordinator)
        if local:
            try:
                await local.set_outlet(self._outlet_position, False)
                # If that was the last active outlet, end the shower entirely —
                # decided from a FRESH local read, not stale coordinator data.
                state = await local.read_state()
                if not any(state["outlets"].values()):
                    _LOGGER.debug("Last outlet off — stopping shower (main off)")
                    await local.set_main(False)
                return
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
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
            await self._cloud_set_outlets(False)
        # State will be confirmed via Pusher client-state-reported event

    async def _cloud_set_outlets(self, active: bool) -> None:
        """Cloud fallback: outlets_set with this outlet toggled, others kept."""
        device_data = self.coordinator.data[self._serial_number]
        outlets = device_data.get(ATTR_OUTLETS, [])
        new_outlet_states = []
        for outlet in outlets:
            pos = outlet.get("position")
            if pos == self._outlet_position:
                new_outlet_states.append({"position": pos, "active": active})
            else:
                new_outlet_states.append({"position": pos, "active": outlet.get("active", False)})
        device_details = await self._api.get_device_details(self._serial_number)
        channel_id = device_details.get("channel")
        if channel_id:
            await self._api.send_control_event(channel_id, "outlets_set", {"outlets": new_outlet_states})

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