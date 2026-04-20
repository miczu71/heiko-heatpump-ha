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

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_HOST, CONF_PORT, CONF_MN, CONF_FLOW_RATE, DEFAULT_FLOW_RATE
from .coordinator import HeikoCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["binary_sensor", "sensor", "switch", "climate", "number", "select"]


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

    # Start the TCP client (non-blocking; it reconnects in the background)
    await coordinator.async_start()

    # Load entity platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

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

    return unload_ok
