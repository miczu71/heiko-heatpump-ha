"""
Select platform for the Heiko Heat Pump integration.

Provides a dropdown to select the working mode directly.
Write index 3 confirmed by CMD 0x05 traffic capture.

Modes confirmed:
  1 = Heating  ✓
  3 = DHW (Sanitary Hot Water)  ✓
  4 = Auto  ✓
  0 = Standby (assumed — power-off state)
  2 = Cooling (assumed — logical extension)
"""

from __future__ import annotations
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HeikoCoordinator
from .entity import HeikoBaseEntity
from .protocol import (
    MODE_STANDBY, MODE_HEATING, MODE_COOLING, MODE_DHW, MODE_AUTO,
    CIRC_PUMP_TYPE_VARIABLE, CIRC_PUMP_TYPE_CONSTANT,
    CIRC_PUMP_MODE_DEFAULT, CIRC_PUMP_MODE_ALWAYS_ON, CIRC_PUMP_MODE_COMPRESSOR,
    CIRC_PUMP_SPEED_HIGH, CIRC_PUMP_SPEED_MEDIUM, CIRC_PUMP_SPEED_LOW,
    BACKUP_PRIORITY_LOWER, BACKUP_PRIORITY_HIGHER,
)

_LOGGER = logging.getLogger(__name__)

# Human label → protocol mode value
_OPTIONS: dict[str, int] = {
    "Standby":  MODE_STANDBY,
    "Heating":  MODE_HEATING,
    "Cooling":  MODE_COOLING,
    "DHW":      MODE_DHW,
    "Auto":     MODE_AUTO,
}
_VALUE_TO_LABEL = {v: k for k, v in _OPTIONS.items()}


@dataclass(frozen=True)
class HeikoSelectEntityDescription:
    key: str
    name: str
    icon: str
    options: dict[str, int]   # human label → protocol value
    read_key: str
    write: Callable[[HeikoCoordinator, int], Awaitable[None]]


# Circulation pump P0 — Etap 7 (2026-09-23), confirmed by a live panel diff
# session (installer-level menu, not covered by the portal or the user
# manual). See docs/heiko_register_map.md (homeassistant-config repo) for
# the session log and per-value confirmation. Panel labels kept verbatim
# (Polish) since that's the source of truth a user matches against the
# physical panel; Circ_Pump_Mode value 0's panel label literally repeats the
# field's own title — a firmware bug, so it's given a descriptive label here
# instead of reproducing the broken text.
_CIRC_PUMP_DESCS: list[HeikoSelectEntityDescription] = [
    HeikoSelectEntityDescription(
        key="circ_pump_type",
        name="Circulation Pump P0 Type",
        icon="mdi:pump",
        options={
            "Pompa sterowana płynnie": CIRC_PUMP_TYPE_VARIABLE,
            "Stałe obroty pompy": CIRC_PUMP_TYPE_CONSTANT,
        },
        read_key="Circ_Pump_Type",
        write=lambda coord, v: coord.async_set_circ_pump_type(v),
    ),
    HeikoSelectEntityDescription(
        key="circ_pump_mode",
        name="Circulation Pump P0 Mode",
        icon="mdi:pump",
        options={
            "Domyślny (przerywany)": CIRC_PUMP_MODE_DEFAULT,
            "Pompa włączona na stałe": CIRC_PUMP_MODE_ALWAYS_ON,
            "Praca pompy ze sprężarką": CIRC_PUMP_MODE_COMPRESSOR,
        },
        read_key="Circ_Pump_Mode",
        write=lambda coord, v: coord.async_set_circ_pump_mode(v),
    ),
    HeikoSelectEntityDescription(
        key="circ_pump_speed_heating",
        name="Circulation Pump P0 Speed (Heating)",
        icon="mdi:speedometer",
        options={
            "Wysokie obroty": CIRC_PUMP_SPEED_HIGH,
            "Średnie obroty": CIRC_PUMP_SPEED_MEDIUM,
            "Niskie obroty": CIRC_PUMP_SPEED_LOW,
        },
        read_key="Circ_Pump_Speed_Heating",
        write=lambda coord, v: coord.async_set_circ_pump_speed_heating(v),
    ),
    HeikoSelectEntityDescription(
        key="circ_pump_speed_dhw",
        name="Circulation Pump P0 Speed (DHW)",
        icon="mdi:speedometer",
        options={
            "Wysokie obroty": CIRC_PUMP_SPEED_HIGH,
            "Średnie obroty": CIRC_PUMP_SPEED_MEDIUM,
            "Niskie obroty": CIRC_PUMP_SPEED_LOW,
        },
        read_key="Circ_Pump_Speed_DHW",
        write=lambda coord, v: coord.async_set_circ_pump_speed_dhw(v),
    ),
]


# Priorities of the additional heat source vs the internal heater AH — panel
# menu "Dodatkowe źródła ciepła" rows 2 and 4, confirmed 2026-09-26 by isolated
# panel changes (slot 48 and slot 50, both 0=lower / 1=higher, two options only).
# Labels are the panel's own wording.
_BACKUP_PRIORITY_OPTIONS: dict[str, int] = {
    "Niższe dla grzałki wewnętrznej AH": BACKUP_PRIORITY_LOWER,
    "Wyższe dla grzałki wewnętrznej AH": BACKUP_PRIORITY_HIGHER,
}
_BACKUP_DESCS: list[HeikoSelectEntityDescription] = [
    HeikoSelectEntityDescription(
        key="backup_priority_heating",
        name="Backup Priority (Heating)",
        icon="mdi:radiator",
        options=_BACKUP_PRIORITY_OPTIONS,
        read_key="Backup_Priority_HBH",
        write=lambda coord, v: coord.async_set_backup_priority_heating(v),
    ),
    HeikoSelectEntityDescription(
        key="backup_priority_dhw",
        name="Backup Priority (DHW)",
        icon="mdi:water-boiler",
        options=_BACKUP_PRIORITY_OPTIONS,
        read_key="HBH_State",   # slot 50 (legacy key name, see coordinator.py)
        write=lambda coord, v: coord.async_set_backup_priority_dhw(v),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HeikoCoordinator = hass.data[DOMAIN][entry.entry_id]
    mn_str = entry.data["mn"]
    async_add_entities([
        HeikoModeSelectEntity(coordinator, mn_str),
        *(HeikoSelectEntity(coordinator, mn_str, desc)
          for desc in _CIRC_PUMP_DESCS + _BACKUP_DESCS),
    ])


class HeikoModeSelectEntity(HeikoBaseEntity, SelectEntity):
    """
    Dropdown select for heat pump working mode.
    Reads from WorkingMode sensor (index 2, par1).
    Writes to mode register (index 3) — also turns power on if currently off.
    Selecting 'Standby' turns the pump off (writes power index 0 → 0.0).
    """

    _attr_name    = "Working Mode"
    _attr_icon    = "mdi:cog-transfer"
    _attr_options = list(_OPTIONS.keys())

    def __init__(self, coordinator: HeikoCoordinator, mn_str: str) -> None:
        super().__init__(coordinator, mn_str, "mode_select")
        self._optimistic: str | None = None

    @property
    def current_option(self) -> str | None:
        if self._optimistic is not None:
            return self._optimistic
        if not self.coordinator.data:
            return None
        # Mode_Setdata comes from CMD 0x02 setdata (par4 convention: 0=Standby,
        # 1=Heating, 2=Cooling, 3=DHW, 4=Auto) — same values as _OPTIONS above.
        wm = self.coordinator.data.get("Mode_Setdata")
        if wm is None:
            return None
        return _VALUE_TO_LABEL.get(int(round(wm)))

    async def async_select_option(self, option: str) -> None:
        mode_val = _OPTIONS.get(option)
        if mode_val is None:
            _LOGGER.error("Unknown mode option: %s", option)
            return

        self._optimistic = option
        self.async_write_ha_state()
        try:
            if mode_val == MODE_STANDBY:
                # Turn power off — pump enters standby
                await self.coordinator.async_set_power(False)
            else:
                # Ensure power is on, then set mode
                await self.coordinator.async_set_power(True)
                await self.coordinator.async_set_mode(mode_val)
        except Exception:
            _LOGGER.exception("Failed to set mode to %s", option)
            self._optimistic = None
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        # Clear optimistic only once the live WorkingMode value is populated.
        # This avoids a brief flicker if the pump takes a cycle to confirm.
        if self.coordinator.data and self.coordinator.data.get("Mode_Setdata") is not None:
            self._optimistic = None
        self.async_write_ha_state()


class HeikoSelectEntity(HeikoBaseEntity, SelectEntity):
    """A generic dropdown select entity that reads from and writes to the
    heat pump, driven by a HeikoSelectEntityDescription. Used for the
    circulation pump P0 controls (Etap 7) — see _CIRC_PUMP_DESCS above."""

    def __init__(
        self,
        coordinator: HeikoCoordinator,
        mn_str: str,
        desc: HeikoSelectEntityDescription,
    ) -> None:
        super().__init__(coordinator, mn_str, desc.key)
        self._attr_name = desc.name
        self._attr_icon = desc.icon
        self._attr_options = list(desc.options.keys())
        self._desc = desc
        self._value_to_label = {v: k for k, v in desc.options.items()}
        self._optimistic: str | None = None

    @property
    def current_option(self) -> str | None:
        if self._optimistic is not None:
            return self._optimistic
        if not self.coordinator.data:
            return None
        raw = self.coordinator.data.get(self._desc.read_key)
        if raw is None:
            return None
        return self._value_to_label.get(int(round(raw)))

    async def async_select_option(self, option: str) -> None:
        value = self._desc.options.get(option)
        if value is None:
            _LOGGER.error("Unknown option for %s: %s", self._attr_name, option)
            return

        self._optimistic = option
        self.async_write_ha_state()
        try:
            await self._desc.write(self.coordinator, value)
        except Exception:
            _LOGGER.exception("Failed to set %s to %s", self._attr_name, option)
            self._optimistic = None
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.coordinator.data and self.coordinator.data.get(self._desc.read_key) is not None:
            self._optimistic = None
        self.async_write_ha_state()
