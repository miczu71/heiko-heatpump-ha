"""
Number platform for the Heiko Heat Pump integration.

Exposes adjustable numeric controls read from CMD 0x02 setdata frames:
  - DHW setpoint (write index 54)
  - Heating curve parallel shift (write index 120)
  - Heating/cooling stop ΔT (write index 19)
  - Heating/cooling restart ΔT (write index 20)
  - DHW restart ΔT (write index 55)
  - Heating curve ambient breakpoints 1–5 (write indices 24–28)
  - Heating curve water temp breakpoints 1–5 (write indices 29–33)

All values are always read from the pump via CMD 0x02; entities show None
until the first setdata frame arrives (~3 min after connection).
"""

from __future__ import annotations
import logging

from homeassistant.components.number import (
    NumberEntity, NumberEntityDescription, NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime
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
    entities: list[HeikoNumberEntity] = [
        HeikoNumberEntity(
            coordinator, mn_str,
            key="dhw_setpoint",
            name="DHW Setpoint",
            icon="mdi:water-boiler",
            min_value=40.0,
            max_value=60.0,
            step=1.0,
            unit=UnitOfTemperature.CELSIUS,
            coordinator_read_key="DHW_Setpoint",
            write_coro="async_set_dhw_setpoint",
        ),
        HeikoNumberEntity(
            coordinator, mn_str,
            key="curve_parallel",
            name="HC Parallel",
            icon="mdi:chart-line",
            min_value=-9.0,
            max_value=9.0,
            step=1.0,
            unit=UnitOfTemperature.CELSIUS,
            coordinator_read_key="Curve_Parallel",
            write_coro="async_set_curve_parallel",
        ),
        HeikoNumberEntity(
            coordinator, mn_str,
            key="heating_stops_dt",
            name="Heating Stops ΔT",
            icon="mdi:thermometer-chevron-up",
            min_value=1.0,
            max_value=15.0,
            step=1.0,
            unit=UnitOfTemperature.CELSIUS,
            coordinator_read_key="Heating_Stops_DT",
            write_coro="async_set_heating_stops_dt",
        ),
        HeikoNumberEntity(
            coordinator, mn_str,
            key="heating_restarts_dt",
            name="Heating Restarts ΔT",
            icon="mdi:thermometer-chevron-down",
            min_value=1.0,
            max_value=15.0,
            step=1.0,
            unit=UnitOfTemperature.CELSIUS,
            coordinator_read_key="Heating_Restarts_DT",
            write_coro="async_set_heating_restarts_dt",
        ),
        HeikoNumberEntity(
            coordinator, mn_str,
            key="dhw_restart_dt",
            name="DHW Restart ΔT",
            icon="mdi:thermometer-water",
            min_value=1.0,
            max_value=15.0,
            step=1.0,
            unit=UnitOfTemperature.CELSIUS,
            coordinator_read_key="DHW_Restart_DT",
            write_coro="async_set_dhw_restart_dt",
        ),
    ]

    # Heating curve ambient temperature breakpoints (points 1–5)
    for pt in range(1, 6):
        entities.append(HeikoNumberEntity(
            coordinator, mn_str,
            key=f"curve_amb_{pt}",
            name=f"HC Amb {pt}",
            icon="mdi:thermometer-lines",
            min_value=-25.0,
            max_value=20.0,
            step=1.0,
            unit=UnitOfTemperature.CELSIUS,
            coordinator_read_key=f"Curve_Amb_{pt}",
            write_coro=f"async_set_curve_amb_{pt}",
        ))

    # Heating curve water temperature breakpoints (points 1–5)
    for pt in range(1, 6):
        entities.append(HeikoNumberEntity(
            coordinator, mn_str,
            key=f"curve_water_{pt}",
            name=f"HC Water {pt}",
            icon="mdi:water-thermometer",
            min_value=15.0,
            max_value=60.0,
            step=1.0,
            unit=UnitOfTemperature.CELSIUS,
            coordinator_read_key=f"Curve_Water_{pt}",
            write_coro=f"async_set_curve_water_{pt}",
        ))

    # Anti-Legionella numbers (confirmed by CMD 0x05 MITM capture, setdata idx 41-43)
    entities += [
        HeikoNumberEntity(
            coordinator, mn_str,
            key="anti_leg_setpoint",
            name="Anti-Legionella Setpoint",
            icon="mdi:thermometer-high",
            min_value=40.0,
            max_value=70.0,
            step=1.0,
            unit=UnitOfTemperature.CELSIUS,
            coordinator_read_key="Anti_Leg_Setpoint",
            write_coro="async_set_anti_leg_setpoint",
        ),
        HeikoNumberEntity(
            coordinator, mn_str,
            key="anti_leg_duration",
            name="Anti-Legionella Duration",
            icon="mdi:timer",
            min_value=1.0,
            max_value=120.0,
            step=1.0,
            unit=UnitOfTime.MINUTES,
            coordinator_read_key="Anti_Leg_Duration",
            write_coro="async_set_anti_leg_duration",
        ),
        HeikoNumberEntity(
            coordinator, mn_str,
            key="anti_leg_finish",
            name="Anti-Legionella Finish Time",
            icon="mdi:timer-check",
            min_value=1.0,
            max_value=240.0,
            step=1.0,
            unit=UnitOfTime.MINUTES,
            coordinator_read_key="Anti_Leg_Finish",
            write_coro="async_set_anti_leg_finish",
        ),
    ]

    async_add_entities(entities)


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
            val = self._optimistic
        elif not self._read_key or not self.coordinator.data:
            return None
        else:
            val = self.coordinator.data.get(self._read_key)
        if val is None:
            return None
        if self._attr_native_step == 1.0:
            return int(val)
        return val

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
