"""
Climate platform for the Heiko Heat Pump integration.

Write indices confirmed by CMD 0x05 traffic capture:
  Power  → index 0  (1.0=on, 0.0=off)
  Mode   → index 3  (1=Heating, 2=Cooling, 3=DHW, 4=Auto, 0=Standby)
  Setpoint → index 37 (heating circuit °C)

Reads:
  WorkingMode (index 2, par1) → current mode
  Setpoint    (index 37)      → current heating setpoint
  Tw          (index 8)       → current water temperature
"""

from __future__ import annotations
import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity, ClimateEntityFeature, HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
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

MIN_SETPOINT  = 20.0
MAX_SETPOINT  = 60.0
SETPOINT_STEP = 0.5

# WorkingMode register value → HA HVACMode
_MODE_TO_HVAC: dict[int, HVACMode] = {
    MODE_STANDBY: HVACMode.OFF,
    MODE_HEATING: HVACMode.HEAT,
    MODE_COOLING: HVACMode.COOL,
    MODE_DHW:     HVACMode.HEAT,   # no dedicated DHW mode in HA; shown as HEAT
    MODE_AUTO:    HVACMode.AUTO,
}

# HA HVACMode → protocol write value
# HEAT writes Heating (1). User can switch to DHW via select entity.
_HVAC_TO_MODE: dict[HVACMode, int] = {
    HVACMode.HEAT: MODE_HEATING,
    HVACMode.COOL: MODE_COOLING,
    HVACMode.AUTO: MODE_AUTO,
}

_MODE_NAMES = {
    0: "Standby", 1: "Heating", 2: "Cooling", 3: "DHW", 4: "Auto",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HeikoCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HeikoClimateEntity(coordinator, entry.data["mn"])])


class HeikoClimateEntity(CoordinatorEntity[HeikoCoordinator], ClimateEntity):
    """
    Climate entity for the heat pump heating circuit.

    Mode is read from WorkingMode (idx 2, par1) and written to index 3.
    Target temperature is the heating setpoint (idx 37).
    Current temperature is Tw (idx 8, water/DHW outlet).

    For DHW setpoint control use the separate number entity (number.heiko_dhw_setpoint).
    For precise mode control (switch to DHW mode) use the select entity.
    """

    _attr_name                    = "Heat Pump"
    _attr_icon                    = "mdi:heat-pump"
    _attr_temperature_unit        = UnitOfTemperature.CELSIUS
    _attr_hvac_modes              = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO]
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
        if self._optimistic_setpoint is not None:
            return self._optimistic_setpoint
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("Setpoint")

    @property
    def current_temperature(self) -> float | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("Tw")

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        wm = self.coordinator.data.get("WorkingMode")
        if wm is None:
            return {}
        wm_int = int(round(wm))
        return {
            "working_mode_raw":  wm_int,
            "working_mode_name": _MODE_NAMES.get(wm_int, f"Unknown ({wm_int})"),
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """
        OFF  → write power 0 (index 0)
        HEAT → write power 1 then mode 1 (Heating)
        COOL → write power 1 then mode 2 (Cooling)
        AUTO → write power 1 then mode 4 (Auto)
        """
        self._optimistic_mode = hvac_mode
        self.async_write_ha_state()
        try:
            if hvac_mode == HVACMode.OFF:
                await self.coordinator.async_set_power(False)
            else:
                mode = _HVAC_TO_MODE.get(hvac_mode, MODE_HEATING)
                await self.coordinator.async_set_power(True)
                await self.coordinator.async_set_mode(mode)
        except Exception as exc:
            _LOGGER.error("Failed to set HVAC mode %s: %s", hvac_mode, exc)
            self._optimistic_mode = None
            self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Write heating circuit setpoint (index 37)."""
        temp = kwargs.get("temperature")
        if temp is None:
            return
        temp = float(max(MIN_SETPOINT, min(MAX_SETPOINT, temp)))
        self._optimistic_setpoint = temp
        self.async_write_ha_state()
        try:
            await self.coordinator.async_set_setpoint(temp)
        except Exception as exc:
            _LOGGER.error("Failed to set temperature %.1f°C: %s", temp, exc)
            self._optimistic_setpoint = None
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._optimistic_setpoint = None
        self._optimistic_mode     = None
        self.async_write_ha_state()
