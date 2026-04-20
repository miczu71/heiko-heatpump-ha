"""Diagnostics support for Heiko Heat Pump."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import HeikoCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: HeikoCoordinator = hass.data[DOMAIN][entry.entry_id]
    return {
        "config": {
            "host": "**REDACTED**",
            "port": entry.data.get("port"),
            "mn": "**REDACTED**",
            "flow_rate_lps": entry.data.get("flow_rate_lps"),
        },
        "connection": {
            "connected": coordinator.connected,
            "last_seen": coordinator.last_seen.isoformat() if coordinator.last_seen else None,
            "reconnect_count": coordinator.reconnect_count,
        },
        "data": coordinator.data,
    }
