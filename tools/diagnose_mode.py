"""
Heiko Heat Pump — Working Mode Diagnostic Tool
===============================================
Run this on the same machine as Home Assistant (or any machine on the LAN).

It connects to the USR-W600 bridge, captures one CMD 0x01 realtime frame,
and prints every non-zero float slot with its value.

Run it WHILE THE PUMP IS IN A KNOWN MODE (e.g. Heating = 2.0, DHW = 1.0)
and look for a slot containing that value. That slot number is the correct
WorkingMode index.

Usage:
    python3 diagnose_mode.py
    python3 diagnose_mode.py --host 192.168.0.82 --port 8899
"""

import socket
import struct
import time
import argparse

HOST = "192.168.0.82"
PORT = 8899

KNOWN_SLOTS = {
    5:  "Tuo  (outdoor outlet)",
    6:  "Tui  (outdoor inlet)",
    7:  "Tup  (outdoor pipe)",
    8:  "Tw   (water/DHW temp)",
    9:  "Tc   (heating water)",
    12: "Tr   (room temp)",
    13: "PWM",
    19: "WorkingMode ← CURRENT GUESS",
    21: "Frequency (Hz)",
    22: "EEV (steps)",
    23: "Pd   (high-side pressure)",
    24: "Ps   (low-side pressure)",
    25: "Ta   (ambient)",
    26: "Td   (discharge)",
    27: "Ts   (suction)",
    28: "Tp   (pipe)",
    29: "Fan1 (rpm)",
    30: "Fan2 (rpm)",
    31: "Current (A)",
    32: "Voltage (V)",
    34: "WaterPump",
    37: "Setpoint (°C)",
}


def capture_frame(host: str, port: int, timeout: int = 90) -> bytes | None:
    print(f"\nConnecting to {host}:{port} ...")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(10)
    s.connect((host, port))
    print("Connected. Waiting for CMD 0x01 frame (pump sends every ~30 s)...")
    s.settimeout(timeout)

    buf = bytearray()
    deadline = time.time() + timeout

    while time.time() < deadline:
        chunk = s.recv(1024)
        if not chunk:
            break
        buf.extend(chunk)

        i = 0
        while i < len(buf) - 1:
            if buf[i] == 0xAA and buf[i + 1] == 0x55:
                if len(buf) - i >= 13:
                    content_len = struct.unpack_from('<H', buf, i + 10)[0]
                    total = 13 + (content_len - 1) + 3
                    if len(buf) - i >= total:
                        frame = bytes(buf[i:i + total])
                        if frame[12] == 0x01:
                            s.close()
                            return frame
                        i += total
                    else:
                        break
                else:
                    break
            else:
                i += 1

    s.close()
    return None


def analyse(frame: bytes, target_mode: float) -> None:
    payload = frame[13:]
    print(f"\nPayload: {len(payload)} bytes")
    print(f"Searching for working mode value: {target_mode}\n")

    print(f"{'Slot':>5}  {'Offset':>7}  {'Value':>12}  Label")
    print("─" * 70)

    max_slots = (len(payload) - 2) // 4
    hits = []

    for slot in range(max_slots):
        off = 2 + slot * 4
        if off + 4 > len(payload):
            break
        v = struct.unpack_from('<f', payload, off)[0]

        is_mode_hit = abs(v - target_mode) < 0.05
        label = KNOWN_SLOTS.get(slot, "")

        # Print if: known slot, mode hit, or non-trivial value
        if label or is_mode_hit or (0.01 < abs(v) < 10000):
            arrow = "  ◄◄◄ POSSIBLE WORKING MODE SLOT!" if is_mode_hit else ""
            print(f"  [{slot:3d}]  off={off:4d}   {v:12.4f}  {label}{arrow}")
            if is_mode_hit:
                hits.append((slot, v))

    print()
    if hits:
        print(f"Slots containing {target_mode}:")
        for slot, v in hits:
            name = KNOWN_SLOTS.get(slot, "(unknown)")
            print(f"  → slot {slot}  ({name})")
        print()
        print("The correct WorkingMode index is one of the slots marked above.")
        print("If slot 19 is NOT in this list, the current guess is wrong.")
        print("Report which slot matches and the integration will be fixed.")
    else:
        print(f"No slot found containing {target_mode}.")
        print("Check that the pump is actually in the expected mode right now.")

    # Also print raw hex for manual analysis
    print("\nFull payload hex (for manual inspection):")
    for row in range(0, len(payload), 16):
        chunk = payload[row:row + 16]
        hex_part = ' '.join(f'{b:02x}' for b in chunk)
        print(f"  {row:4d}: {hex_part}")


def main():
    parser = argparse.ArgumentParser(description="Heiko heat pump mode diagnostic")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--mode", type=float, default=2.0,
                        help="Expected working mode value (default 2.0 = Heating)")
    args = parser.parse_args()

    print("=" * 70)
    print("  Heiko Heat Pump — Working Mode Diagnostic")
    print(f"  Target: {args.host}:{args.port}")
    print(f"  Expected mode value: {args.mode}")
    print("=" * 70)

    frame = capture_frame(args.host, args.port)
    if frame is None:
        print("ERROR: No frame received. Check host/port and that the pump is online.")
        return

    print(f"Frame captured ({len(frame)} bytes). Command byte: 0x{frame[12]:02X}")
    analyse(frame, args.mode)


if __name__ == "__main__":
    main()
