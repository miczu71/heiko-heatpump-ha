"""
Climate platform for the Heiko Heat Pump integration.

Reads:
  - WorkingMode (index 20, cloud par18): 0=Standby, 1=DHW, 2=Heat, 3=Cool,
    4=DHW+Heat, 5=DHW+Cool — used to determine current hvac_mode.
  - Setpoint (index 38, cloud par36): heating water setpoint in °C.
  - Tw (index 8, cloud par7): water / DHW temperature, shown as current temp.

Writes via CMD 0x05:
  - Power on/off at index 39 (community table "Sw").
  - Heating setpoint at index 38.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import HeikoCoordinator

_LOGGER = logging.getLogger(__name__)

MIN_SETPOINT  = 20.0
MAX_SETPOINT  = 60.0
SETPOINT_STEP = 0.5

# WorkingMode register (index 20, par18) → HA HVACMode
_MODE_TO_HVAC: dict[int, HVACMode] = {
    0: HVACMode.OFF,
    1: HVACMode.HEAT,   # DHW only
    2: HVACMode.HEAT,   # Heating
    3: HVACMode.COOL,   # Cooling
    4: HVACMode.HEAT,   # DHW + Heating
    5: HVACMode.COOL,   # DHW + Cooling
}

_MODE_NAMES = {
    0: "Standby", 1: "DHW", 2: "Heating", 3: "Cooling",
    4: "DHW + Heating", 5: "DHW + Cooling",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HeikoCoordinator = hass.data[DOMAIN][entry.entry_id]
    mn_str = entry.data["mn"]
    async_add_entities([HeikoClimateEntity(coordinator, mn_str)])


class HeikoClimateEntity(CoordinatorEntity[HeikoCoordinator], ClimateEntity):
    """
    Climate entity for the Heiko heat pump.

    hvac_mode is read from WorkingMode (index 20, par18):
      0=Standby → OFF
      1=DHW, 2=Heating, 4=DHW+Heating → HEAT
      3=Cooling, 5=DHW+Cooling → COOL

    target_temperature = Setpoint register (index 38, par36, e.g. 22.0°C).
    current_temperature = Tw register (index 8, par7 — water/DHW temp).
    """

    _attr_name                    = "Heat Pump"
    _attr_icon                    = "mdi:heat-pump"
    _attr_temperature_unit        = UnitOfTemperature.CELSIUS
    _attr_hvac_modes              = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL]
    _attr_supported_features      = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_min_temp                = MIN_SETPOINT
    _attr_max_temp                = MAX_SETPOINT
    _attr_target_temperature_step = SETPOINT_STEP

    def __init__(self, coordinator: HeikoCoordinator, mn_str: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{mn_str}_climate"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mn_str)},
            name="Heiko Heat Pump",
            manufacturer=MANUFACTURER,
            model=MODEL,
        )
        self._optimistic_setpoint: float | None = None
        self._optimistic_mode: HVACMode | None  = None

    @property
    def hvac_mode(self) -> HVACMode | None:
        if self._optimistic_mode is not None:
            return self._optimistic_mode
        if not self.coordinator.data:
            return None
        wm = self.coordinator.data.get("WorkingMode")
        if wm is None:
            return None
        return _MODE_TO_HVAC.get(int(round(wm)), HVACMode.OFF)

    @property
    def target_temperature(self) -> float | None:
        """Heating water setpoint (index 38, par36)."""
        if self._optimistic_setpoint is not None:
            return self._optimistic_setpoint
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("Setpoint")

    @property
    def current_temperature(self) -> float | None:
        """Water/DHW temperature (index 8, par7)."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("Tw")

    @property
    def extra_state_attributes(self) -> dict:
        """Expose raw working mode number and name as extra attributes."""
        if not self.coordinator.data:
            return {}
        wm = self.coordinator.data.get("WorkingMode")
        if wm is None:
            return {}
        wm_int = int(round(wm))
        return {
            "working_mode_raw": wm_int,
            "working_mode_name": _MODE_NAMES.get(wm_int, f"Unknown ({wm_int})"),
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._optimistic_mode = hvac_mode
        self.async_write_ha_state()
        try:
            await self.coordinator.async_set_power(hvac_mode != HVACMode.OFF)
        except Exception as exc:
            _LOGGER.error("Failed to set HVAC mode %s: %s", hvac_mode, exc)
            self._optimistic_mode = None
            self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get("temperature")
        if temp is None:
            return
        temp = float(max(MIN_SETPOINT, min(MAX_SETPOINT, temp)))
        self._optimistic_setpoint = temp
        self.async_write_ha_state()
        try:
            await self.coordinator.async_set_setpoint(temp)
        except Exception as exc:
            _LOGGER.error("Failed to set temperature %.1f °C: %s", temp, exc)
            self._optimistic_setpoint = None
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        # Both Setpoint and WorkingMode are in the realtime frame, so we
        # can clear both optimistic values when a confirmed frame arrives.
        self._optimistic_setpoint = None
        self._optimistic_mode     = None
        self.async_write_ha_state()
