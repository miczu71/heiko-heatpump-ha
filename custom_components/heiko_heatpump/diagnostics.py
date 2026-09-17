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
            "debug_slot_logging": entry.data.get("debug_slot_logging"),
        },
        "connection": {
            "connected": coordinator.connected,
            "last_seen": coordinator.last_seen.isoformat() if coordinator.last_seen else None,
            "reconnect_count": coordinator.reconnect_count,
        },
        "data": coordinator.data,
        # ── Etap 1 discovery: raw payloads + full unfiltered float tables ──
        # The community register table lists ≥121 setdata slots; PARAM_MAP
        # above only names ~24. These fields let a user inspect every slot
        # the pump actually sends, independent of what the integration
        # currently interprets.
        "raw_realtime_hex": coordinator.raw_realtime_hex,
        "raw_setdata_hex": coordinator.raw_setdata_hex,
        "realtime_payload_len": coordinator.realtime_payload_len,
        "setdata_payload_len": coordinator.setdata_payload_len,
        "frame_counts": coordinator.frame_counts,
        "all_floats_realtime": coordinator.all_floats_realtime,
        "all_floats_setdata": coordinator.all_floats_setdata,
    }
