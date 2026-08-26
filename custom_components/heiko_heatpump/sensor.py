"""
Sensor platform for the Heiko Heat Pump integration.

Each named parameter from the realtime data frame becomes a separate sensor entity.
All sensors update as soon as a new CMD 0x01 frame is received (~30 s cadence).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HeikoCoordinator
from .entity import HeikoBaseEntity


@dataclass(frozen=True, kw_only=True)
class HeikoSensorEntityDescription(SensorEntityDescription):
    """Extended description with optional precision."""
    precision: int = 2


# ── Sensor definitions ─────────────────────────────────────────────────────────
# Every key here must exist in PARAM_MAP. Verified against cloud JSON snapshot.
SENSOR_DESCRIPTIONS: tuple[HeikoSensorEntityDescription, ...] = (

    # ── Outdoor unit temperatures ─────────────────────────────────────────────
    HeikoSensorEntityDescription(
        key="Tuo",
        name="Outdoor Unit Outlet Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
    ),
    HeikoSensorEntityDescription(
        key="Tui",
        name="Outdoor Unit Inlet Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
    ),
    HeikoSensorEntityDescription(
        key="Tup",
        name="Outdoor Unit Pipe Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
        entity_registry_enabled_default=False,
    ),

    # ── Water / refrigerant circuit ───────────────────────────────────────────
    HeikoSensorEntityDescription(
        key="Tw",
        name="Hot Water / DHW Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
    ),
    HeikoSensorEntityDescription(
        key="Tc",
        name="Heating Circuit Return Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
    ),
    HeikoSensorEntityDescription(
        key="Tv1",
        name="EEV Temperature Sensor 1",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
        entity_registry_enabled_default=False,
    ),
    HeikoSensorEntityDescription(
        key="Tv2",
        name="EEV Temperature Sensor 2",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
        entity_registry_enabled_default=False,
    ),
    HeikoSensorEntityDescription(
        key="Tr",
        name="Room Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
        entity_registry_enabled_default=False,
    ),

    # ── Ambient & unknown temperatures ────────────────────────────────────────
    HeikoSensorEntityDescription(
        key="Ta",
        name="Ambient Air Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
    ),
    HeikoSensorEntityDescription(
        key="Td",
        name="Discharge Temperature Td",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
        entity_registry_enabled_default=False,
    ),
    HeikoSensorEntityDescription(
        key="Ts",
        name="Suction Temperature Ts",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
        entity_registry_enabled_default=False,
    ),
    HeikoSensorEntityDescription(
        key="Tp",
        name="Liquid Line Temperature Tp",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
        entity_registry_enabled_default=False,
    ),
    # Heating setpoint: index 37, cloud par36 (floor/radiator circuit target)
    HeikoSensorEntityDescription(
        key="Setpoint",
        name="Heating Water Setpoint",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
    ),

    # ── Electrical ────────────────────────────────────────────────────────────
    HeikoSensorEntityDescription(
        key="Voltage",
        name="Supply Voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
    ),
    HeikoSensorEntityDescription(
        key="Current",
        name="Compressor Current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        precision=2,
    ),

    # ── Compressor & fans ─────────────────────────────────────────────────────
    HeikoSensorEntityDescription(
        key="Frequency",
        name="Compressor Frequency",
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
    ),
    HeikoSensorEntityDescription(
        key="EEV",
        name="Expansion Valve Opening",
        native_unit_of_measurement="steps",
        state_class=SensorStateClass.MEASUREMENT,
        precision=0,
        entity_registry_enabled_default=False,
    ),
    HeikoSensorEntityDescription(
        key="Fan1",
        name="Fan 1 Speed",
        native_unit_of_measurement="rpm",
        state_class=SensorStateClass.MEASUREMENT,
        precision=0,
        entity_registry_enabled_default=False,
    ),
    HeikoSensorEntityDescription(
        key="Fan2",
        name="Fan 2 Speed",
        native_unit_of_measurement="rpm",
        state_class=SensorStateClass.MEASUREMENT,
        precision=0,
        entity_registry_enabled_default=False,
    ),

    # ── Pressures ─────────────────────────────────────────────────────────────
    HeikoSensorEntityDescription(
        key="Pd",
        name="High-side Pressure",
        native_unit_of_measurement=UnitOfPressure.BAR,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=2,
    ),
    HeikoSensorEntityDescription(
        key="Ps",
        name="Low-side Pressure",
        native_unit_of_measurement=UnitOfPressure.BAR,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=2,
    ),

    # ── State sensors ─────────────────────────────────────────────────────────
    # WorkingMode raw numeric — disabled by default; text version via HeikoWorkingModeTextEntity
    HeikoSensorEntityDescription(
        key="WorkingMode",
        name="Working Mode (raw)",
        state_class=SensorStateClass.MEASUREMENT,
        precision=0,
        entity_registry_enabled_default=False,
    ),
    # WaterPump raw numeric — disabled by default; text version via HeikoWaterPumpEntity
    HeikoSensorEntityDescription(
        key="WaterPump",
        name="Water Pump (raw)",
        state_class=SensorStateClass.MEASUREMENT,
        precision=0,
        entity_registry_enabled_default=False,
    ),
    HeikoSensorEntityDescription(
        key="PWM",
        name="PWM",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
        entity_registry_enabled_default=False,
    ),

    # ── Calculated / derived sensors ──────────────────────────────────────────
    # Outdoor ΔT: Tuo − Tui (heat extracted from outdoor air)
    HeikoSensorEntityDescription(
        key="DeltaT",
        name="Outdoor Unit Delta T",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=2,
    ),
    # Water circuit ΔT: Tw − Tc (hot outlet minus floor heating return)
    HeikoSensorEntityDescription(
        key="DeltaT_water",
        name="Water Circuit Delta T",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=2,
    ),
    # Electrical input power: V × I (apparent; true watts slightly lower due to PF)
    HeikoSensorEntityDescription(
        key="Power",
        name="Electrical Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        precision=0,
    ),
    # Thermal output power: flow × 4186 × (Setpoint − Tc)
    # Only shown when compressor is running (Frequency > 5 Hz)
    HeikoSensorEntityDescription(
        key="Thermal_power",
        name="Thermal Output Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        precision=0,
    ),
    HeikoSensorEntityDescription(
        key="COP_carnot",
        name="COP Carnot",
        state_class=SensorStateClass.MEASUREMENT,
        precision=2,
        entity_registry_enabled_default=False,
    ),
    # COP estimated: Q_thermal / P_electrical — only when compressor running
    # Uses configured flow rate (default 0.29 L/s for Eko II 6)
    HeikoSensorEntityDescription(
        key="COP_estimated",
        name="COP Estimated",
        state_class=SensorStateClass.MEASUREMENT,
        precision=2,
    ),

    # ── Working-time counters ─────────────────────────────────────────────────
    HeikoSensorEntityDescription(
        key="Time_AH",
        name="AH Working Time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        precision=0,
    ),
    HeikoSensorEntityDescription(
        key="Time_HBH",
        name="HBH Working Time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        precision=0,
    ),
    HeikoSensorEntityDescription(
        key="Time_HWTBH",
        name="HWTBH Working Time",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        precision=0,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Heiko sensor entities from a config entry."""
    coordinator: HeikoCoordinator = hass.data[DOMAIN][entry.entry_id]
    mn_str = entry.data["mn"]

    entities: list = [
        HeikoSensorEntity(coordinator, description, mn_str)
        for description in SENSOR_DESCRIPTIONS
    ]
    entities.append(HeikoWaterPumpEntity(coordinator, mn_str))
    entities.append(HeikoWorkingModeTextEntity(coordinator, mn_str))
    entities.append(HeikoModeSettingEntity(coordinator, mn_str))
    entities.append(HeikoLastSeenSensor(coordinator, mn_str))
    entities.append(HeikoReconnectSensor(coordinator, mn_str))
    async_add_entities(entities)


class HeikoSensorEntity(HeikoBaseEntity, SensorEntity):
    """A single numeric sensor entity backed by the Heiko coordinator."""

    entity_description: HeikoSensorEntityDescription

    def __init__(
        self,
        coordinator: HeikoCoordinator,
        description: HeikoSensorEntityDescription,
        mn_str: str,
    ) -> None:
        super().__init__(coordinator, mn_str, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Optional[float]:
        """Return the current sensor value from coordinator data."""
        if self.coordinator.data is None:
            return None
        raw = self.coordinator.data.get(self.entity_description.key)
        if raw is None:
            return None
        return round(raw, self.entity_description.precision)


class HeikoWaterPumpEntity(HeikoBaseEntity, SensorEntity):
    """
    Water pump state rendered as human-readable text: 'on' or 'off'.
    Raw value from protocol: 1.0 = on, 0.0 = off.
    """

    _attr_name = "Water Pump"
    _attr_icon = "mdi:pump"

    def __init__(self, coordinator: HeikoCoordinator, mn_str: str) -> None:
        super().__init__(coordinator, mn_str, "WaterPump_text")

    @property
    def native_value(self) -> Optional[str]:
        if self.coordinator.data is None:
            return None
        raw = self.coordinator.data.get("WaterPump")
        if raw is None:
            return None
        return "on" if raw >= 0.5 else "off"


class HeikoLastSeenSensor(HeikoBaseEntity, SensorEntity):
    """Timestamp of the last frame received from the heat pump."""

    _attr_name = "Last Seen"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: HeikoCoordinator, mn_str: str) -> None:
        super().__init__(coordinator, mn_str, "last_seen")

    @property
    def native_value(self):
        return self.coordinator.last_seen


class HeikoReconnectSensor(HeikoBaseEntity, SensorEntity):
    """Number of times the TCP client has reconnected since HA started."""

    _attr_name = "Reconnect Count"
    _attr_icon = "mdi:wifi-refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: HeikoCoordinator, mn_str: str) -> None:
        super().__init__(coordinator, mn_str, "reconnect_count")

    @property
    def native_value(self) -> int:
        return self.coordinator.reconnect_count


_WORKING_MODE_NAMES: dict[int, str] = {
    0: "Standby",
    1: "Sanitary Hot Water",
    2: "Heating",
    3: "Cooling",
    4: "Sanitary Hot Water+Heating",
    5: "Sanitary Hot Water+Cooling",
}


class HeikoWorkingModeTextEntity(HeikoBaseEntity, SensorEntity):
    """
    Working mode rendered as human-readable text matching the cloud UI labels.
    Raw value from protocol (index 19, par18): 0–5.
    """

    _attr_name = "Working Mode"
    _attr_icon = "mdi:cog-transfer"

    def __init__(self, coordinator: HeikoCoordinator, mn_str: str) -> None:
        super().__init__(coordinator, mn_str, "WorkingMode_text")

    @property
    def native_value(self) -> Optional[str]:
        if self.coordinator.data is None:
            return None
        raw = self.coordinator.data.get("WorkingMode")
        if raw is None:
            return None
        return _WORKING_MODE_NAMES.get(int(round(raw)), f"Unknown ({int(round(raw))})")

    @property
    def extra_state_attributes(self) -> dict:
        if self.coordinator.data is None:
            return {}
        raw = self.coordinator.data.get("WorkingMode")
        return {"raw_value": raw} if raw is not None else {}


# Mode setting labels — write-side convention, matches par4 from cloud setdata API:
# 0=Standby, 1=Heating, 2=Cooling, 3=DHW, 4=Auto
_MODE_SETDATA_NAMES: dict[int, str] = {
    0: "Standby",
    1: "Heating",
    2: "Cooling",
    3: "DHW",
    4: "Auto",
}


class HeikoModeSettingEntity(HeikoBaseEntity, SensorEntity):
    """
    Configured working mode (the mode SETTING, not the instantaneous state).
    Read from CMD 0x02 setdata idx=3 — equivalent to par4 in the cloud API.
    Replaces the cloud-based sensor.hp_working_mode from multiscrape.
    """

    _attr_name = "Mode Setting"
    _attr_icon = "mdi:cog-transfer"

    def __init__(self, coordinator: HeikoCoordinator, mn_str: str) -> None:
        super().__init__(coordinator, mn_str, "ModeSetting")

    @property
    def native_value(self) -> Optional[str]:
        if self.coordinator.data is None:
            return None
        raw = self.coordinator.data.get("Mode_Setdata")
        if raw is None:
            return None
        return _MODE_SETDATA_NAMES.get(int(round(raw)), f"Unknown ({int(round(raw))})")

    @property
    def extra_state_attributes(self) -> dict:
        if self.coordinator.data is None:
            return {}
        raw = self.coordinator.data.get("Mode_Setdata")
        return {"raw_value": raw} if raw is not None else {}

