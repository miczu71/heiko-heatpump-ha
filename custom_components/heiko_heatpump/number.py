"""
Number platform for the Heiko Heat Pump integration.

Exposes adjustable numeric controls read from CMD 0x02 setdata frames.
All values are read from the pump; entities show None until the first
setdata frame arrives (~3 min after connection).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HeikoCoordinator
from .entity import HeikoBaseEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class HeikoNumberEntityDescription:
    key: str
    name: str
    icon: str
    min_value: float
    max_value: float
    step: float
    unit: str
    read_key: str | None
    write: Callable[[HeikoCoordinator, float], Awaitable[None]]


def _amb_write(pt: int) -> Callable[[HeikoCoordinator, float], Awaitable[None]]:
    async def _w(coord: HeikoCoordinator, v: float) -> None:
        await getattr(coord, f"async_set_curve_amb_{pt}")(v)
    return _w


def _water_write(pt: int) -> Callable[[HeikoCoordinator, float], Awaitable[None]]:
    async def _w(coord: HeikoCoordinator, v: float) -> None:
        await getattr(coord, f"async_set_curve_water_{pt}")(v)
    return _w


_BASE_DESCS: list[HeikoNumberEntityDescription] = [
    HeikoNumberEntityDescription(
        key="dhw_setpoint",
        name="DHW Setpoint",
        icon="mdi:water-boiler",
        min_value=40.0, max_value=60.0, step=1.0,
        unit=UnitOfTemperature.CELSIUS,
        read_key="DHW_Setpoint",
        write=lambda coord, v: coord.async_set_dhw_setpoint(v),
    ),
    HeikoNumberEntityDescription(
        key="curve_parallel",
        name="HC Parallel",
        icon="mdi:chart-line",
        min_value=-9.0, max_value=9.0, step=1.0,
        unit=UnitOfTemperature.CELSIUS,
        read_key="Curve_Parallel",
        write=lambda coord, v: coord.async_set_curve_parallel(v),
    ),
    HeikoNumberEntityDescription(
        key="heating_stops_dt",
        name="Heating Stops ΔT",
        icon="mdi:thermometer-chevron-up",
        min_value=1.0, max_value=15.0, step=1.0,
        unit=UnitOfTemperature.CELSIUS,
        read_key="Heating_Stops_DT",
        write=lambda coord, v: coord.async_set_heating_stops_dt(v),
    ),
    HeikoNumberEntityDescription(
        key="heating_restarts_dt",
        name="Heating Restarts ΔT",
        icon="mdi:thermometer-chevron-down",
        min_value=1.0, max_value=15.0, step=1.0,
        unit=UnitOfTemperature.CELSIUS,
        read_key="Heating_Restarts_DT",
        write=lambda coord, v: coord.async_set_heating_restarts_dt(v),
    ),
    HeikoNumberEntityDescription(
        key="dhw_restart_dt",
        name="DHW Restart ΔT",
        icon="mdi:thermometer-water",
        min_value=1.0, max_value=15.0, step=1.0,
        unit=UnitOfTemperature.CELSIUS,
        read_key="DHW_Restart_DT",
        write=lambda coord, v: coord.async_set_dhw_restart_dt(v),
    ),
    # Anti-Legionella numbers (write indices 41–43, confirmed MITM)
    HeikoNumberEntityDescription(
        key="anti_leg_setpoint",
        name="Anti-Legionella Setpoint",
        icon="mdi:thermometer-high",
        min_value=40.0, max_value=70.0, step=1.0,
        unit=UnitOfTemperature.CELSIUS,
        read_key="Anti_Leg_Setpoint",
        write=lambda coord, v: coord.async_set_anti_leg_setpoint(v),
    ),
    HeikoNumberEntityDescription(
        key="anti_leg_duration",
        name="Anti-Legionella Duration",
        icon="mdi:timer",
        min_value=1.0, max_value=120.0, step=1.0,
        unit=UnitOfTime.MINUTES,
        read_key="Anti_Leg_Duration",
        write=lambda coord, v: coord.async_set_anti_leg_duration(v),
    ),
    HeikoNumberEntityDescription(
        key="anti_leg_finish",
        name="Anti-Legionella Finish Time",
        icon="mdi:timer-check",
        min_value=1.0, max_value=240.0, step=1.0,
        unit=UnitOfTime.MINUTES,
        read_key="Anti_Leg_Finish",
        write=lambda coord, v: coord.async_set_anti_leg_finish(v),
    ),
]

# Heating curve ambient and water temperature breakpoints (points 1–5)
_CURVE_DESCS: list[HeikoNumberEntityDescription] = [
    *(
        HeikoNumberEntityDescription(
            key=f"curve_amb_{pt}",
            name=f"HC Amb {pt}",
            icon="mdi:thermometer-lines",
            min_value=-25.0, max_value=20.0, step=1.0,
            unit=UnitOfTemperature.CELSIUS,
            read_key=f"Curve_Amb_{pt}",
            write=_amb_write(pt),
        )
        for pt in range(1, 6)
    ),
    *(
        HeikoNumberEntityDescription(
            key=f"curve_water_{pt}",
            name=f"HC Water {pt}",
            icon="mdi:water-thermometer",
            min_value=15.0, max_value=60.0, step=1.0,
            unit=UnitOfTemperature.CELSIUS,
            read_key=f"Curve_Water_{pt}",
            write=_water_write(pt),
        )
        for pt in range(1, 6)
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HeikoCoordinator = hass.data[DOMAIN][entry.entry_id]
    mn_str = entry.data["mn"]
    async_add_entities([
        HeikoNumberEntity(coordinator, mn_str, desc)
        for desc in _BASE_DESCS + _CURVE_DESCS
    ])


class HeikoNumberEntity(HeikoBaseEntity, NumberEntity):
    """A numeric control entity that reads from and writes to the heat pump."""

    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: HeikoCoordinator,
        mn_str: str,
        desc: HeikoNumberEntityDescription,
    ) -> None:
        super().__init__(coordinator, mn_str, desc.key)
        self._attr_name = desc.name
        self._attr_icon = desc.icon
        self._attr_native_min_value = desc.min_value
        self._attr_native_max_value = desc.max_value
        self._attr_native_step = desc.step
        self._attr_native_unit_of_measurement = desc.unit
        self._desc = desc
        self._optimistic: float | None = None

    @property
    def native_value(self) -> float | None:
        val = self._optimistic
        if val is None:
            if not self._desc.read_key or not self.coordinator.data:
                return None
            val = self.coordinator.data.get(self._desc.read_key)
        if val is None:
            return None
        if self._attr_native_step == 1.0:
            return int(val)
        return val

    async def async_set_native_value(self, value: float) -> None:
        value = max(self._attr_native_min_value, min(self._attr_native_max_value, value))
        self._optimistic = value
        self.async_write_ha_state()
        try:
            await self._desc.write(self.coordinator, value)
        except Exception:
            _LOGGER.exception("Failed to set %s to %.1f", self._attr_name, value)
            self._optimistic = None
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        # Only clear optimistic once coordinator has a confirmed readback.
        # DHW_Setpoint comes from CMD 0x02 (~3 min), not CMD 0x01 (30s).
        if self._desc.read_key and self.coordinator.data:
            if self.coordinator.data.get(self._desc.read_key) is not None:
                self._optimistic = None
        self.async_write_ha_state()
