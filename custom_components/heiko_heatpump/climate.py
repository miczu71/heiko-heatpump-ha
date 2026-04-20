"""
Climate platform for the Heiko Heat Pump integration.

Target temperature: DHW setpoint (write index 54, 40–60°C).
Current temperature: Tw — hot water / DHW temperature (read index 8).
HVAC mode: derived from WorkingMode in CMD 0x01 realtime data (read index 2).

WorkingMode read values (from pump realtime data):
  0 = Standby        → HVACMode.OFF
  1 = DHW            → HVACMode.HEAT
  2 = Heating        → HVACMode.HEAT
  3 = Cooling        → HVACMode.COOL
  4 = DHW + Heating  → HVACMode.HEAT
  5 = DHW + Cooling  → HVACMode.HEAT

Note: write mode values differ from read values; use the select entity for
precise mode control. The climate entity maps OFF→power off, HEAT/COOL→power on.
Heating setpoint is shown via a read-only sensor entity (not controllable here).
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

_LOGGER = logging.getLogger(__name__)

DHW_MIN  = 40.0
DHW_MAX  = 60.0
DHW_STEP = 0.5

# WorkingMode values as read from CMD 0x01 realtime data (PARAM_MAP idx 2)
_WORKING_MODE_TO_HVAC: dict[int, HVACMode] = {
    0: HVACMode.OFF,   # Standby
    1: HVACMode.HEAT,  # DHW / Sanitary Hot Water
    2: HVACMode.HEAT,  # Heating
    3: HVACMode.COOL,  # Cooling
    4: HVACMode.HEAT,  # DHW + Heating
    5: HVACMode.HEAT,  # DHW + Cooling
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HeikoCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HeikoClimateEntity(coordinator, entry.data["mn"])])


class HeikoClimateEntity(CoordinatorEntity[HeikoCoordinator], ClimateEntity):
    """
    Climate entity centred on DHW (sanitary hot water) control.

    Target temperature = DHW setpoint (index 54, 40–60°C).
    Current temperature = Tw (hot water outlet, index 8).
    HVAC mode is read from WorkingMode (index 2) — use the Working Mode select
    entity for precise mode selection. Setting OFF here powers the pump off;
    setting HEAT powers it back on (retaining the last active mode).
    """

    _attr_name                    = "Heat Pump"
    _attr_icon                    = "mdi:heat-pump"
    _attr_temperature_unit        = UnitOfTemperature.CELSIUS
    _attr_hvac_modes              = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL]
    _attr_supported_features      = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_min_temp                = DHW_MIN
    _attr_max_temp                = DHW_MAX
    _attr_target_temperature_step = DHW_STEP

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
        return _WORKING_MODE_TO_HVAC.get(int(round(wm)), HVACMode.OFF)

    @property
    def target_temperature(self) -> float | None:
        if self._optimistic_setpoint is not None:
            return self._optimistic_setpoint
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("DHW_Setpoint")

    @property
    def current_temperature(self) -> float | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("Tw")

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._optimistic_mode = hvac_mode
        self.async_write_ha_state()
        try:
            if hvac_mode == HVACMode.OFF:
                await self.coordinator.async_set_power(False)
            else:
                await self.coordinator.async_set_power(True)
        except Exception as exc:
            _LOGGER.error("Failed to set HVAC mode %s: %s", hvac_mode, exc)
            self._optimistic_mode = None
            self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Write DHW setpoint (index 54)."""
        temp = kwargs.get("temperature")
        if temp is None:
            return
        temp = float(max(DHW_MIN, min(DHW_MAX, temp)))
        self._optimistic_setpoint = temp
        self.async_write_ha_state()
        try:
            await self.coordinator.async_set_dhw_setpoint(temp)
        except Exception as exc:
            _LOGGER.error("Failed to set DHW setpoint %.1f°C: %s", temp, exc)
            self._optimistic_setpoint = None
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.coordinator.data:
            if self.coordinator.data.get("WorkingMode") is not None:
                self._optimistic_mode = None
            if self.coordinator.data.get("DHW_Setpoint") is not None:
                self._optimistic_setpoint = None
        self.async_write_ha_state()
