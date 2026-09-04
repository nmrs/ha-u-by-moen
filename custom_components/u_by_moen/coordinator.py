"""Data update coordinator for U by Moen."""
from datetime import timedelta
import logging
from typing import Any, Dict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MoenApi, MoenApiError
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


class MoenDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Moen data from the API."""

    def __init__(self, hass: HomeAssistant, api: MoenApi) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.api = api
        self.local = None  # Optional MoenLocal — set by __init__ when pairing file exists
        self.devices: Dict[str, Dict[str, Any]] = {}

    async def _async_merge_local(self, devices_data: Dict[str, Dict[str, Any]]) -> None:
        """Overlay freshly-read local HAP state onto the cloud device data."""
        if not self.local:
            return
        try:
            state = await self.local.read_state()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Local HAP read failed, using cloud data only: %s", err)
            return
        for device_data in devices_data.values():
            device_data["mode"] = "adjusting" if state["main"] else "off"
            device_data["current_temperature"] = state["current_temp_f"]
            device_data["target_temperature"] = state["target_temp_f"]
            for outlet in device_data.get("outlets", []):
                pos = outlet.get("position")
                if pos in state["outlets"]:
                    outlet["active"] = state["outlets"][pos]

    async def _async_update_data(self) -> Dict[str, Dict[str, Any]]:
        """Fetch data from API."""
        try:
            # Get list of devices
            devices_list = await self.api.get_devices()

            # Get detailed info for each device
            devices_data = {}
            for device in devices_list:
                serial_number = device["serial_number"]
                try:
                    device_details = await self.api.get_device_details(serial_number)
                    devices_data[serial_number] = device_details
                except MoenApiError as err:
                    _LOGGER.error(
                        "Failed to get details for device %s: %s", serial_number, err
                    )
                    # Keep existing data if update fails
                    if serial_number in self.devices:
                        devices_data[serial_number] = self.devices[serial_number]

            # Local HAP reads are the source of truth for outlets/temps/mode
            await self._async_merge_local(devices_data)

            self.devices = devices_data
            return devices_data

        except MoenApiError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    def update_device_from_pusher(
        self, serial_number: str, update_data: Dict[str, Any]
    ) -> None:
        """Update device data from Pusher event."""
        if serial_number in self.devices:
            # Merge the update data into existing device data
            self.devices[serial_number].update(update_data)

            # Notify Home Assistant that data has been updated
            self.async_set_updated_data(self.devices)
            _LOGGER.debug("Updated device %s from Pusher event", serial_number)
