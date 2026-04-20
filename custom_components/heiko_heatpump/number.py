"""
Number platform for the Heiko Heat Pump integration.

Exposes adjustable numeric controls:
  - DHW setpoint (write index 54, confirmed by traffic capture)

Heating setpoint is read-only (depends on the heating curve) and is
available as a sensor entity (sensor.heiko_heat_pump_heating_water_setpoint).
"""

from __future__ import annotations
import logging

from homeassistant.components.number import (
    NumberEntity, NumberEntityDescription, NumberMode,
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


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HeikoCoordinator = hass.data[DOMAIN][entry.entry_id]
    mn_str = entry.data["mn"]
    async_add_entities([
        HeikoNumberEntity(
            coordinator, mn_str,
            key="dhw_setpoint",
            name="DHW Setpoint",
            icon="mdi:water-boiler",
            min_value=40.0,
            max_value=60.0,
            step=0.5,
            unit=UnitOfTemperature.CELSIUS,
            coordinator_read_key='DHW_Setpoint',  # populated from CMD 0x02 setdata frame
            write_coro="async_set_dhw_setpoint",
        ),
    ])


class HeikoNumberEntity(CoordinatorEntity[HeikoCoordinator], NumberEntity):
    """A numeric control entity that reads from and writes to the heat pump."""

    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: HeikoCoordinator,
        mn_str: str,
        key: str,
        name: str,
        icon: str,
        min_value: float,
        max_value: float,
        step: float,
        unit: str,
        coordinator_read_key: str | None,
        write_coro: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id        = f"{mn_str}_{key}"
        self._attr_name             = name
        self._attr_icon             = icon
        self._attr_native_min_value = min_value
        self._attr_native_max_value = max_value
        self._attr_native_step      = step
        self._attr_native_unit_of_measurement = unit
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mn_str)},
            name="Heiko Heat Pump",
            manufacturer=MANUFACTURER,
            model=MODEL,
        )
        self._read_key   = coordinator_read_key
        self._write_coro = write_coro
        self._optimistic: float | None = None

    @property
    def native_value(self) -> float | None:
        if self._optimistic is not None:
            return self._optimistic
        if not self._read_key or not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._read_key)

    async def async_set_native_value(self, value: float) -> None:
        value = max(self._attr_native_min_value,
                    min(self._attr_native_max_value, value))
        self._optimistic = value
        self.async_write_ha_state()
        try:
            coro = getattr(self.coordinator, self._write_coro)
            await coro(value)
        except Exception as exc:
            _LOGGER.error("Failed to set %s to %.1f: %s", self._attr_name, value, exc)
            self._optimistic = None
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        # Only clear optimistic state once the coordinator actually has a
        # confirmed readback value for this entity's key.
        # For DHW_Setpoint this comes from CMD 0x02 (every ~3 min), not
        # CMD 0x01 (every 30s), so we must not clear early.
        if self._read_key and self.coordinator.data:
            if self.coordinator.data.get(self._read_key) is not None:
                self._optimistic = None
        elif not self._read_key:
            # No readback possible — keep optimistic until next write
            pass
        self.async_write_ha_state()
