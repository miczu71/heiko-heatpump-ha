"""
Climate platform for the Heiko Heat Pump integration.

Target temperature: DHW setpoint (write index 54, 40–60°C, step 1°C).
Current temperature: Tw — hot water / DHW temperature (read index 8).

HVAC modes (power state):
  OFF  → pump standby (power off)
  HEAT → pump active (any non-standby working mode)

Preset modes (working mode — mirrors select.heiko_heat_pump_working_mode):
  Heating / DHW / Auto / Cooling

WorkingMode read values from CMD 0x01 (PARAM_MAP idx 2):
  0=Standby, 1=DHW, 2=Heating, 3=Cooling, 4=DHW+Heating, 5=DHW+Cooling
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
from .protocol import MODE_HEATING, MODE_COOLING, MODE_DHW, MODE_AUTO

_LOGGER = logging.getLogger(__name__)

DHW_MIN  = 40.0
DHW_MAX  = 60.0
DHW_STEP = 1.0

# WorkingMode (read from pump) → preset label
_WORKING_MODE_TO_PRESET: dict[int, str] = {
    1: "DHW",
    2: "Heating",
    3: "Cooling",
    4: "Auto",
    5: "Auto",
}

# Preset label → protocol write value (write index 3)
_PRESET_TO_MODE: dict[str, int] = {
    "Heating": MODE_HEATING,
    "DHW":     MODE_DHW,
    "Auto":    MODE_AUTO,
    "Cooling": MODE_COOLING,
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HeikoCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HeikoClimateEntity(coordinator, entry.data["mn"])])


class HeikoClimateEntity(CoordinatorEntity[HeikoCoordinator], ClimateEntity):
    """
    Climate entity for the heat pump.

    HVAC mode (OFF/HEAT) controls power on/off.
    Preset mode (Heating/DHW/Auto/Cooling) controls working mode,
    matching the behaviour of select.heiko_heat_pump_working_mode.
    Target temperature controls DHW setpoint (40–60°C, step 1°C).
    Current temperature is Tw (hot water outlet).
    """

    _attr_name                    = "Heat Pump"
    _attr_icon                    = "mdi:heat-pump"
    _attr_temperature_unit        = UnitOfTemperature.CELSIUS
    _attr_hvac_modes              = [HVACMode.OFF, HVACMode.HEAT]
    _attr_preset_modes            = ["Heating", "DHW", "Auto", "Cooling"]
    _attr_supported_features      = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
    )
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
        self._optimistic_mode:     HVACMode | None = None
        self._optimistic_preset:   str | None      = None
        self._optimistic_setpoint: float | None    = None

    @property
    def hvac_mode(self) -> HVACMode | None:
        if self._optimistic_mode is not None:
            return self._optimistic_mode
        if not self.coordinator.data:
            return None
        # Mode_Setdata: 0=Standby (off), anything else = active
        wm = self.coordinator.data.get("Mode_Setdata")
        if wm is None:
            return None
        return HVACMode.OFF if int(round(wm)) == 0 else HVACMode.HEAT

    @property
    def preset_mode(self) -> str | None:
        if self._optimistic_preset is not None:
            return self._optimistic_preset
        if not self.coordinator.data:
            return None
        wm = self.coordinator.data.get("Mode_Setdata")
        if wm is None:
            return None
        return _WORKING_MODE_TO_PRESET.get(int(round(wm)))

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
        """OFF → power off; HEAT → power on (retains current preset/mode)."""
        self._optimistic_mode = hvac_mode
        self.async_write_ha_state()
        try:
            await self.coordinator.async_set_power(hvac_mode != HVACMode.OFF)
        except Exception as exc:
            _LOGGER.error("Failed to set HVAC mode %s: %s", hvac_mode, exc)
            self._optimistic_mode = None
            self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set working mode — same action as select.heiko_heat_pump_working_mode."""
        mode_val = _PRESET_TO_MODE.get(preset_mode)
        if mode_val is None:
            _LOGGER.error("Unknown preset: %s", preset_mode)
            return
        self._optimistic_preset = preset_mode
        self._optimistic_mode   = HVACMode.HEAT
        self.async_write_ha_state()
        try:
            await self.coordinator.async_set_power(True)
            await self.coordinator.async_set_mode(mode_val)
        except Exception as exc:
            _LOGGER.error("Failed to set preset %s: %s", preset_mode, exc)
            self._optimistic_preset = None
            self._optimistic_mode   = None
            self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Write DHW setpoint (index 54, 40–60°C)."""
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
            if self.coordinator.data.get("Mode_Setdata") is not None:
                self._optimistic_mode   = None
                self._optimistic_preset = None
            if self.coordinator.data.get("DHW_Setpoint") is not None:
                self._optimistic_setpoint = None
        self.async_write_ha_state()
