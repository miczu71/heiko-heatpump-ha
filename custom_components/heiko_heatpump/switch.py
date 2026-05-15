"""Switch platform for the Heiko Heat Pump integration."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HeikoCoordinator
from .entity import HeikoBaseEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class HeikoSwitchEntityDescription:
    key: str
    name: str
    icon: str
    read_key: str
    write: Callable[[HeikoCoordinator, bool], Awaitable[None]]
    # inverted=True: pump stores 0.0=on, 1.0=off (e.g. HBH)
    inverted: bool = field(default=False)


_SWITCH_DESCS: list[HeikoSwitchEntityDescription] = [
    HeikoSwitchEntityDescription(
        key="power_switch",
        name="Heat Pump Power",
        icon="mdi:heat-pump",
        read_key="Power_State",
        write=lambda coord, v: coord.async_set_power(v),
    ),
    HeikoSwitchEntityDescription(
        key="heating_curve_switch",
        name="Heating Curve",
        icon="mdi:chart-bell-curve",
        read_key="HeatingCurve_State",
        write=lambda coord, v: coord.async_set_heating_curve(v),
    ),
    HeikoSwitchEntityDescription(
        key="hbh_switch",
        name="Backup Heater (HBH)",
        icon="mdi:radiator",
        read_key="HBH_State",
        write=lambda coord, v: coord.async_set_hbh(v),
        inverted=True,
    ),
    HeikoSwitchEntityDescription(
        key="dhw_storage_switch",
        name="DHW Storage",
        icon="mdi:water-boiler",
        read_key="DHWStorage_State",
        write=lambda coord, v: coord.async_set_dhw_storage(v),
    ),
    HeikoSwitchEntityDescription(
        key="anti_leg_switch",
        name="Anti-Legionella Program",
        icon="mdi:bacteria",
        read_key="Anti_Leg_Program",
        write=lambda coord, v: coord.async_set_anti_leg_program(v),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HeikoCoordinator = hass.data[DOMAIN][entry.entry_id]
    mn_str = entry.data["mn"]
    async_add_entities([
        HeikoSwitchEntity(coordinator, mn_str, desc)
        for desc in _SWITCH_DESCS
    ])


class HeikoSwitchEntity(HeikoBaseEntity, SwitchEntity):
    """Generic switch entity for Heiko heat pump boolean settings.

    State is read back from CMD 0x02 setdata frames (via coordinator.data).
    Optimistic state is applied immediately on write and cleared once the
    coordinator receives a confirming setdata frame with the new value.
    """

    def __init__(
        self,
        coordinator: HeikoCoordinator,
        mn_str: str,
        desc: HeikoSwitchEntityDescription,
    ) -> None:
        super().__init__(coordinator, mn_str, desc.key)
        self._attr_name = desc.name
        self._attr_icon = desc.icon
        self._desc = desc
        self._optimistic_state: bool | None = None

    @property
    def is_on(self) -> bool | None:
        if self._optimistic_state is not None:
            return self._optimistic_state
        v = self.coordinator.data.get(self._desc.read_key) if self.coordinator.data else None
        if v is None:
            return None
        raw_on = round(v) == 1
        return (not raw_on) if self._desc.inverted else raw_on

    @property
    def assumed_state(self) -> bool:
        return self._optimistic_state is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._optimistic_state = True
        self.async_write_ha_state()
        try:
            await self._desc.write(self.coordinator, True)
        except Exception:
            _LOGGER.exception("Failed to turn on %s", self._attr_name)
            self._optimistic_state = None
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._optimistic_state = False
        self.async_write_ha_state()
        try:
            await self._desc.write(self.coordinator, False)
        except Exception:
            _LOGGER.exception("Failed to turn off %s", self._attr_name)
            self._optimistic_state = None
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        # Clear optimistic state once coordinator.data reflects the expected value
        if self._optimistic_state is not None and self.coordinator.data:
            v = self.coordinator.data.get(self._desc.read_key)
            if v is not None:
                raw_on = round(v) == 1
                actual = (not raw_on) if self._desc.inverted else raw_on
                if actual == self._optimistic_state:
                    self._optimistic_state = None
        self.async_write_ha_state()
