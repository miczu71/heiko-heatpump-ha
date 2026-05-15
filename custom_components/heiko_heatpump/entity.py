"""Shared base entity class for all Heiko Heat Pump entity platforms."""

from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import HeikoCoordinator


class HeikoBaseEntity(CoordinatorEntity[HeikoCoordinator]):
    """Sets unique_id and device_info from mn_str + key."""

    def __init__(
        self,
        coordinator: HeikoCoordinator,
        mn_str: str,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{mn_str}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mn_str)},
            name="Heiko Heat Pump",
            manufacturer=MANUFACTURER,
            model=MODEL,
        )
