"""Binary sensor platform for Heiko heat pump."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import HeikoCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HeikoCoordinator = hass.data[DOMAIN][entry.entry_id]
    mn_str = entry.data["mn"]
    async_add_entities([
        HeikoConnectionSensor(coordinator, mn_str),
        HeikoAntiLegRunningSensor(coordinator, mn_str),
    ])


class HeikoConnectionSensor(CoordinatorEntity[HeikoCoordinator], BinarySensorEntity):
    """True when the TCP socket to the W600 bridge is live."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_name = "Connection"

    def __init__(self, coordinator: HeikoCoordinator, mn_str: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{mn_str}_connection"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mn_str)},
            name="Heiko Heat Pump",
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def is_on(self) -> bool:
        return self.coordinator.connected


class HeikoAntiLegRunningSensor(CoordinatorEntity[HeikoCoordinator], BinarySensorEntity):
    """
    True when the Anti-Legionella programme is enabled AND the pump is in DHW mode.

    The legionella cycle fires internally on the WinCE panel's schedule; we cannot
    detect it directly from CMD 0x05 traffic. Instead we observe that WorkingMode
    switches to 1 (DHW) when the cycle runs. This sensor combines programme-on
    (Anti_Leg_Program=1, from CMD 0x02) with DHW mode (WorkingMode=1, from CMD 0x01)
    as the best available indicator. It will also be ON if the user manually selects
    DHW mode while the programme is enabled.
    """

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_name = "Anti-Legionella Running"

    def __init__(self, coordinator: HeikoCoordinator, mn_str: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{mn_str}_anti_leg_running"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mn_str)},
            name="Heiko Heat Pump",
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data:
            return None
        program = self.coordinator.data.get("Anti_Leg_Program")
        mode = self.coordinator.data.get("WorkingMode")
        if program is None or mode is None:
            return None
        return round(program) == 1 and round(mode) == 1  # programme on AND DHW mode
