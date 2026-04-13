"""
Switch platform for the Heiko Heat Pump integration.

⚠ Important: the on/off power switch lives in the SETDATA endpoint (par1 in setdata),
NOT in the realtime data frame. The realtime frame does not carry a reliable 0/1 on/off
bit — index 39 (par37) was previously mislabelled "Sw" but its value of ~212 in standby
confirms it is not an on/off state.

This switch entity therefore uses CMD 0x05 to WRITE to the unit (which is correct for
control), but it cannot read back the actual power state from the realtime frame.
State is maintained optimistically after each write. For a read-back, the setdata
frame (CMD 0x02) would need to be parsed separately.

The Water Pump state (par33, local index 35, key "WaterPump") IS readable from
realtime data and is exposed as a sensor, not a switch.
"""

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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Heiko switch entity from a config entry."""
    coordinator: HeikoCoordinator = hass.data[DOMAIN][entry.entry_id]
    mn_str = entry.data["mn"]
    async_add_entities([HeikoSwitchEntity(coordinator, mn_str)])


class HeikoSwitchEntity(CoordinatorEntity[HeikoCoordinator], SwitchEntity):
    """
    Switch entity for the heat pump on/off power state.

    Writing: sends CMD 0x05 with param index 39 and value 1.0 (on) or 0.0 (off).
    Reading: state is held optimistically after a write. There is no reliable
             on/off readback in the realtime frame — the power state lives in
             the setdata endpoint (CMD 0x02 / CMD 0x07) which is not yet parsed.

    If you observe that the pump ignores on/off commands, the write param index
    (39) may need adjustment once the setdata frame format is reverse-engineered.
    """

    _attr_name = "Heat Pump Power"
    _attr_icon = "mdi:heat-pump"

    def __init__(self, coordinator: HeikoCoordinator, mn_str: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{mn_str}_power_switch"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mn_str)},
            name="Heiko Heat Pump",
            manufacturer=MANUFACTURER,
            model=MODEL,
        )
        # Optimistic state: set immediately on write, cleared on next frame
        self._optimistic_state: bool | None = None

    @property
    def is_on(self) -> bool | None:
        """
        Return optimistic state if a recent write is pending confirmation.
        Otherwise returns None (unknown) since the realtime frame does not
        carry a reliable on/off bit.
        """
        return self._optimistic_state

    @property
    def assumed_state(self) -> bool:
        """Tell HA this entity uses assumed/optimistic state."""
        return True

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Send on command (param index 39, value 1.0)."""
        self._optimistic_state = True
        self.async_write_ha_state()
        try:
            await self.coordinator.async_set_power(True)
        except Exception as exc:
            _LOGGER.error("Failed to turn heat pump on: %s", exc)
            self._optimistic_state = None
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Send off command (param index 39, value 0.0)."""
        self._optimistic_state = False
        self.async_write_ha_state()
        try:
            await self.coordinator.async_set_power(False)
        except Exception as exc:
            _LOGGER.error("Failed to turn heat pump off: %s", exc)
            self._optimistic_state = None
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """
        A new realtime frame arrived. We don't clear optimistic state here
        because the realtime frame has no reliable power-state bit to confirm
        against. Optimistic state persists until the next explicit write.
        """
        self.async_write_ha_state()

