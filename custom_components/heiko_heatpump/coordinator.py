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

from .const import DOMAIN, DEFAULT_FLOW_RATE
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
        flow_rate_lps: float = DEFAULT_FLOW_RATE,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=POLL_INTERVAL,
        )
        self._mn            = mn
        self._flow_rate_lps = flow_rate_lps   # L/s, from config
        self._client        = HeikoTCPClient(host, port, self._on_frame)
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
        # DeltaT_outdoor: Tuo − Tui (outdoor unit outlet minus inlet).
        # Positive in heating mode — the refrigerant extracted this heat from outdoor air.
        tuo = params.get("Tuo")
        tui = params.get("Tui")
        if tuo is not None and tui is not None:
            params["DeltaT"] = round(tuo - tui, 2)

        # Power (W): Voltage × Current = apparent electrical input power.
        # Note: true power = V × I × power_factor. PF ≈ 0.85 for compressor loads
        # but we have no PF sensor, so this is VA (will read ~15% high).
        voltage = params.get("Voltage")
        current = params.get("Current")
        power_w: float | None = None
        if voltage is not None and current is not None:
            power_w = round(voltage * current, 1)
            params["Power"] = power_w

        # DeltaT_water: Tw − Tc (hot water outlet minus heating circuit return).
        # Tw = hot water / DHW outlet from heat exchanger.
        # Tc = floor heating return temperature (cold water coming back).
        # Large ΔT = pump is lifting water temperature a lot across the HX.
        tw = params.get("Tw")
        tc = params.get("Tc")
        if tw is not None and tc is not None:
            params["DeltaT_water"] = round(tw - tc, 2)

        # COP_carnot: theoretical maximum COP (Carnot efficiency).
        # COP_carnot = T_hot_K / (T_hot_K − T_cold_K)
        # Uses Tw (hot water outlet) as T_hot and Ta (ambient) as T_cold.
        # Real heat pumps achieve 40–55% of Carnot COP.
        ta = params.get("Ta")
        if tw is not None and ta is not None:
            tw_k = tw + 273.15
            ta_k = ta + 273.15
            denom = tw_k - ta_k
            if denom > 0.1:  # avoid division by near-zero
                params["COP_carnot"] = round(tw_k / denom, 2)

        # COP_estimated: calculated from thermal output / electrical input.
        # Formula: Q_thermal = flow_rate(L/s) × 4186(J/kg·K) × ΔT_floor(°C)
        #          ΔT_floor  = Setpoint − Tc  (target supply minus actual return)
        #          COP       = Q_thermal / Power_electrical
        #
        # Uses:
        #   flow_rate = configured value (default 0.29 L/s for Eko II 6)
        #   Setpoint  = heating circuit target temperature (par36, idx 37)
        #   Tc        = heating circuit return temperature (par8, idx 9)
        #   Power     = Voltage × Current (apparent power in VA)
        #
        # Only computed when compressor is running (Frequency > 0) and
        # power is meaningful (> 50 W) to avoid nonsense values in standby.
        setpoint = params.get("Setpoint")
        frequency = params.get("Frequency")
        if (tc is not None and setpoint is not None and power_w is not None
                and frequency is not None and frequency > 5.0 and power_w > 50.0):
            dt_floor = setpoint - tc
            if dt_floor > 0.1:  # only when supply is genuinely warmer than return
                q_thermal = self._flow_rate_lps * 4186.0 * dt_floor
                params["COP_estimated"] = round(q_thermal / power_w, 2)
                params["Thermal_power"] = round(q_thermal, 1)


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
