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
    CMD_SETPARAMS,
    MODE_STANDBY, MODE_HEATING, MODE_COOLING, MODE_DHW, MODE_AUTO,
    build_ack_realtime,
    build_request_realtime,
    build_set_power,
    build_set_mode,
    build_set_setpoint,
    build_set_dhw_setpoint,
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
        self._mn_config     = mn              # MN from config (WiFi module MAC)
        self._mn            = mn              # active MN used for writes — updated on first frame
        self._flow_rate_lps = flow_rate_lps
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
        CMD 0x01: realtime data (every ~30 s) — main sensor update path.
        CMD 0x02: setdata snapshot (every ~3 min) — reads DHW setpoint.
        """
        if frame.command == CMD_REALTIME:
            await self._handle_realtime(frame)
        elif frame.command == CMD_SETPARAMS:
            await self._handle_setdata(frame)
        # CMD 0x03/0x04/0x05 replies silently ignored

    async def _handle_setdata(self, frame: HeatPumpFrame) -> None:
        """
        Process CMD 0x02 setdata frame (sent by pump every ~3 minutes).
        Learns the pump's MN and extracts the DHW setpoint (write index 54).
        """
        if frame.mn != self._mn:
            self._mn = frame.mn

        # Extracts the DHW setpoint and merges it into the live data dict
        # so the number entity shows the current value before the user changes it.
        if len(frame.payload) < 2 + 54 * 4 + 4:
            _LOGGER.debug("CMD 0x02 payload too short for DHW setpoint (%d bytes)", len(frame.payload))
            return

        import struct as _st
        dhw_offset = 2 + 54 * 4   # same offset formula as realdata
        dhw_val = _st.unpack_from('<f', frame.payload, dhw_offset)[0]
        if -1e6 < dhw_val < 1e6 and dhw_val > 0:
            if self._latest_data:
                self._latest_data["DHW_Setpoint"] = round(dhw_val, 1)
                self.async_set_updated_data(self._latest_data)
                _LOGGER.debug("CMD 0x02: DHW setpoint = %.1f°C", dhw_val)

    async def _handle_realtime(self, frame: HeatPumpFrame) -> None:
        """Process a CMD 0x01 realtime data frame."""

        # Learn the pump's actual MN from its own frames.
        # The config MN is the WiFi module's MAC; the pump's MN in its frames
        # is what we must use in CMD 0x05 write commands.
        if frame.mn != self._mn:
            _LOGGER.info(
                "Updating write MN from config (%s) to pump MN (%s)",
                self._mn.hex(':'), frame.mn.hex(':'),
            )
            self._mn = frame.mn

        params = extract_all_params(frame.payload)

        if not params:
            _LOGGER.warning("CMD 0x01 frame yielded no parameters (payload too short?)")
            return

        # ── Preserve slow-updating values from CMD 0x02 setdata frames ────────
        # DHW_Setpoint is only updated every ~3 min from CMD 0x02.
        # Carry it forward into every realtime update so it doesn't vanish
        # between setdata frames.
        if "DHW_Setpoint" in self._latest_data:
            params["DHW_Setpoint"] = self._latest_data["DHW_Setpoint"]

        # ── Calculated / derived sensors ──────────────────────────────────────
        tuo = params.get("Tuo")
        tui = params.get("Tui")
        if tuo is not None and tui is not None:
            params["DeltaT"] = round(tuo - tui, 2)

        voltage = params.get("Voltage")
        current = params.get("Current")
        power_w: float | None = None
        if voltage is not None and current is not None:
            power_w = round(voltage * current, 1)
            params["Power"] = power_w

        tw = params.get("Tw")
        tc = params.get("Tc")
        if tw is not None and tc is not None:
            params["DeltaT_water"] = round(tw - tc, 2)

        ta = params.get("Ta")
        if tw is not None and ta is not None:
            tw_k = tw + 273.15
            ta_k = ta + 273.15
            denom = tw_k - ta_k
            if denom > 0.1:
                params["COP_carnot"] = round(tw_k / denom, 2)

        setpoint = params.get("Setpoint")
        frequency = params.get("Frequency")
        if (tc is not None and setpoint is not None and power_w is not None
                and frequency is not None and frequency > 5.0 and power_w > 50.0):
            dt_floor = setpoint - tc
            if dt_floor > 0.1:
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

    # ── Write commands (all indices verified by CMD 0x05 traffic capture) ────

    async def async_set_power(self, on: bool) -> None:
        """Turn pump on/off. Write index 0: 1.0=on, 0.0=off."""
        await self._send_write(build_set_power(self._mn, on),
                               f"Power → {'ON' if on else 'OFF'}")

    async def async_set_mode(self, mode: int) -> None:
        """
        Set working mode. Write index 3.
        Use MODE_* constants: MODE_HEATING=1, MODE_DHW=3, MODE_AUTO=4, MODE_STANDBY=0.
        """
        await self._send_write(build_set_mode(self._mn, mode),
                               f"Mode → {mode}")

    async def async_set_setpoint(self, setpoint_celsius: float) -> None:
        """Set heating circuit water setpoint. Write index 37."""
        await self._send_write(build_set_setpoint(self._mn, setpoint_celsius),
                               f"Heating setpoint → {setpoint_celsius:.1f}°C")

    async def async_set_dhw_setpoint(self, setpoint_celsius: float) -> None:
        """Set DHW (hot water) target temperature. Write index 54."""
        await self._send_write(build_set_dhw_setpoint(self._mn, setpoint_celsius),
                               f"DHW setpoint → {setpoint_celsius:.1f}°C")

    async def _send_write(self, frame_bytes: bytes, description: str) -> None:
        """Send a CMD 0x05 write frame and log it."""
        ok = await self._client.send(frame_bytes)
        if not ok:
            raise RuntimeError(f"Failed to send write command: {description}")
        _LOGGER.info("Write: %s", description)
