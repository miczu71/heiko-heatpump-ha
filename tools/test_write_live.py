#!/usr/bin/env python3
"""
Live write test — bypasses HA, talks directly to the W600 SocketA.

Sends one CMD 0x05 using the patched protocol.py (55 AA header, plain
CRC-16/Modbus over body without header), then listens for the next
CMD 0x02 SETDATA from the pump and reports whether the target field
took the new value.

Usage:
  python3 test_write_live.py --host 192.168.1.100 --mn A1B2C3D4E5F6 dhw 49
  python3 test_write_live.py --host 192.168.1.100 --mn A1B2C3D4E5F6 power 1
  python3 test_write_live.py --host 192.168.1.100 --mn A1B2C3D4E5F6 mode 3

Caveats:
- This connects as a second SocketA client to the W600. If the W600 is
  in single-client mode, HA will be briefly disconnected; it reconnects
  automatically after we exit.
- Uses only the patched /config/custom_components/heiko_heatpump/protocol.py
  — so if this works, HA will work once reloaded.
"""

from __future__ import annotations

import argparse
import socket
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "heiko_heatpump"))
from protocol import (  # noqa: E402
    FrameBuffer, parse_frame,
    build_set_dhw_setpoint, build_set_setpoint, build_set_power, build_set_mode,
    build_set_heating_curve, build_set_hbh, build_set_dhw_storage,
    CMD_REALTIME, CMD_SETPARAMS,
    WRITE_IDX_DHW, WRITE_IDX_HEATING, WRITE_IDX_POWER, WRITE_IDX_MODE,
    WRITE_IDX_HEATING_CURVE, WRITE_IDX_HBH, WRITE_IDX_DHW_STORAGE,
)

W600_PORT = 8899


def read_float_at(payload: bytes, idx: int) -> float | None:
    off = 2 + idx * 4
    if off + 4 > len(payload):
        return None
    return struct.unpack_from('<f', payload, off)[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("param", choices=["dhw", "setpoint", "power", "mode", "curve", "hbh", "dhw_storage"])
    ap.add_argument("value", type=float)
    ap.add_argument("--host", required=True, help="W600 bridge IP address (e.g. 192.168.1.100)")
    ap.add_argument("--mn", required=True,
                    help="Unit MN as 12 hex chars (e.g. A1B2C3D4E5F6) — shown on W600 label or HA device info")
    ap.add_argument("--timeout", type=float, default=60.0,
                    help="seconds to wait for confirming CMD 0x02 (default 60)")
    args = ap.parse_args()
    mn_str = args.mn.replace(":", "").replace("-", "")
    if len(mn_str) != 12:
        ap.error("--mn must be exactly 12 hex characters")
    MN = bytes.fromhex(mn_str)
    W600_HOST = args.host

    if args.param == "dhw":
        frame = build_set_dhw_setpoint(MN, args.value)
        watch_idx = WRITE_IDX_DHW
        label = f"DHW setpoint = {args.value:g}°C"
    elif args.param == "setpoint":
        frame = build_set_setpoint(MN, args.value)
        watch_idx = WRITE_IDX_HEATING
        label = f"Heating setpoint = {args.value:g}°C"
    elif args.param == "power":
        frame = build_set_power(MN, bool(int(args.value)))
        watch_idx = WRITE_IDX_POWER
        label = f"Power = {'ON' if int(args.value) else 'OFF'}"
    elif args.param == "mode":
        frame = build_set_mode(MN, int(args.value))
        watch_idx = WRITE_IDX_MODE
        label = f"Mode = {int(args.value)}"
    elif args.param == "curve":
        frame = build_set_heating_curve(MN, bool(int(args.value)))
        watch_idx = WRITE_IDX_HEATING_CURVE
        label = f"Heating curve = {'ON' if int(args.value) else 'OFF'}"
    elif args.param == "hbh":
        frame = build_set_hbh(MN, bool(int(args.value)))
        watch_idx = WRITE_IDX_HBH
        label = f"Backup heater (HBH) = {'ON' if int(args.value) else 'OFF'}"
    elif args.param == "dhw_storage":
        frame = build_set_dhw_storage(MN, bool(int(args.value)))
        watch_idx = WRITE_IDX_DHW_STORAGE
        label = f"DHW storage = {'ON' if int(args.value) else 'OFF'}"

    print(f"Target: {label}")
    print(f"Frame : {frame.hex(' ')}")
    print(f"Connecting to {W600_HOST}:{W600_PORT} …")
    sock = socket.create_connection((W600_HOST, W600_PORT), timeout=10)  # noqa: F821
    sock.settimeout(5.0)

    buf = FrameBuffer()
    baseline: float | None = None
    baseline_at = time.time()

    def flush_reads():
        nonlocal baseline
        try:
            data = sock.recv(4096)
        except socket.timeout:
            return
        for raw in buf.feed(data):
            fr = parse_frame(raw)
            if fr is None:
                continue
            if fr.command == CMD_SETPARAMS:
                v = read_float_at(fr.payload, watch_idx)
                if v is not None and -1e6 < v < 1e6:
                    baseline = v
                    print(f"  baseline CMD 0x02: idx {watch_idx} = {v:g}")
            elif fr.command == CMD_REALTIME:
                v = read_float_at(fr.payload, watch_idx)
                if v is not None and -1e6 < v < 1e6 and watch_idx in (WRITE_IDX_POWER, WRITE_IDX_MODE, WRITE_IDX_HEATING):
                    # realtime also carries the current state for these indices
                    if baseline is None:
                        baseline = v
                        print(f"  baseline CMD 0x01: idx {watch_idx} = {v:g}")

    # Collect a baseline for ~8s so at least one CMD 0x01 arrives
    print("Collecting baseline (8 s) …")
    t_start = time.time()
    while time.time() - t_start < 8:
        flush_reads()

    # Send the write
    print(f"\n→ sending CMD 0x05 write: {label}")
    sock.sendall(frame)
    sent_at = time.time()

    # Watch for the value to change. DHW_Setpoint only appears in CMD 0x02
    # (every ~60 s), heating setpoint shows up in realtime too.
    print(f"Waiting up to {args.timeout:.0f}s for confirming frame …")
    while time.time() - sent_at < args.timeout:
        try:
            data = sock.recv(4096)
        except socket.timeout:
            continue
        for raw in buf.feed(data):
            fr = parse_frame(raw)
            if fr is None:
                continue
            if fr.command == CMD_SETPARAMS:
                v = read_float_at(fr.payload, watch_idx)
                if v is None:
                    continue
                delta = "  (UNCHANGED)" if baseline is not None and abs(v - baseline) < 0.01 else "  ★ CHANGED"
                print(f"[{time.time() - sent_at:5.1f}s] CMD 0x02: idx {watch_idx} = {v:g}{delta}")
                if args.param == "dhw" and abs(v - args.value) < 0.01:
                    print(f"\n✓ SUCCESS — pump accepted the write. "
                          f"idx {watch_idx} is now {v:g} (expected {args.value:g}).")
                    sock.close()
                    return 0
            elif fr.command == CMD_REALTIME and watch_idx in (WRITE_IDX_POWER, WRITE_IDX_MODE, WRITE_IDX_HEATING):
                v = read_float_at(fr.payload, watch_idx)
                if v is None:
                    continue
                if baseline is not None and abs(v - args.value) < 0.01 and abs(v - baseline) > 0.01:
                    print(f"[{time.time() - sent_at:5.1f}s] CMD 0x01: idx {watch_idx} = {v:g}  ★ CHANGED")
                    print(f"\n✓ SUCCESS — pump accepted the write. "
                          f"idx {watch_idx} is now {v:g} (expected {args.value:g}).")
                    sock.close()
                    return 0

    print(f"\n✗ TIMEOUT — no confirming frame saw idx {watch_idx} == {args.value:g} "
          f"within {args.timeout:.0f}s.")
    sock.close()
    return 1


if __name__ == "__main__":
    sys.exit(main())
