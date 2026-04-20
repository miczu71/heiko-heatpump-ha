"""
Heiko Heat Pump — Home Assistant custom integration.

Connects to the USR-W600 WiFi-to-RS-485 bridge over TCP and exposes
heat pump sensor values and controls as Home Assistant entities.

Platforms loaded:
  - sensor  (temperatures, pressures, frequency, voltage, current, etc.)
  - switch  (on/off power control via Sw parameter)
  - climate (setpoint + on/off combined for thermostat card, optional)
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, CONF_HOST, CONF_PORT, CONF_MN, CONF_FLOW_RATE, DEFAULT_FLOW_RATE
from .coordinator import HeikoCoordinator
from .protocol import MODE_STANDBY, MODE_HEATING, MODE_COOLING, MODE_DHW, MODE_AUTO

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "sensor", "switch", "number", "select", "water_heater"]

_MODE_NAMES: dict[str, int] = {
    "standby": MODE_STANDBY,
    "heating": MODE_HEATING,
    "cooling": MODE_COOLING,
    "dhw":     MODE_DHW,
    "auto":    MODE_AUTO,
}


def _all_coordinators(hass: HomeAssistant) -> list[HeikoCoordinator]:
    return list(hass.data.get(DOMAIN, {}).values())


def _register_services(hass: HomeAssistant) -> None:
    async def set_dhw_setpoint(call: ServiceCall) -> None:
        for coord in _all_coordinators(hass):
            await coord.async_set_dhw_setpoint(call.data["temperature"])

    async def set_mode(call: ServiceCall) -> None:
        mode = call.data["mode"]
        if isinstance(mode, str):
            mode = _MODE_NAMES[mode.lower()]
        for coord in _all_coordinators(hass):
            await coord.async_set_mode(mode)

    async def set_power(call: ServiceCall) -> None:
        for coord in _all_coordinators(hass):
            await coord.async_set_power(call.data["power"])

    async def set_heating_curve(call: ServiceCall) -> None:
        for coord in _all_coordinators(hass):
            await coord.async_set_heating_curve(call.data["enabled"])

    async def set_hbh(call: ServiceCall) -> None:
        for coord in _all_coordinators(hass):
            await coord.async_set_hbh(call.data["enabled"])

    async def set_dhw_storage(call: ServiceCall) -> None:
        for coord in _all_coordinators(hass):
            await coord.async_set_dhw_storage(call.data["enabled"])

    hass.services.async_register(
        DOMAIN, "set_dhw_setpoint", set_dhw_setpoint,
        schema=vol.Schema({
            vol.Required("temperature"): vol.All(vol.Coerce(float), vol.Range(min=40, max=60)),
        }),
    )
    hass.services.async_register(
        DOMAIN, "set_mode", set_mode,
        schema=vol.Schema({
            vol.Required("mode"): vol.Any(
                vol.All(int, vol.Range(min=0, max=4)),
                vol.All(str, vol.Lower, vol.In(_MODE_NAMES)),
            ),
        }),
    )
    hass.services.async_register(
        DOMAIN, "set_power", set_power,
        schema=vol.Schema({vol.Required("power"): cv.boolean}),
    )
    hass.services.async_register(
        DOMAIN, "set_heating_curve", set_heating_curve,
        schema=vol.Schema({vol.Required("enabled"): cv.boolean}),
    )
    hass.services.async_register(
        DOMAIN, "set_hbh", set_hbh,
        schema=vol.Schema({vol.Required("enabled"): cv.boolean}),
    )
    hass.services.async_register(
        DOMAIN, "set_dhw_storage", set_dhw_storage,
        schema=vol.Schema({vol.Required("enabled"): cv.boolean}),
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Heiko Heat Pump from a config entry."""
    host      = entry.data[CONF_HOST]
    port      = int(entry.data[CONF_PORT])
    mn_str    = entry.data[CONF_MN]
    flow_rate = float(entry.data.get(CONF_FLOW_RATE, DEFAULT_FLOW_RATE))

    # Parse MN hex string → 6 bytes
    mn = bytes.fromhex(mn_str)

    coordinator = HeikoCoordinator(hass, host, port, mn, flow_rate_lps=flow_rate)

    # Store coordinator for platforms to access
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await coordinator.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, "set_dhw_setpoint"):
        _register_services(hass)

    _LOGGER.info(
        "Heiko Heat Pump integration started: %s:%d (MN %s)", host, port, mn_str
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        coordinator: HeikoCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_stop()
        if not hass.data[DOMAIN]:
            for svc in ("set_dhw_setpoint", "set_mode", "set_power",
                        "set_heating_curve", "set_hbh", "set_dhw_storage"):
                hass.services.async_remove(DOMAIN, svc)

    return unload_ok
