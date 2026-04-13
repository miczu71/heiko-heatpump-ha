"""
Home Assistant DataUpdateCoordinator for the Heiko heat pump.

Responsibilities:
- Owns the HeikoTCPClient instance (one per config entry)
- Receives CMD 0x01 frames and extracts parameter values
- Also polls via CMD 0x06 every POLL_INTERVAL in case push frames stop arriving
- Exposes async methods to write Setpoint and Sw back to the unit
- Notifies HA entities via the standard coordinator update mechanism
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .protocol import (
    HeatPumpFrame,
    CMD_REALTIME,
    build_ack_realtime,
    build_request_realtime,
    build_set_setpoint,
    build_set_power,
    extract_all_params,
)
from .tcp_client import HeikoTCPClient

_LOGGER = logging.getLogger(__name__)

# How often to actively poll (CMD 0x06) as a fallback.
# The pump pushes every 30 s; we poll at 60 s to avoid unnecessary traffic.
POLL_INTERVAL = timedelta(seconds=60)


class HeikoCoordinator(DataUpdateCoordinator[dict[str, float]]):
    """
    Coordinator that bridges the async TCP client with HA's entity update system.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        mn: bytes,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=POLL_INTERVAL,
        )
        self._mn     = mn   # 6-byte unit identifier (from config flow)
        self._client = HeikoTCPClient(host, port, self._on_frame)
        self._latest_data: dict[str, float] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_start(self) -> None:
        """Start the TCP client. Called from async_setup_entry."""
        await self._client.start()

    async def async_stop(self) -> None:
        """Stop the TCP client. Called from async_unload_entry."""
        await self._client.stop()

    # ── DataUpdateCoordinator override ────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, float]:
        """
        Called by the coordinator on POLL_INTERVAL.
        We send CMD 0x06 to actively request fresh data.
        The actual data arrives via _on_frame() callback, which calls
        async_set_updated_data() to push to entities immediately.

        This method returns the most recently seen data so that the coordinator
        does not report a failure when the pump is merely slow to respond.
        """
        if not self._client.connected:
            raise UpdateFailed("Not connected to heat pump bridge")

        poll_frame = build_request_realtime(self._mn)
        ok = await self._client.send(poll_frame)
        if not ok:
            raise UpdateFailed("Failed to send poll request to heat pump")

        # Return last known data; entities will be updated again when the reply arrives
        if not self._latest_data:
            raise UpdateFailed("No data received from heat pump yet")

        return self._latest_data

    # ── Frame dispatch ────────────────────────────────────────────────────────

    async def _on_frame(self, frame: HeatPumpFrame) -> None:
        """
        Callback invoked by HeikoTCPClient for every valid received frame.
        Handles CMD 0x01 (realtime data push from unit).
        """
        if frame.command == CMD_REALTIME:
            await self._handle_realtime(frame)
        # Other commands (0x02, 0x04, 0x05 replies) are silently ignored for now

    async def _handle_realtime(self, frame: HeatPumpFrame) -> None:
        """Process a CMD 0x01 realtime data frame."""
        params = extract_all_params(frame.payload)

        if not params:
            _LOGGER.warning("CMD 0x01 frame yielded no parameters (payload too short?)")
            return

        # ── Calculated / derived sensors ──────────────────────────────────────
        # DeltaT: outdoor unit outlet − inlet (Tuo − Tui).
        # Positive in heating mode (outlet warmer than inlet because the
        # refrigerant absorbs heat from the outdoor air).
        tuo = params.get("Tuo")
        tui = params.get("Tui")
        if tuo is not None and tui is not None:
            params["DeltaT"] = round(tuo - tui, 2)

        # Power (W): apparent electrical input = Voltage × Current.
        # This is VA not true Watts (no power-factor correction), but for a
        # compressor load it is a reasonable approximation.
        voltage = params.get("Voltage")
        current = params.get("Current")
        if voltage is not None and current is not None:
            params["Power"] = round(voltage * current, 1)

        # COP estimate: not calculable without water-side flow rate.
        # Placeholder: if flow rate (L/s) and specific heat of water (4186 J/kg·K)
        # were known we could do: COP = (flow × 4186 × ΔT_water) / Power_W
        # For now we expose a "COPe" that uses outdoor ΔT as a proxy — useful
        # for relative comparison but NOT a true COP.
        delta_t = params.get("DeltaT")
        power = params.get("Power")
        if delta_t is not None and power is not None and power > 10:
            # Rough proxy: higher outdoor ΔT relative to power = more efficient
            # True COP needs: mass_flow_rate × Cp × ΔT_water / electrical_power
            # We set COPe = None; users who know their flow rate can make a
            # template sensor. Leaving hook in data dict for future.
            pass  # params["COPe"] = ...

        _LOGGER.debug("Received realtime data: %s", params)
        self._latest_data = params

        # Push update to all subscribed HA entities immediately
        self.async_set_updated_data(params)

        # Send acknowledgement back to the unit (CMD 0x03)
        ack = build_ack_realtime(frame.mn)
        await self._client.send(ack)

    # ── Write commands ────────────────────────────────────────────────────────

    async def async_set_setpoint(self, setpoint_celsius: float) -> None:
        """
        Write a new target water temperature setpoint to the heat pump.
        Param index 38, value is a float in °C.
        """
        frame_bytes = build_set_setpoint(self._mn, setpoint_celsius)
        ok = await self._client.send(frame_bytes)
        if not ok:
            raise RuntimeError("Failed to send setpoint command to heat pump")
        _LOGGER.info("Setpoint → %.1f °C", setpoint_celsius)

    async def async_set_power(self, on: bool) -> None:
        """
        Turn the heat pump on or off.
        Param index 39, value 1.0 = on, 0.0 = off.
        """
        frame_bytes = build_set_power(self._mn, on)
        ok = await self._client.send(frame_bytes)
        if not ok:
            raise RuntimeError("Failed to send power command to heat pump")
        _LOGGER.info("Power → %s", "ON" if on else "OFF")
