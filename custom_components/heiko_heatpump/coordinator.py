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
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue, async_delete_issue
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN, DEFAULT_FLOW_RATE
from .protocol import (
    HeatPumpFrame,
    CMD_REALTIME,
    CMD_SETPARAMS,
    MODE_STANDBY, MODE_HEATING, MODE_COOLING, MODE_DHW, MODE_AUTO,
    build_ack_realtime,
    build_ack_setparams,
    build_request_realtime,
    build_set_power,
    build_set_mode,
    build_set_setpoint,
    build_set_dhw_setpoint,
    build_set_heating_curve,
    build_set_hbh,
    build_set_dhw_storage,
    build_set_curve_parallel,
    build_set_heating_stops_dt,
    build_set_heating_restarts_dt,
    build_set_dhw_restart_dt,
    build_set_curve_amb_point,
    build_set_curve_water_point,
    extract_all_params,
)
from .tcp_client import HeikoTCPClient

_LOGGER = logging.getLogger(__name__)

# How often to actively poll (CMD 0x06) as a fallback.
# The pump pushes every 30 s; we poll at 60 s to avoid unnecessary traffic.
POLL_INTERVAL = timedelta(seconds=60)
_STALE_THRESHOLD = timedelta(minutes=5)
_ISSUE_ID = "pump_not_responding"


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
        self._mn_config       = mn
        self._mn              = mn
        self._flow_rate_lps   = flow_rate_lps
        self._client          = HeikoTCPClient(host, port, self._on_frame, self._on_connection_change)
        self._latest_data: dict[str, float] = {}
        self._last_seen: datetime | None = None
        self._reconnect_count: int = 0
        self._ever_connected: bool = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_start(self) -> None:
        """Start the TCP client. Called from async_setup_entry."""
        await self._client.start()

    async def async_stop(self) -> None:
        """Stop the TCP client. Called from async_unload_entry."""
        await self._client.stop()

    @property
    def connected(self) -> bool:
        return self._client.connected

    @property
    def last_seen(self) -> datetime | None:
        return self._last_seen

    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count

    async def _on_connection_change(self, is_connected: bool) -> None:
        """Called by HeikoTCPClient when the TCP connection is established or lost."""
        if is_connected:
            if self._ever_connected:
                self._reconnect_count += 1
            else:
                self._ever_connected = True
        _LOGGER.info("Heat pump bridge connection: %s", "connected" if is_connected else "disconnected")
        self.async_set_updated_data(self._latest_data)

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
        if self._last_seen is not None:
            age = dt_util.utcnow() - self._last_seen
            if age > _STALE_THRESHOLD:
                async_create_issue(
                    self.hass,
                    DOMAIN,
                    _ISSUE_ID,
                    is_fixable=False,
                    severity=IssueSeverity.WARNING,
                    translation_key=_ISSUE_ID,
                    translation_placeholders={
                        "minutes": str(int(age.total_seconds() / 60)),
                        "last_seen": self._last_seen.astimezone().strftime("%H:%M:%S"),
                    },
                )

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
        self._last_seen = dt_util.utcnow()
        async_delete_issue(self.hass, DOMAIN, _ISSUE_ID)
        if frame.command == CMD_REALTIME:
            await self._handle_realtime(frame)
        elif frame.command == CMD_SETPARAMS:
            await self._handle_setdata(frame)
        # CMD 0x03/0x04/0x05 replies silently ignored

    async def _handle_setdata(self, frame: HeatPumpFrame) -> None:
        """
        Process CMD 0x02 setdata frame.

        Sends CMD 0x04 ACK — the cloud server always does this; omitting it
        may cause the pump to distrust the client and ignore CMD 0x05 writes.

        Extracts slow-changing state values not present in CMD 0x01 realtime frames:
        DHW_Setpoint, Power_State, HeatingCurve_State, HBH_State, DHWStorage_State.
        """
        if frame.mn != self._mn:
            self._mn = frame.mn

        # Always ACK the set-params frame (CMD 0x04)
        ack = build_ack_setparams(frame.mn, target=frame.target, device_id=frame.device_id)
        await self._client.send(ack)

        import struct as _st

        def _read_float(idx: int) -> float | None:
            off = 2 + idx * 4
            if len(frame.payload) >= off + 4:
                v = _st.unpack_from('<f', frame.payload, off)[0]
                if -1e6 < v < 1e6:
                    return v
            return None

        changed = False

        # DHW setpoint — idx 54
        v = _read_float(54)
        if v is not None and v > 0:
            self._latest_data["DHW_Setpoint"] = round(v, 1)
            changed = True
            _LOGGER.debug("CMD 0x02: DHW setpoint = %.1f°C", v)

        # Power state — idx 0: 0.0=off, 1.0=on
        v = _read_float(0)
        if v is not None:
            self._latest_data["Power_State"] = float(round(v))
            changed = True
            _LOGGER.debug("CMD 0x02: Power = %.0f", v)

        # Working mode (write-side convention) — idx 3: same as par4 in cloud API
        # 0=Standby, 1=Heating, 2=Cooling, 3=DHW, 4=Auto
        v = _read_float(3)
        if v is not None:
            self._latest_data["Mode_Setdata"] = float(round(v))
            changed = True
            _LOGGER.debug("CMD 0x02: Mode_Setdata = %.0f", v)

        # Heating curve — idx 23: 0.0=off, 1.0=on
        v = _read_float(23)
        if v is not None:
            self._latest_data["HeatingCurve_State"] = float(round(v))
            changed = True
            _LOGGER.debug("CMD 0x02: HeatingCurve = %.0f", v)

        # HBH backup heater — idx 50: inverted (0.0=enabled, 1.0=disabled)
        v = _read_float(50)
        if v is not None:
            self._latest_data["HBH_State"] = float(round(v))
            changed = True
            _LOGGER.debug("CMD 0x02: HBH = %.0f (0=on, 1=off)", v)

        # DHW storage — idx 62: 0.0=off, 1.0=on
        v = _read_float(62)
        if v is not None:
            self._latest_data["DHWStorage_State"] = float(round(v))
            changed = True
            _LOGGER.debug("CMD 0x02: DHWStorage = %.0f", v)

        # Heating/cooling stop ΔT — idx 19
        v = _read_float(19)
        if v is not None and v > 0:
            self._latest_data["Heating_Stops_DT"] = round(v, 1)
            changed = True
            _LOGGER.debug("CMD 0x02: Heating_Stops_DT = %.1f°C", v)

        # Heating/cooling restart ΔT — idx 20
        v = _read_float(20)
        if v is not None and v > 0:
            self._latest_data["Heating_Restarts_DT"] = round(v, 1)
            changed = True
            _LOGGER.debug("CMD 0x02: Heating_Restarts_DT = %.1f°C", v)

        # DHW restart ΔT — idx 55
        v = _read_float(55)
        if v is not None and v > 0:
            self._latest_data["DHW_Restart_DT"] = round(v, 1)
            changed = True
            _LOGGER.debug("CMD 0x02: DHW_Restart_DT = %.1f°C", v)

        # Heating curve parallel shift — idx 120 (may be absent if payload is short)
        v = _read_float(120)
        if v is not None:
            self._latest_data["Curve_Parallel"] = round(v, 1)
            changed = True
            _LOGGER.debug("CMD 0x02: Curve_Parallel = %.1f", v)

        # Heating curve ambient temp breakpoints — idx 24–28 (points 1–5)
        for _pt in range(1, 6):
            v = _read_float(23 + _pt)
            if v is not None:
                self._latest_data[f"Curve_Amb_{_pt}"] = round(v, 1)
                changed = True
        _LOGGER.debug("CMD 0x02: Curve_Amb = %s",
                      [self._latest_data.get(f"Curve_Amb_{p}") for p in range(1, 6)])

        # Heating curve water temp breakpoints — idx 29–33 (points 1–5)
        for _pt in range(1, 6):
            v = _read_float(28 + _pt)
            if v is not None:
                self._latest_data[f"Curve_Water_{_pt}"] = round(v, 1)
                changed = True
        _LOGGER.debug("CMD 0x02: Curve_Water = %s",
                      [self._latest_data.get(f"Curve_Water_{p}") for p in range(1, 6)])

        if changed and self._latest_data:
            self.async_set_updated_data(self._latest_data)

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
        # These keys are only set when a CMD 0x02 arrives. Carry them forward
        # into every realtime update so they don't vanish between setdata frames.
        for _key in (
            "DHW_Setpoint", "Power_State", "Mode_Setdata",
            "HeatingCurve_State", "HBH_State", "DHWStorage_State",
            "Heating_Stops_DT", "Heating_Restarts_DT", "DHW_Restart_DT",
            "Curve_Parallel",
            "Curve_Amb_1", "Curve_Amb_2", "Curve_Amb_3", "Curve_Amb_4", "Curve_Amb_5",
            "Curve_Water_1", "Curve_Water_2", "Curve_Water_3", "Curve_Water_4", "Curve_Water_5",
        ):
            if _key in self._latest_data:
                params[_key] = self._latest_data[_key]

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

        frequency = params.get("Frequency")
        if (tw is not None and tc is not None and power_w is not None
                and frequency is not None and frequency > 5.0 and power_w > 50.0):
            dt_floor = tw - tc
            # Cap ΔT at 15 °C: a larger delta means Tw and Tc are from different
            # circuits (e.g. DHW tank vs. heating return), producing a bogus COP.
            if 0.5 < dt_floor <= 15.0:
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

    async def async_set_heating_curve(self, on: bool) -> None:
        """Enable/disable heating curve. Write index 23: 1.0=on, 0.0=off."""
        await self._send_write(build_set_heating_curve(self._mn, on),
                               f"Heating curve → {'ON' if on else 'OFF'}")

    async def async_set_hbh(self, on: bool) -> None:
        """Enable/disable backup heater (HBH). Write index 48: inverted (0.0=on, 1.0=off)."""
        await self._send_write(build_set_hbh(self._mn, on),
                               f"Backup heater (HBH) → {'ON' if on else 'OFF'}")

    async def async_set_dhw_storage(self, on: bool) -> None:
        """Enable/disable DHW storage. Write index 62: 1.0=on, 0.0=off."""
        await self._send_write(build_set_dhw_storage(self._mn, on),
                               f"DHW storage → {'ON' if on else 'OFF'}")

    async def async_set_curve_parallel(self, value: float) -> None:
        """Set heating curve parallel shift. Write index 120. Range −9 to +9."""
        await self._send_write(build_set_curve_parallel(self._mn, value),
                               f"Curve parallel shift → {value:+.0f}")

    async def async_set_heating_stops_dt(self, value: float) -> None:
        """Set heating/cooling stop ΔT. Write index 19."""
        await self._send_write(build_set_heating_stops_dt(self._mn, value),
                               f"Heating stops ΔT → {value:.1f}°C")

    async def async_set_heating_restarts_dt(self, value: float) -> None:
        """Set heating/cooling restart ΔT. Write index 20."""
        await self._send_write(build_set_heating_restarts_dt(self._mn, value),
                               f"Heating restarts ΔT → {value:.1f}°C")

    async def async_set_dhw_restart_dt(self, value: float) -> None:
        """Set DHW restart ΔT. Write index 55."""
        await self._send_write(build_set_dhw_restart_dt(self._mn, value),
                               f"DHW restart ΔT → {value:.1f}°C")

    async def async_set_curve_amb_1(self, value: float) -> None:
        await self._send_write(build_set_curve_amb_point(self._mn, 1, value),
                               f"Curve ambient point 1 → {value:.1f}°C")

    async def async_set_curve_amb_2(self, value: float) -> None:
        await self._send_write(build_set_curve_amb_point(self._mn, 2, value),
                               f"Curve ambient point 2 → {value:.1f}°C")

    async def async_set_curve_amb_3(self, value: float) -> None:
        await self._send_write(build_set_curve_amb_point(self._mn, 3, value),
                               f"Curve ambient point 3 → {value:.1f}°C")

    async def async_set_curve_amb_4(self, value: float) -> None:
        await self._send_write(build_set_curve_amb_point(self._mn, 4, value),
                               f"Curve ambient point 4 → {value:.1f}°C")

    async def async_set_curve_amb_5(self, value: float) -> None:
        await self._send_write(build_set_curve_amb_point(self._mn, 5, value),
                               f"Curve ambient point 5 → {value:.1f}°C")

    async def async_set_curve_water_1(self, value: float) -> None:
        await self._send_write(build_set_curve_water_point(self._mn, 1, value),
                               f"Curve water point 1 → {value:.1f}°C")

    async def async_set_curve_water_2(self, value: float) -> None:
        await self._send_write(build_set_curve_water_point(self._mn, 2, value),
                               f"Curve water point 2 → {value:.1f}°C")

    async def async_set_curve_water_3(self, value: float) -> None:
        await self._send_write(build_set_curve_water_point(self._mn, 3, value),
                               f"Curve water point 3 → {value:.1f}°C")

    async def async_set_curve_water_4(self, value: float) -> None:
        await self._send_write(build_set_curve_water_point(self._mn, 4, value),
                               f"Curve water point 4 → {value:.1f}°C")

    async def async_set_curve_water_5(self, value: float) -> None:
        await self._send_write(build_set_curve_water_point(self._mn, 5, value),
                               f"Curve water point 5 → {value:.1f}°C")

    async def _send_write(self, frame_bytes: bytes, description: str) -> None:
        """Send a CMD 0x05 write frame and log it."""
        ok = await self._client.send(frame_bytes)
        if not ok:
            raise RuntimeError(f"Failed to send write command: {description}")
        _LOGGER.info("Write: %s", description)
