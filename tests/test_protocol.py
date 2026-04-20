"""
Unit tests for the Heiko heat pump protocol module.

Run with:
    python -m pytest tests/test_protocol.py -v

Tests cover:
  - Float extraction from example frame (empirically verified values)
  - Frame parsing (header, MN, command, payload)
  - Frame building (CMD 0x06 poll, CMD 0x05 write)
  - CRC round-trip (build frame then parse it back)
  - FrameBuffer stream reassembly
"""

import struct
import sys
import os

# Allow running without a full HA installation
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.heiko_heatpump.protocol import (
    FrameBuffer,
    build_ack_realtime,
    build_request_realtime,
    build_set_power,
    build_set_setpoint,
    build_write_param,
    crc16_modbus,
    extract_all_params,
    extract_float,
    parse_frame,
    CMD_REALTIME,
    CMD_REQ_RT,
    CMD_WRITE,
    FRAME_END,
    PAYLOAD_FLOAT_PREFIX,
)

# ── Fixture: truncated example frame from documentation ────────────────────────

# Exact bytes from the documentation example (67 bytes, payload = 54 bytes).
# Verified empirically: Tuo@payload[22:26]=47.88°C, Tui@[26:30]=44.37°C, etc.
EXAMPLE_FRAME_HEX = (
    "AA 55 01 00 00 00 00 00 00 01 B7 00 01 "   # header (13 bytes)
    "00 00 00 00 00 00 00 00 00 00 00 00 "       # payload prefix + indices 0-2 zeros
    "80 3F 00 00 "                               # index 3: 1.0 (some flag)
    "00 00 00 00 "                               # index 4: 0.0
    "1E 85 3F 42 "                              # index 5 Tuo  = 47.88 °C
    "E1 7A 31 42 "                              # index 6 Tui  = 44.37 °C
    "D7 A3 3E 42 "                              # index 7 Tup  = 47.66 °C
    "B8 1E 14 42 "                              # index 8 Tw   = 37.03 °C
    "85 EB CD 41 "                              # index 9 Tc   = 25.74 °C
    "B8 1E B5 41 "                              # index 10 Tv1 = 22.64 °C
    "47 E1 B4 41 "                              # index 11 Tv2 = 22.61 °C
    "52 B8 E6 41"                               # index 12 Tr  = 28.84 °C
)
EXAMPLE_PAYLOAD = bytes.fromhex(EXAMPLE_FRAME_HEX.replace(" ", ""))[13:]

# Test MN (6 bytes) — using the module's real MAC from the config
TEST_MN = bytes.fromhex("A1B2C3D4E5F6")


# ── Float extraction ───────────────────────────────────────────────────────────

class TestExtractFloat:
    def test_tuo_index5(self):
        """Tuo (outdoor unit outlet) at index 5 should be ~47.88°C."""
        v = extract_float(EXAMPLE_PAYLOAD, 5)
        assert v is not None
        assert abs(v - 47.88) < 0.01, f"Tuo expected ~47.88, got {v}"

    def test_tui_index6(self):
        """Tui (outdoor unit inlet) at index 6 should be ~44.37°C."""
        v = extract_float(EXAMPLE_PAYLOAD, 6)
        assert v is not None
        assert abs(v - 44.37) < 0.01, f"Tui expected ~44.37, got {v}"

    def test_tup_index7(self):
        """Tup (outdoor unit pipe) at index 7 should be ~47.66°C."""
        v = extract_float(EXAMPLE_PAYLOAD, 7)
        assert v is not None
        assert abs(v - 47.66) < 0.01

    def test_tw_index8(self):
        """Tw (water temp) at index 8 should be ~37.03°C."""
        v = extract_float(EXAMPLE_PAYLOAD, 8)
        assert v is not None
        assert abs(v - 37.03) < 0.01

    def test_tc_index9(self):
        """Tc (condenser) at index 9 should be ~25.74°C."""
        v = extract_float(EXAMPLE_PAYLOAD, 9)
        assert v is not None
        assert abs(v - 25.74) < 0.01

    def test_tr_index12(self):
        """Tr (refrigerant) at index 12 should be ~28.84°C."""
        v = extract_float(EXAMPLE_PAYLOAD, 12)
        assert v is not None
        assert abs(v - 28.84) < 0.01

    def test_out_of_bounds_returns_none(self):
        """Requesting an index beyond the available payload should return None."""
        v = extract_float(EXAMPLE_PAYLOAD, 100)
        assert v is None

    def test_payload_offset_formula(self):
        """Verify the offset formula: offset = PAYLOAD_FLOAT_PREFIX + index * 4."""
        for index in [5, 6, 7, 8, 9, 10, 11, 12]:
            expected_offset = PAYLOAD_FLOAT_PREFIX + index * 4
            if expected_offset + 4 <= len(EXAMPLE_PAYLOAD):
                raw = struct.unpack_from('<f', EXAMPLE_PAYLOAD, expected_offset)[0]
                v   = extract_float(EXAMPLE_PAYLOAD, index)
                assert v is not None
                assert abs(v - raw) < 1e-6


# ── extract_all_params ─────────────────────────────────────────────────────────

class TestExtractAllParams:
    def test_returns_dict(self):
        params = extract_all_params(EXAMPLE_PAYLOAD)
        assert isinstance(params, dict)

    def test_known_temps_present(self):
        params = extract_all_params(EXAMPLE_PAYLOAD)
        for key in ("Tuo", "Tui", "Tup", "Tw", "Tc", "Tv1", "Tv2", "Tr"):
            assert key in params, f"Missing key {key}"

    def test_high_index_params_absent_in_truncated_frame(self):
        """Params with high indices (Setpoint=38, Sw=39) require full 162-byte payload."""
        params = extract_all_params(EXAMPLE_PAYLOAD)
        # These should NOT appear when the payload is truncated to 54 bytes
        assert "Setpoint" not in params
        assert "Sw" not in params

    def test_values_are_floats(self):
        params = extract_all_params(EXAMPLE_PAYLOAD)
        for k, v in params.items():
            assert isinstance(v, float), f"{k} value is not float: {type(v)}"


# ── CRC ───────────────────────────────────────────────────────────────────────

class TestCRC:
    def test_known_vectors(self):
        """CRC-16/Modbus known test vectors."""
        # Standard Modbus CRC test: b'\x01\x04\x02\xFF\xFF' = 0x80B8
        assert crc16_modbus(b'\x01\x04\x02\xFF\xFF') == 0x80B8

    def test_empty_input(self):
        """Empty input should produce 0xFFFF (the initial value)."""
        assert crc16_modbus(b'') == 0xFFFF

    def test_single_byte(self):
        """Single byte 0x01: deterministic check."""
        result = crc16_modbus(b'\x01')
        assert isinstance(result, int)
        assert 0 <= result <= 0xFFFF


# ── Frame building ─────────────────────────────────────────────────────────────

class TestBuildFrames:
    def _parse_built(self, raw: bytes):
        """Helper: build a frame then parse it back, skipping CRC check failures."""
        assert raw[-1] == FRAME_END, "Frame must end with 0x3A"
        assert raw[0] == 0xAA and raw[1] == 0x55, "Frame must start with 0xAA 0x55"

    def test_build_request_realtime_structure(self):
        """CMD 0x06 frame should have correct structure and CRC-covered bytes."""
        raw = build_request_realtime(TEST_MN)
        # Header
        assert raw[0] == 0xAA
        assert raw[1] == 0x55
        # Target
        assert raw[2] == 0x01
        # MN
        assert raw[3:9] == TEST_MN
        # Device ID
        assert raw[9] == 0x01
        # Content length: no payload, so content_len = 0 + 1 = 1
        content_len = struct.unpack_from('<H', raw, 10)[0]
        assert content_len == 1, f"Expected content_len=1, got {content_len}"
        # Command
        assert raw[12] == CMD_REQ_RT
        # End byte
        assert raw[-1] == FRAME_END

    def test_build_request_realtime_crc_round_trip(self):
        """A self-built CMD 0x06 frame should parse cleanly (CRC computed + re-verified)."""
        raw = build_request_realtime(TEST_MN)
        frame = parse_frame(raw)
        assert frame is not None
        assert frame.command == CMD_REQ_RT
        assert frame.mn == TEST_MN
        assert frame.crc_ok is True, "CRC round-trip failed for CMD 0x06 frame"

    def test_build_set_setpoint_value(self):
        """CMD 0x05 setpoint frame should embed the correct param index and float."""
        setpoint = 45.0
        raw = build_set_setpoint(TEST_MN, setpoint)
        # Command byte is at position 12
        assert raw[12] == CMD_WRITE
        # Payload starts at byte 13; first 2 bytes = param index 38 LE
        param_idx = struct.unpack_from('<H', raw, 13)[0]
        assert param_idx == 38, f"Expected param index 38 (Setpoint), got {param_idx}"
        # Next 4 bytes = float value
        val = struct.unpack_from('<f', raw, 15)[0]
        assert abs(val - setpoint) < 0.001, f"Expected {setpoint}, got {val}"

    def test_build_set_power_on(self):
        """CMD 0x05 power-on frame should set param 39 to 1.0."""
        raw = build_set_power(TEST_MN, on=True)
        param_idx = struct.unpack_from('<H', raw, 13)[0]
        assert param_idx == 39, f"Expected param index 39 (Sw), got {param_idx}"
        val = struct.unpack_from('<f', raw, 15)[0]
        assert abs(val - 1.0) < 0.001

    def test_build_set_power_off(self):
        """CMD 0x05 power-off frame should set param 39 to 0.0."""
        raw = build_set_power(TEST_MN, on=False)
        param_idx = struct.unpack_from('<H', raw, 13)[0]
        assert param_idx == 39
        val = struct.unpack_from('<f', raw, 15)[0]
        assert abs(val - 0.0) < 0.001

    def test_write_param_crc_round_trip(self):
        """A self-built CMD 0x05 frame should parse cleanly with matching CRC."""
        raw = build_write_param(TEST_MN, 38, 48.5)
        frame = parse_frame(raw)
        assert frame is not None
        assert frame.command == CMD_WRITE
        assert frame.crc_ok is True

    def test_ack_realtime_structure(self):
        """CMD 0x03 ack frame should have correct command byte."""
        raw = build_ack_realtime(TEST_MN)
        assert raw[12] == 0x03  # CMD_ACK_RT
        assert raw[-1] == FRAME_END
        frame = parse_frame(raw)
        assert frame is not None
        assert frame.crc_ok is True


# ── parse_frame ────────────────────────────────────────────────────────────────

class TestParseFrame:
    def _make_valid_frame(self, command: int, payload: bytes) -> bytes:
        """Build a complete valid frame for testing parse_frame."""
        return build_write_param.__wrapped__ if False else build_request_realtime(TEST_MN)

    def test_parse_rejects_short_frame(self):
        assert parse_frame(b'\xAA\x55\x01') is None

    def test_parse_rejects_bad_header(self):
        raw = build_request_realtime(TEST_MN)
        corrupted = b'\x00' + raw[1:]
        assert parse_frame(corrupted) is None

    def test_parse_rejects_bad_end_byte(self):
        raw = bytearray(build_request_realtime(TEST_MN))
        raw[-1] = 0x00  # corrupt end byte
        assert parse_frame(bytes(raw)) is None

    def test_parse_good_frame_has_correct_mn(self):
        raw = build_request_realtime(TEST_MN)
        frame = parse_frame(raw)
        assert frame is not None
        assert frame.mn == TEST_MN

    def test_parse_crc_mismatch_still_returns_frame(self):
        """parse_frame returns the frame even on CRC mismatch (logs a warning)."""
        raw = bytearray(build_request_realtime(TEST_MN))
        # Corrupt one CRC byte
        raw[-3] ^= 0xFF
        frame = parse_frame(bytes(raw))
        assert frame is not None
        assert frame.crc_ok is False


# ── FrameBuffer ────────────────────────────────────────────────────────────────

class TestFrameBuffer:
    def test_single_frame_complete(self):
        """Feeding a complete frame at once should yield one frame."""
        raw = build_request_realtime(TEST_MN)
        buf = FrameBuffer()
        frames = buf.feed(raw)
        assert len(frames) == 1
        assert frames[0] == raw

    def test_fragmented_frame(self):
        """Frame split across two TCP segments should reassemble correctly."""
        raw = build_request_realtime(TEST_MN)
        half = len(raw) // 2
        buf = FrameBuffer()
        frames = buf.feed(raw[:half])
        assert frames == []  # not complete yet
        frames = buf.feed(raw[half:])
        assert len(frames) == 1
        assert frames[0] == raw

    def test_two_frames_in_one_segment(self):
        """Two complete frames in one TCP segment should yield two frames."""
        raw = build_request_realtime(TEST_MN)
        buf = FrameBuffer()
        frames = buf.feed(raw + raw)
        assert len(frames) == 2

    def test_leading_garbage_discarded(self):
        """Garbage bytes before the header should be silently discarded."""
        raw = build_request_realtime(TEST_MN)
        garbage = b'\x00\x01\x02\xDE\xAD'
        buf = FrameBuffer()
        frames = buf.feed(garbage + raw)
        assert len(frames) == 1
        assert frames[0] == raw

    def test_multiple_fragments(self):
        """Frame split into many tiny pieces should reassemble."""
        raw = build_request_realtime(TEST_MN)
        buf = FrameBuffer()
        frames = []
        for byte in raw:
            frames.extend(buf.feed(bytes([byte])))
        assert len(frames) == 1
        assert frames[0] == raw


# ── Main (run without pytest) ─────────────────────────────────────────────────

if __name__ == "__main__":
    import traceback

    suites = [
        TestExtractFloat,
        TestExtractAllParams,
        TestCRC,
        TestBuildFrames,
        TestParseFrame,
        TestFrameBuffer,
    ]

    passed = failed = 0
    for suite_cls in suites:
        suite = suite_cls()
        for name in [m for m in dir(suite_cls) if m.startswith("test_")]:
            method = getattr(suite, name)
            try:
                method()
                print(f"  PASS  {suite_cls.__name__}.{name}")
                passed += 1
            except Exception:
                print(f"  FAIL  {suite_cls.__name__}.{name}")
                traceback.print_exc()
                failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
