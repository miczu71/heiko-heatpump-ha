"""Water heater platform for Heiko heat pump — DHW control."""

from __future__ import annotations

from typing import Any

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import HeikoCoordinator
from .protocol import MODE_STANDBY, MODE_HEATING, MODE_COOLING, MODE_DHW, MODE_AUTO

_OP_TO_MODE: dict[str, int] = {
    "Standby": MODE_STANDBY,
    "Heating": MODE_HEATING,
    "Cooling": MODE_COOLING,
    "DHW":     MODE_DHW,
    "Auto":    MODE_AUTO,
}
_MODE_TO_OP: dict[int, str] = {v: k for k, v in _OP_TO_MODE.items()}
OPERATION_LIST = list(_OP_TO_MODE)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HeikoCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HeikoDHWWaterHeater(coordinator, entry)])


class HeikoDHWWaterHeater(CoordinatorEntity[HeikoCoordinator], WaterHeaterEntity):
    """Domestic hot water control via the water_heater platform."""

    _attr_name = "DHW"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 40.0
    _attr_max_temp = 60.0
    _attr_target_temperature_step = 1.0
    _attr_operation_list = OPERATION_LIST
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
    )

    def __init__(self, coordinator: HeikoCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        mn_str = entry.data["mn"]
        self._attr_unique_id = f"{mn_str}_dhw_water_heater"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mn_str)},
            name="Heiko Heat Pump",
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def current_temperature(self) -> float | None:
        return self.coordinator.data.get("Tw") if self.coordinator.data else None

    @property
    def target_temperature(self) -> float | None:
        return self.coordinator.data.get("DHW_Setpoint") if self.coordinator.data else None

    @property
    def current_operation(self) -> str | None:
        if not self.coordinator.data:
            return None
        raw = self.coordinator.data.get("Mode_Setdata")
        if raw is None:
            return None
        return _MODE_TO_OP.get(int(round(raw)), "Standby")

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is not None:
            await self.coordinator.async_set_dhw_setpoint(float(temp))

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        mode = _OP_TO_MODE.get(operation_mode)
        if mode is not None:
            await self.coordinator.async_set_mode(mode)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
