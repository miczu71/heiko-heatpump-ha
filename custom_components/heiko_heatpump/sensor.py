"""
Sensor platform for the Heiko Heat Pump integration.

Each named parameter from the realtime data frame becomes a separate sensor entity.
All sensors update as soon as a new CMD 0x01 frame is received (~30 s cadence).
"""

from __future__ import annotations

import logging
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
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import HeikoCoordinator

_LOGGER = logging.getLogger(__name__)


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
    ),

    # ── Water / refrigerant circuit ───────────────────────────────────────────
    HeikoSensorEntityDescription(
        key="Tw",
        name="Water / DHW Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
    ),
    HeikoSensorEntityDescription(
        key="Tc",
        name="Heating Water Temperature",
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
    ),
    HeikoSensorEntityDescription(
        key="Tv2",
        name="EEV Temperature Sensor 2",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
    ),
    HeikoSensorEntityDescription(
        key="Tr",
        name="Room Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
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
    ),
    HeikoSensorEntityDescription(
        key="Ts",
        name="Suction Temperature Ts",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
    ),
    HeikoSensorEntityDescription(
        key="Tp",
        name="Pipe Temperature Tp",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
    ),
    # Heating setpoint: index 38, cloud par36=22.0°C (floor/radiator circuit target)
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
    ),
    HeikoSensorEntityDescription(
        key="Fan1",
        name="Fan 1 Speed",
        native_unit_of_measurement="rpm",
        state_class=SensorStateClass.MEASUREMENT,
        precision=0,
    ),
    HeikoSensorEntityDescription(
        key="Fan2",
        name="Fan 2 Speed",
        native_unit_of_measurement="rpm",
        state_class=SensorStateClass.MEASUREMENT,
        precision=0,
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
    # WorkingMode: index 19 (corrected), par18.
    # Values: 0=Standby, 1=Sanitary Hot Water, 2=Heating, 3=Cooling,
    #         4=Sanitary Hot Water+Heating, 5=Sanitary Hot Water+Cooling
    HeikoSensorEntityDescription(
        key="WorkingMode",
        name="Working Mode",
        state_class=SensorStateClass.MEASUREMENT,
        precision=0,
    ),
    # WaterPump: index 34, par33. Rendered as "on"/"off" by HeikoWaterPumpEntity below.
    HeikoSensorEntityDescription(
        key="WaterPump",
        name="Water Pump",
        state_class=SensorStateClass.MEASUREMENT,
        precision=0,
    ),
    # PWM: index 13, par12
    HeikoSensorEntityDescription(
        key="PWM",
        name="PWM",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
    ),

    # ── Calculated / derived sensors ──────────────────────────────────────────
    # DeltaT: Tuo − Tui (outdoor outlet minus inlet).
    # In heating mode: positive value = heat extracted from outdoor air.
    HeikoSensorEntityDescription(
        key="DeltaT",
        name="Outdoor Unit Delta T",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=2,
    ),
    # Power: Voltage × Current = apparent electrical input power.
    HeikoSensorEntityDescription(
        key="Power",
        name="Electrical Power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        precision=0,
    ),

    # ── Working-time counters ─────────────────────────────────────────────────
    HeikoSensorEntityDescription(
        key="Time_AH",
        name="AH Working Time",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.TOTAL_INCREASING,
        precision=0,
    ),
    HeikoSensorEntityDescription(
        key="Time_HBH",
        name="HBH Working Time",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.TOTAL_INCREASING,
        precision=0,
    ),
    HeikoSensorEntityDescription(
        key="Time_HWTBH",
        name="HWTBH Working Time",
        native_unit_of_measurement="min",
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
    # Specialised text-value entities
    entities.append(HeikoWaterPumpEntity(coordinator, mn_str))
    entities.append(HeikoWorkingModeTextEntity(coordinator, mn_str))
    async_add_entities(entities)


class HeikoSensorEntity(CoordinatorEntity[HeikoCoordinator], SensorEntity):
    """A single numeric sensor entity backed by the Heiko coordinator."""

    entity_description: HeikoSensorEntityDescription

    def __init__(
        self,
        coordinator: HeikoCoordinator,
        description: HeikoSensorEntityDescription,
        mn_str: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{mn_str}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mn_str)},
            name="Heiko Heat Pump",
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def native_value(self) -> Optional[float]:
        """Return the current sensor value from coordinator data."""
        if self.coordinator.data is None:
            return None
        raw = self.coordinator.data.get(self.entity_description.key)
        if raw is None:
            return None
        return round(raw, self.entity_description.precision)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinator (called on push frames too)."""
        self.async_write_ha_state()


class HeikoWaterPumpEntity(CoordinatorEntity[HeikoCoordinator], SensorEntity):
    """
    Water pump state rendered as human-readable text: 'on' or 'off'.
    Raw value from protocol: 1.0 = on, 0.0 = off.
    """

    _attr_name = "Water Pump"
    _attr_icon = "mdi:pump"

    def __init__(self, coordinator: HeikoCoordinator, mn_str: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{mn_str}_WaterPump_text"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mn_str)},
            name="Heiko Heat Pump",
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def native_value(self) -> Optional[str]:
        if self.coordinator.data is None:
            return None
        raw = self.coordinator.data.get("WaterPump")
        if raw is None:
            return None
        return "on" if raw >= 0.5 else "off"

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


_WORKING_MODE_NAMES: dict[int, str] = {
    0: "Standby",
    1: "Sanitary Hot Water",
    2: "Heating",
    3: "Cooling",
    4: "Sanitary Hot Water+Heating",
    5: "Sanitary Hot Water+Cooling",
}


class HeikoWorkingModeTextEntity(CoordinatorEntity[HeikoCoordinator], SensorEntity):
    """
    Working mode rendered as human-readable text matching the cloud UI labels.
    Raw value from protocol (index 19, par18): 0–5.
    """

    _attr_name = "Working Mode"
    _attr_icon = "mdi:cog-transfer"

    def __init__(self, coordinator: HeikoCoordinator, mn_str: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{mn_str}_WorkingMode_text"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mn_str)},
            name="Heiko Heat Pump",
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

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

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()

