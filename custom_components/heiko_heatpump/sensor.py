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
        name="Condenser Temperature",
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
        name="Refrigerant Temperature",
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
        name="Temperature par25",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
    ),
    HeikoSensorEntityDescription(
        key="Ts",
        name="Temperature par26",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
    ),
    HeikoSensorEntityDescription(
        key="Tp",
        name="Temperature par27",
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
    # WorkingMode: index 20, par18=0 in standby.
    # Values: 0=Standby, 1=DHW, 2=Heating, 3=Cooling, 4=DHW+Heating, 5=DHW+Cooling
    HeikoSensorEntityDescription(
        key="WorkingMode",
        name="Working Mode",
        state_class=SensorStateClass.MEASUREMENT,
        precision=0,
    ),
    # WaterPump: index 35, par33=1.0 (pump running in standby to maintain DHW)
    HeikoSensorEntityDescription(
        key="WaterPump",
        name="Water Pump State",
        state_class=SensorStateClass.MEASUREMENT,
        precision=0,
    ),
    # PWM: index 13, par12=25.0 — labelled PWM by community table
    HeikoSensorEntityDescription(
        key="PWM",
        name="PWM",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        precision=1,
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

    entities = [
        HeikoSensorEntity(coordinator, description, mn_str)
        for description in SENSOR_DESCRIPTIONS
    ]
    async_add_entities(entities)


class HeikoSensorEntity(CoordinatorEntity[HeikoCoordinator], SensorEntity):
    """A single sensor entity backed by the Heiko coordinator."""

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
        # Round to configured precision
        return round(raw, self.entity_description.precision)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from coordinator (called on push frames too)."""
        self.async_write_ha_state()
