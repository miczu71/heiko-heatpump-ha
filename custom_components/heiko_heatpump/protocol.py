"""
Heiko / Neoheat / ECOtouch heat pump RS-485 binary protocol implementation.

Frame structure (all multi-byte integers little-endian unless noted):
  ┌──────────┬────────┬────────────────┬──────────┬───────────────────┬─────────┬────────────────────────┬───────────────┬──────┐
  │ 0xAA 0x55│ Target │ MN (6 bytes)   │ DevID    │ Content len (2 B) │ Command │ Payload (n bytes)      │  CRC-16 (2 B) │ 0x3A │
  │  2 bytes │ 1 byte │ unit unique ID │  1 byte  │  = n+1, LE        │  1 byte │  parameter floats etc  │   Modbus LE   │ end  │
  └──────────┴────────┴────────────────┴──────────┴───────────────────┴─────────┴────────────────────────┴───────────────┴──────┘

Total header before payload = 13 bytes.

Payload layout for CMD 0x01 (realtime data):
  - Bytes 0-1:  2-byte sub-header / unknown prefix (always observed as 00 00 in example)
  - Bytes 2+:   IEEE 754 little-endian float array, indexed by parameter index.
                Parameter at index i lives at payload offset = 2 + i * 4.

⚠ CRC algorithm: CRC-16/Modbus (poly 0x8005, init 0xFFFF, reflect in/out, no final XOR).
  This is the standard for RS-485/Modbus devices and is consistent with the protocol family.
  It CANNOT be verified from the provided truncated example frame (frame ends before CRC bytes).
  If CRC mismatches occur at runtime, try CRC-16/CCITT as an alternative (see crc16_ccitt below).
"""

from __future__ import annotations

import struct
import logging
from dataclasses import dataclass
from typing import Optional

_LOGGER = logging.getLogger(__name__)

# ── Frame constants ────────────────────────────────────────────────────────────
FRAME_HEADER   = bytes([0xAA, 0x55])
FRAME_END      = 0x3A
CMD_REALTIME   = 0x01   # unit → server: realtime sensor data (every ~30 s)
CMD_SETPARAMS  = 0x02   # unit → server: set-parameter snapshot (every ~3 min)
CMD_ACK_RT     = 0x03   # server → unit: acknowledge realtime data
CMD_ACK_SET    = 0x04   # server → unit: acknowledge set-parameter data
CMD_WRITE      = 0x05   # server → unit: write a parameter value
CMD_REQ_RT     = 0x06   # server → unit: request realtime data
CMD_REQ_SET    = 0x07   # server → unit: request set parameters

# Header length before payload: AA(2)+Target(1)+MN(6)+DevID(1)+Len(2)+Cmd(1) = 13
HEADER_LEN = 13

# Payload layout for CMD 0x01: 2-byte sub-prefix then float array
# payload_offset(index) = PAYLOAD_FLOAT_PREFIX + index * 4
PAYLOAD_FLOAT_PREFIX = 2

# ── Parameter index map ────────────────────────────────────────────────────────
# Maps internal key → (payload_index, unit, description)
#
# Payload offset formula:
#   payload_offset = 2 + index * 4
#   (2-byte sub-header prefix before the float array, empirically confirmed)
#
# IMPORTANT — two index zones:
#   Indices  5–13 : community table index used directly
#   Indices 14+   : community table index MINUS ONE (the table is 1-based
#                   for this group; all entities in this range were off by
#                   one slot and have been corrected)
#
# Every index below has been verified against the live cloud API JSON:
#   par20=0→90Hz running, par21=200(EEV), par22=11.3bar, par23=11.2bar,
#   par24=14.3°C(Ta), par30=0.1→6.2A running, par31=240V,
#   par33=1(WaterPump), par36=22°C(Setpoint), par18=0(standby)/2(heating)
PARAM_MAP: dict[str, tuple[int, str, str]] = {

    # ── Outdoor unit temperatures  (indices 5–7, cloud par4–6) ────────────────
    "Tuo":         ( 5,  "°C",    "Outdoor unit outlet temperature"),
    "Tui":         ( 6,  "°C",    "Outdoor unit inlet temperature"),
    "Tup":         ( 7,  "°C",    "Outdoor unit pipe temperature"),

    # ── Water / refrigerant circuit  (indices 8–12, cloud par7–11) ───────────
    # Tw (par7): DHW temperature in standby/DHW mode; heating water in heat mode
    "Tw":          ( 8,  "°C",    "Water / DHW temperature (context-dependent)"),
    "Tc":          ( 9,  "°C",    "Heating water temperature"),
    "Tv1":         (10,  "°C",    "EEV temperature sensor 1 (−99 = not fitted)"),
    "Tv2":         (11,  "°C",    "EEV temperature sensor 2 (−99 = not fitted)"),
    "Tr":          (12,  "°C",    "Room temperature"),

    # ── Index 13 / cloud par12 ────────────────────────────────────────────────
    "PWM":         (13,  "%",     "PWM duty cycle (community table index 13)"),

    # ══════════════════════════════════════════════════════════════════════════
    # ALL INDICES BELOW ARE TABLE-INDEX MINUS ONE
    # Community table says e.g. "index 22 = Frequency" but the actual payload
    # slot is 21.  Every entry from here uses the corrected (table − 1) value.
    # ══════════════════════════════════════════════════════════════════════════

    # ── Working mode  (corrected index 19, cloud par18) ───────────────────────
    # par18=0 in standby, 2 in heating (confirmed live).
    # Values: 0=Standby, 1=DHW, 2=Heating, 3=Cooling, 4=DHW+Heating, 5=DHW+Cooling
    "WorkingMode": (19,  "",      "Working mode: 0=Standby 1=DHW 2=Heat 3=Cool 4=DHW+Heat 5=DHW+Cool"),

    # ── Compressor & fans  (corrected indices 21–30, cloud par20–29) ──────────
    # par20=0Hz standby / 90Hz heating (confirmed live)
    # par21=200 EEV steps (confirmed)
    # par28/29=fan speeds (0 in standby)
    "Frequency":   (21,  "Hz",    "Compressor frequency"),
    "EEV":         (22,  "steps", "Expansion valve opening in steps"),
    "Fan1":        (29,  "rpm",   "Fan 1 speed"),
    "Fan2":        (30,  "rpm",   "Fan 2 speed"),

    # ── Pressures  (corrected indices 23–24, cloud par22–23) ─────────────────
    "Pd":          (23,  "bar",   "High-side pressure (discharge)"),
    "Ps":          (24,  "bar",   "Low-side pressure (suction)"),

    # ── Temperatures  (corrected indices 25–28, cloud par24–27) ──────────────
    # Ta=14.3°C confirmed ambient (cloud par24, corrected idx 25)
    # Td/Ts/Tp: confirmed names from user
    "Ta":          (25,  "°C",    "Ambient air temperature"),
    "Td":          (26,  "°C",    "Discharge temperature Td"),
    "Ts":          (27,  "°C",    "Suction temperature Ts"),
    "Tp":          (28,  "°C",    "Pipe temperature Tp"),

    # ── Electrical  (corrected indices 31–32, cloud par30–31) ────────────────
    # par30=0.1A standby / 6.2A heating (confirmed live)
    # par31=240V (confirmed)
    "Current":     (31,  "A",     "Compressor current"),
    "Voltage":     (32,  "V",     "Supply voltage"),

    # ── Water pump  (corrected index 34, cloud par33) ─────────────────────────
    # par33=1.0 = pump running (confirmed via HTML diagram)
    "WaterPump":   (34,  "",      "Water pump state: 1.0 = running, 0.0 = stopped"),

    # ── Heating setpoint  (corrected index 37, cloud par36) ───────────────────
    # par36=22.0°C = floor/radiator heating circuit target (confirmed)
    "Setpoint":    (37,  "°C",    "Heating water setpoint"),

    # ── Working-time counters  (corrected indices 42–44, cloud par41–43) ──────
    # par43=314 min HWTBH confirmed
    "Time_AH":     (42,  "min",   "AH auxiliary heater working time"),
    "Time_HBH":    (43,  "min",   "HBH backup heater working time"),
    "Time_HWTBH":  (44,  "min",   "HWTBH hot-water backup heater working time"),
}


# ── CRC-16/Modbus ─────────────────────────────────────────────────────────────
def crc16_modbus(data: bytes) -> int:
    """
    CRC-16/Modbus: poly=0x8005, init=0xFFFF, reflect input and output, no final XOR.
    This is the standard CRC for RS-485 Modbus-family devices.

    ⚠ UNVERIFIED: The example frame in the documentation is truncated before the CRC
      bytes; this algorithm is chosen based on the protocol family (RS-485, Modbus-like).
      If you observe consistent CRC failures, try crc16_ccitt() instead and update
      CHOSEN_CRC below.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001  # reflected poly of 0x8005
            else:
                crc >>= 1
    return crc & 0xFFFF


def crc16_ccitt(data: bytes) -> int:
    """Alternative: CRC-16/CCITT (poly=0x1021, init=0xFFFF). Try if Modbus fails."""
    crc = 0xFFFF
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
        crc &= 0xFFFF
    return crc


# Active CRC function — change to crc16_ccitt if Modbus proves wrong at runtime
_compute_crc = crc16_modbus


# ── Frame parsing ──────────────────────────────────────────────────────────────
@dataclass
class HeatPumpFrame:
    target: int
    mn: bytes           # 6-byte unit unique ID
    device_id: int
    command: int
    payload: bytes
    crc_ok: bool        # True if received CRC matched computed CRC


def parse_frame(raw: bytes) -> Optional[HeatPumpFrame]:
    """
    Parse a complete raw frame from the TCP bridge into a HeatPumpFrame.

    Returns None if the frame is malformed (wrong header, too short, etc.).
    Logs a warning (but still returns the frame) if CRC does not match.
    """
    # Minimum frame: header(2)+target(1)+MN(6)+devID(1)+len(2)+cmd(1)+crc(2)+end(1) = 16
    if len(raw) < 16:
        _LOGGER.debug("Frame too short: %d bytes", len(raw))
        return None

    # Validate header
    if raw[0] != 0xAA or raw[1] != 0x55:
        _LOGGER.debug("Bad header: %02X %02X", raw[0], raw[1])
        return None

    # Validate end byte
    if raw[-1] != FRAME_END:
        _LOGGER.debug("Bad end byte: %02X", raw[-1])
        return None

    target    = raw[2]
    mn        = raw[3:9]                         # 6-byte unit ID
    device_id = raw[9]
    # Content length field (LE uint16): = payload_len + 1 (includes command byte)
    content_len = struct.unpack_from('<H', raw, 10)[0]
    command   = raw[12]

    payload_len = content_len - 1  # subtract command byte
    payload_end = 13 + payload_len

    # Validate total frame length: header(13) + payload + crc(2) + end(1)
    expected_total = 13 + payload_len + 2 + 1
    if len(raw) < expected_total:
        _LOGGER.debug(
            "Frame too short for declared payload: got %d, need %d",
            len(raw), expected_total
        )
        return None

    payload    = raw[13:payload_end]
    recv_crc   = struct.unpack_from('<H', raw, payload_end)[0]  # CRC is LE uint16

    # CRC covers everything from the start of the frame up to (but not including) the CRC bytes
    computed_crc = _compute_crc(raw[:payload_end])
    crc_ok = (recv_crc == computed_crc)

    if not crc_ok:
        _LOGGER.warning(
            "CRC mismatch: received 0x%04X, computed 0x%04X. "
            "Frame may be corrupted or CRC algorithm is wrong.",
            recv_crc, computed_crc
        )

    return HeatPumpFrame(
        target=target,
        mn=mn,
        device_id=device_id,
        command=command,
        payload=payload,
        crc_ok=crc_ok,
    )


def extract_float(payload: bytes, param_index: int) -> Optional[float]:
    """
    Extract a single IEEE 754 little-endian float from the payload.

    payload_offset = PAYLOAD_FLOAT_PREFIX + param_index * 4
                   = 2 + param_index * 4

    Empirically confirmed against example frame:
      index 5 (Tuo) → payload[22:26] = 47.88 °C  ✓
      index 6 (Tui) → payload[26:30] = 44.37 °C  ✓
      index 8 (Tw)  → payload[34:38] = 37.03 °C  ✓
    """
    offset = PAYLOAD_FLOAT_PREFIX + param_index * 4
    if offset + 4 > len(payload):
        return None
    value = struct.unpack_from('<f', payload, offset)[0]
    # Sanity-filter NaN / Inf that could appear from corrupt data
    if not (-1e6 < value < 1e6):
        return None
    return float(value)


def extract_all_params(payload: bytes) -> dict[str, float]:
    """Extract all known named parameters from a CMD 0x01 payload."""
    result: dict[str, float] = {}
    for name, (index, unit, desc) in PARAM_MAP.items():
        value = extract_float(payload, index)
        if value is not None:
            result[name] = value
    return result


# ── Frame building ─────────────────────────────────────────────────────────────
def _build_frame(
    target: int,
    mn: bytes,
    device_id: int,
    command: int,
    payload: bytes,
) -> bytes:
    """
    Assemble a complete frame ready to send over TCP.

    Layout:
      AA 55 | target | MN(6) | devID | content_len(2,LE) | command | payload(n) | CRC(2,LE) | 3A
    """
    assert len(mn) == 6, "MN must be exactly 6 bytes"

    # content_len = len(payload) + 1 (the +1 accounts for the command byte)
    content_len = len(payload) + 1

    # Build everything except CRC and end byte
    frame_body = (
        FRAME_HEADER
        + bytes([target])
        + mn
        + bytes([device_id])
        + struct.pack('<H', content_len)
        + bytes([command])
        + payload
    )

    crc = _compute_crc(frame_body)
    return frame_body + struct.pack('<H', crc) + bytes([FRAME_END])


def build_request_realtime(mn: bytes, target: int = 0x01, device_id: int = 0x01) -> bytes:
    """
    Build CMD 0x06: server requests realtime data from unit.
    The unit should reply immediately with a CMD 0x01 frame.
    Payload is empty (the command itself is the full request).
    """
    return _build_frame(
        target=target,
        mn=mn,
        device_id=device_id,
        command=CMD_REQ_RT,
        payload=b'',
    )


def build_ack_realtime(mn: bytes, target: int = 0x01, device_id: int = 0x01) -> bytes:
    """
    Build CMD 0x03: server acknowledges receipt of realtime data.
    Send this in response to each CMD 0x01 frame from the unit.
    """
    return _build_frame(
        target=target,
        mn=mn,
        device_id=device_id,
        command=CMD_ACK_RT,
        payload=b'',
    )


def build_write_param(
    mn: bytes,
    param_index: int,
    value: float,
    target: int = 0x01,
    device_id: int = 0x01,
) -> bytes:
    """
    Build CMD 0x05: server writes a parameter value to the unit.

    The payload format for CMD 0x05 is assumed to be:
      - 2-byte parameter index (LE uint16)
      - 4-byte IEEE 754 float value (LE)

    ⚠ NOTE: The exact CMD 0x05 payload format is inferred from the protocol family.
      Monitor raw traffic when writing to verify. The unit should respond immediately.

    Common use cases:
      build_write_param(mn, 38, 45.0)  → set Setpoint to 45°C
      build_write_param(mn, 39, 1.0)   → turn unit ON
      build_write_param(mn, 39, 0.0)   → turn unit OFF
    """
    payload = struct.pack('<H', param_index) + struct.pack('<f', value)
    return _build_frame(
        target=target,
        mn=mn,
        device_id=device_id,
        command=CMD_WRITE,
        payload=payload,
    )


def build_set_setpoint(mn: bytes, setpoint_celsius: float, **kwargs) -> bytes:
    """Convenience wrapper: set heating water setpoint (param index 37, community table index 38)."""
    return build_write_param(mn, PARAM_MAP["Setpoint"][0], setpoint_celsius, **kwargs)


def build_set_power(mn: bytes, on: bool, **kwargs) -> bytes:
    """
    Convenience wrapper: turn heat pump on (True) or off (False).
    Writes to param index 39 (community table 'Sw', one above Setpoint at 38).
    ⚠ Verify this index by monitoring raw CMD 0x05 traffic from the cloud app.
    """
    return build_write_param(mn, 39, 1.0 if on else 0.0, **kwargs)


# ── Frame stream parser ────────────────────────────────────────────────────────
class FrameBuffer:
    """
    Accumulates raw TCP bytes and yields complete frames.

    The USR-W600 transparent bridge may split or merge TCP segments arbitrarily,
    so we must buffer bytes and search for complete frames by header + length.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        """
        Feed new bytes into the buffer.
        Returns a list of complete raw frame bytes (may be empty).
        """
        self._buf.extend(data)
        return self._extract_frames()

    def _extract_frames(self) -> list[bytes]:
        frames: list[bytes] = []
        while True:
            frame = self._try_extract_one()
            if frame is None:
                break
            frames.append(frame)
        return frames

    def _try_extract_one(self) -> Optional[bytes]:
        buf = self._buf

        # Search for header 0xAA 0x55
        while len(buf) >= 2:
            if buf[0] == 0xAA and buf[1] == 0x55:
                break
            buf.pop(0)  # discard leading garbage byte

        # Need at least 13 bytes to read content_len
        if len(buf) < 13:
            return None

        # Parse content_len from bytes 10-11 (LE uint16)
        content_len = struct.unpack_from('<H', buf, 10)[0]
        payload_len = content_len - 1  # subtract command byte

        # Total frame size: header(13) + payload + crc(2) + end(1)
        total = 13 + payload_len + 3
        if len(buf) < total:
            return None  # not enough data yet

        # Extract candidate frame
        candidate = bytes(buf[:total])

        # Validate end byte
        if candidate[-1] != FRAME_END:
            # Not a valid frame at this position; skip one byte and retry
            buf.pop(0)
            return None

        # Consume the frame from buffer
        del buf[:total]
        return candidate
