"""Switch platform for the Heiko Heat Pump integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import HeikoCoordinator

_LOGGER = logging.getLogger(__name__)

# (name, icon, unique_id_suffix, coordinator_data_key, write_method, inverted)
# inverted=True means pump stores 0.0=on, 1.0=off (e.g. HBH)
_SWITCH_DEFS = [
    (
        "Heat Pump Power",
        "mdi:heat-pump",
        "power_switch",
        "Power_State",
        "async_set_power",
        False,
    ),
    (
        "Heating Curve",
        "mdi:chart-bell-curve",
        "heating_curve_switch",
        "HeatingCurve_State",
        "async_set_heating_curve",
        False,
    ),
    (
        "Backup Heater (HBH)",
        "mdi:radiator",
        "hbh_switch",
        "HBH_State",
        "async_set_hbh",
        True,  # pump: 0.0=enabled(on), 1.0=disabled(off)
    ),
    (
        "DHW Storage",
        "mdi:water-boiler",
        "dhw_storage_switch",
        "DHWStorage_State",
        "async_set_dhw_storage",
        False,
    ),
    (
        "Anti-Legionella Program",
        "mdi:bacteria",
        "anti_leg_switch",
        "Anti_Leg_Program",
        "async_set_anti_leg_program",
        False,
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
        HeikoSwitchEntity(coordinator, mn_str, *defn)
        for defn in _SWITCH_DEFS
    ])


class HeikoSwitchEntity(CoordinatorEntity[HeikoCoordinator], SwitchEntity):
    """Generic switch entity for Heiko heat pump boolean settings.

    State is read back from CMD 0x02 setdata frames (via coordinator.data).
    Optimistic state is applied immediately on write and cleared once the
    coordinator receives a confirming setdata frame with the new value.
    """

    def __init__(
        self,
        coordinator: HeikoCoordinator,
        mn_str: str,
        name: str,
        icon: str,
        unique_id_suffix: str,
        data_key: str,
        write_method: str,
        inverted: bool,
    ) -> None:
        super().__init__(coordinator)
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{mn_str}_{unique_id_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mn_str)},
            name="Heiko Heat Pump",
            manufacturer=MANUFACTURER,
            model=MODEL,
        )
        self._data_key = data_key
        self._write_method = write_method
        self._inverted = inverted
        self._optimistic_state: bool | None = None

    @property
    def is_on(self) -> bool | None:
        if self._optimistic_state is not None:
            return self._optimistic_state
        v = self.coordinator.data.get(self._data_key) if self.coordinator.data else None
        if v is None:
            return None
        raw_on = round(v) == 1
        return (not raw_on) if self._inverted else raw_on

    @property
    def assumed_state(self) -> bool:
        return self._optimistic_state is not None

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._optimistic_state = True
        self.async_write_ha_state()
        try:
            await getattr(self.coordinator, self._write_method)(True)
        except Exception as exc:
            _LOGGER.error("Failed to turn on %s: %s", self._attr_name, exc)
            self._optimistic_state = None
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._optimistic_state = False
        self.async_write_ha_state()
        try:
            await getattr(self.coordinator, self._write_method)(False)
        except Exception as exc:
            _LOGGER.error("Failed to turn off %s: %s", self._attr_name, exc)
            self._optimistic_state = None
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        # Clear optimistic state once coordinator.data reflects the expected value
        if self._optimistic_state is not None and self.coordinator.data:
            v = self.coordinator.data.get(self._data_key)
            if v is not None:
                raw_on = round(v) == 1
                actual = (not raw_on) if self._inverted else raw_on
                if actual == self._optimistic_state:
                    self._optimistic_state = None
        self.async_write_ha_state()
