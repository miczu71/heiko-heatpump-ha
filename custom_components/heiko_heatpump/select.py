"""
Select platform for the Heiko Heat Pump integration.

Provides a dropdown to select the working mode directly.
Write index 3 confirmed by CMD 0x05 traffic capture.

Modes confirmed:
  1 = Heating  ✓
  3 = DHW (Sanitary Hot Water)  ✓
  4 = Auto  ✓
  0 = Standby (assumed — power-off state)
  2 = Cooling (assumed — logical extension)
"""

from __future__ import annotations
import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import HeikoCoordinator
from .protocol import (
    MODE_STANDBY, MODE_HEATING, MODE_COOLING, MODE_DHW, MODE_AUTO,
)

_LOGGER = logging.getLogger(__name__)

# Human label → protocol mode value
_OPTIONS: dict[str, int] = {
    "Standby":  MODE_STANDBY,
    "Heating":  MODE_HEATING,
    "Cooling":  MODE_COOLING,
    "DHW":      MODE_DHW,
    "Auto":     MODE_AUTO,
}
_VALUE_TO_LABEL = {v: k for k, v in _OPTIONS.items()}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HeikoCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HeikoModeSelectEntity(coordinator, entry.data["mn"])])


class HeikoModeSelectEntity(CoordinatorEntity[HeikoCoordinator], SelectEntity):
    """
    Dropdown select for heat pump working mode.
    Reads from WorkingMode sensor (index 2, par1).
    Writes to mode register (index 3) — also turns power on if currently off.
    Selecting 'Standby' turns the pump off (writes power index 0 → 0.0).
    """

    _attr_name    = "Working Mode"
    _attr_icon    = "mdi:cog-transfer"
    _attr_options = list(_OPTIONS.keys())

    def __init__(self, coordinator: HeikoCoordinator, mn_str: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{mn_str}_mode_select"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mn_str)},
            name="Heiko Heat Pump",
            manufacturer=MANUFACTURER,
            model=MODEL,
        )
        self._optimistic: str | None = None

    @property
    def current_option(self) -> str | None:
        if self._optimistic is not None:
            return self._optimistic
        if not self.coordinator.data:
            return None
        wm = self.coordinator.data.get("WorkingMode")
        if wm is None:
            return None
        return _VALUE_TO_LABEL.get(int(round(wm)))

    async def async_select_option(self, option: str) -> None:
        mode_val = _OPTIONS.get(option)
        if mode_val is None:
            _LOGGER.error("Unknown mode option: %s", option)
            return

        self._optimistic = option
        self.async_write_ha_state()
        try:
            if option == "Standby":
                # Turn power off — pump enters standby
                await self.coordinator.async_set_power(False)
            else:
                # Ensure power is on, then set mode
                await self.coordinator.async_set_power(True)
                await self.coordinator.async_set_mode(mode_val)
        except Exception as exc:
            _LOGGER.error("Failed to set mode to %s: %s", option, exc)
            self._optimistic = None
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._optimistic = None
        self.async_write_ha_state()
