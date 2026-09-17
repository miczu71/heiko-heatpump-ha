"""Binary sensor platform for Heiko heat pump."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import HeikoCoordinator
from .const import DOMAIN
from .entity import HeikoBaseEntity


@dataclass(frozen=True, kw_only=True)
class HeikoBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Generic on/off flag backed by a single coordinator.data key.

    on_value: raw value (after round()) that counts as "on". Everything else
    (including missing/None) is "off"/unknown, matching the 0/1 convention
    used throughout _SETDATA_MAP.
    """
    on_value: int = 1


# ── Etap 4 (2026-09-17): named via portal, cross-validated against a live
# diagnostics dump (74 pairs, 0 mismatches) — docs/heiko_register_map.md in
# homeassistant-config. Read-only completeness pass. Two enabled by default
# (Circuit 2 Active — cheap, useful state signal); the rest start disabled,
# enable individually if wanted.
#
# Vacation Mode does NOT have an entry here even though it was named in the
# same batch: Etap 5 added switch.vacation_mode_switch (write + read-back),
# which fully supersedes a read-only duplicate — same pattern as
# HeatingCurve_State (circuit 1), which is switch-only too.
BINARY_SENSOR_DESCRIPTIONS: tuple[HeikoBinarySensorEntityDescription, ...] = (
    HeikoBinarySensorEntityDescription(
        key="Circuit2_Enabled",
        name="Heating Circuit 2 Active",
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    HeikoBinarySensorEntityDescription(
        key="Circuit2_HeatingCurve_State",
        name="Circuit 2 Heating Curve",
        entity_registry_enabled_default=False,
    ),
    HeikoBinarySensorEntityDescription(
        key="Backup_Heating_For_Heating",
        name="Backup Heating Sources For Heating",
        entity_registry_enabled_default=False,
    ),
    HeikoBinarySensorEntityDescription(
        # Portal enum "Lower than AH"(0) / "Higher than AH"(1).
        key="Backup_Priority_HBH",
        name="Backup Heater HBH Priority Higher Than AH",
        entity_registry_enabled_default=False,
    ),
    HeikoBinarySensorEntityDescription(
        key="Backup_Source_DHW",
        name="Backup Heating Source For DHW",
        entity_registry_enabled_default=False,
    ),
    HeikoBinarySensorEntityDescription(
        key="Shifting_Priority",
        name="Shifting Priority",
        entity_registry_enabled_default=False,
    ),
    HeikoBinarySensorEntityDescription(
        key="DHW_Backup_For_Shifting",
        name="DHW Backup Heater For Shifting Priority",
        entity_registry_enabled_default=False,
    ),
    HeikoBinarySensorEntityDescription(
        key="Reheating_Function",
        name="Reheating Function",
        entity_registry_enabled_default=False,
    ),
    HeikoBinarySensorEntityDescription(
        key="Reduced_Setpoint",
        name="Reduced Setpoint",
        entity_registry_enabled_default=False,
    ),
    HeikoBinarySensorEntityDescription(
        key="Quiet_Operation",
        name="Quiet Operation",
        entity_registry_enabled_default=False,
    ),
    HeikoBinarySensorEntityDescription(
        key="Electrical_Utility_Lock",
        name="Electrical Utility Lock",
        device_class=BinarySensorDeviceClass.LOCK,
        entity_registry_enabled_default=False,
    ),
    HeikoBinarySensorEntityDescription(
        key="HBH_During_Lock",
        name="HBH Allowed During Electrical Utility Lock",
        entity_registry_enabled_default=False,
    ),
    HeikoBinarySensorEntityDescription(
        key="P0_During_Lock",
        name="P0 Allowed During Electrical Utility Lock",
        entity_registry_enabled_default=False,
    ),
    HeikoBinarySensorEntityDescription(
        key="Heating_Cooling_Timer",
        name="Heating/Cooling ON/OFF Timer",
        entity_registry_enabled_default=False,
    ),
    HeikoBinarySensorEntityDescription(
        key="Room_Temp_Effect_On_Curve",
        name="Room Temp Effect On Heating Curve",
        entity_registry_enabled_default=False,
    ),
    HeikoBinarySensorEntityDescription(
        key="WaterPump_P1",
        name="Water Pump P1",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_registry_enabled_default=False,
    ),
    HeikoBinarySensorEntityDescription(
        key="WaterPump_P2",
        name="Water Pump P2",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_registry_enabled_default=False,
    ),
)


class HeikoGenericBinarySensor(HeikoBaseEntity, BinarySensorEntity):
    """A single on/off binary sensor backed by one coordinator.data key."""

    entity_description: HeikoBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: HeikoCoordinator,
        description: HeikoBinarySensorEntityDescription,
        mn_str: str,
    ) -> None:
        super().__init__(coordinator, mn_str, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data:
            return None
        raw = self.coordinator.data.get(self.entity_description.key)
        if raw is None:
            return None
        return round(raw) == self.entity_description.on_value


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HeikoCoordinator = hass.data[DOMAIN][entry.entry_id]
    mn_str = entry.data["mn"]
    entities: list = [
        HeikoConnectionSensor(coordinator, mn_str),
        HeikoAntiLegRunningSensor(coordinator, mn_str),
    ]
    entities += [
        HeikoGenericBinarySensor(coordinator, description, mn_str)
        for description in BINARY_SENSOR_DESCRIPTIONS
    ]
    async_add_entities(entities)


class HeikoConnectionSensor(HeikoBaseEntity, BinarySensorEntity):
    """True when the TCP socket to the W600 bridge is live."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_name = "Connection"

    def __init__(self, coordinator: HeikoCoordinator, mn_str: str) -> None:
        super().__init__(coordinator, mn_str, "connection")

    @property
    def is_on(self) -> bool:
        return self.coordinator.connected


class HeikoAntiLegRunningSensor(HeikoBaseEntity, BinarySensorEntity):
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
        super().__init__(coordinator, mn_str, "anti_leg_running")

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data:
            return None
        program = self.coordinator.data.get("Anti_Leg_Program")
        mode = self.coordinator.data.get("WorkingMode")
        if program is None or mode is None:
            return None
        return round(program) == 1 and round(mode) == 1  # programme on AND DHW mode
