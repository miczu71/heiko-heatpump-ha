"""
Heiko Heat Pump — Write Command Capture Tool
=============================================
Connects to the USR-W600 bridge and captures ALL frame types including:
  CMD 0x01 — realtime data (pump → server, every 30s)
  CMD 0x02 — set parameters (pump → server, every 3min)  ← GOLD MINE
  CMD 0x05 — write command (server → pump)               ← what we want

HOW TO USE:
1. Run this script:  python3 capture_writes.py
2. Open the cloud app (myheatpump.com) in your browser
3. Change a setting (e.g. turn on/off, change mode, change DHW setpoint)
4. Watch this terminal — CMD 0x05 frames will appear with full decode
5. Note down the index and value for each control you want to implement

The CMD 0x02 frame (sent automatically every 3 min) will also decode all
setdata parameters — letting us map every controllable register.

Run:  python3 capture_writes.py [--host 192.168.0.82] [--port 8899]
"""

import socket
import struct
import time
import argparse
from datetime import datetime

HOST = "192.168.0.82"
PORT = 8899

CMD_NAMES = {
    0x01: "REALTIME DATA  (pump→server)",
    0x02: "SET PARAMS     (pump→server)",  # ← decode this carefully
    0x03: "ACK REALTIME   (server→pump)",
    0x04: "ACK SET PARAMS (server→pump)",
    0x05: "WRITE COMMAND  (server→pump)",  # ← this is what cloud sends
    0x06: "REQUEST RT     (server→pump)",
    0x07: "REQUEST SET    (server→pump)",
}

# Known realdata parameter names (index → name)
REALDATA_NAMES = {
    2: "WorkingMode", 5: "Tuo", 6: "Tui", 7: "Tup", 8: "Tw", 9: "Tc",
    10: "Tv1", 11: "Tv2", 12: "Tr", 13: "PWM", 21: "Frequency",
    22: "EEV", 23: "Pd", 24: "Ps", 25: "Ta", 26: "Td", 27: "Ts",
    28: "Tp", 29: "Fan1", 30: "Fan2", 31: "Current", 32: "Voltage",
    34: "WaterPump", 37: "Setpoint",
}

def decode_float_array(payload: bytes, prefix: int = 2) -> list:
    """Decode all floats in a payload starting at 'prefix' offset."""
    results = []
    i = prefix
    idx = 0
    while i + 4 <= len(payload):
        v = struct.unpack_from('<f', payload, i)[0]
        results.append((idx, i, v))
        idx += 1
        i += 4
    return results

def decode_write_cmd(payload: bytes) -> tuple:
    """Decode a CMD 0x05 payload: uint16_LE index + float32_LE value."""
    if len(payload) >= 6:
        idx = struct.unpack_from('<H', payload, 0)[0]
        val = struct.unpack_from('<f', payload, 2)[0]
        return idx, val
    return None, None

def print_frame(frame: bytes, direction: str = ""):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    cmd = frame[12]
    payload = frame[13:-3]  # strip CRC and end byte
    mn = frame[3:9].hex(':').upper()
    cmd_name = CMD_NAMES.get(cmd, f"UNKNOWN (0x{cmd:02X})")

    bar = "═" * 60
    arrow = "▼ PUMP→HA" if cmd in (0x01, 0x02) else "▲ HA→PUMP" if cmd in (0x03,0x04,0x05,0x06,0x07) else ""

    print(f"\n{bar}")
    print(f"  [{ts}] {arrow}")
    print(f"  CMD 0x{cmd:02X} — {cmd_name}")
    print(f"  MN: {mn}  |  Payload: {len(payload)} bytes")

    if cmd == 0x05:
        # Write command — decode the target index and value
        idx, val = decode_write_cmd(payload)
        if idx is not None:
            name = REALDATA_NAMES.get(idx, "UNKNOWN")
            print(f"\n  ┌─ WRITE COMMAND ─────────────────────────────")
            print(f"  │  Index : {idx}  ({name})")
            print(f"  │  Value : {val:.4f}")
            print(f"  └─────────────────────────────────────────────")
            print(f"\n  *** Add to PARAM_MAP write targets: idx={idx}, name='{name}', val={val:.4f} ***")
        print(f"\n  Raw payload: {payload.hex(' ')}")

    elif cmd == 0x02:
        # Setdata frame — decode ALL parameters
        print(f"\n  SET PARAMETERS (CMD 0x02) — all controllable registers:")
        print(f"  {'Idx':>4}  {'Offset':>6}  {'Value':>10}  Name")
        print(f"  {'─'*4}  {'─'*6}  {'─'*10}  {'─'*20}")
        floats = decode_float_array(payload, prefix=2)
        for idx, offset, val in floats:
            if abs(val) > 0.001 or True:  # show all including zeros
                name = REALDATA_NAMES.get(idx, "")
                marker = " ◄" if abs(val) > 0.001 else ""
                print(f"  [{idx:3d}]  off={offset:4d}  {val:10.4f}  {name}{marker}")

    elif cmd == 0x01:
        # Realtime data — show key values only
        print(f"\n  Key sensors:")
        floats = decode_float_array(payload, prefix=2)
        for idx, offset, val in floats:
            name = REALDATA_NAMES.get(idx)
            if name and abs(val) > 0.001:
                print(f"    {name:15s} = {val:.2f}")

    print(f"\n  Full hex: {frame.hex(' ')}")


def main():
    parser = argparse.ArgumentParser(description="Heiko write-command capture tool")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--all", action="store_true",
                        help="Show all frames (default: only CMD 0x02 and 0x05)")
    args = parser.parse_args()

    print("=" * 60)
    print("  Heiko Heat Pump — Write Command Capture")
    print(f"  Target: {args.host}:{args.port}")
    print("=" * 60)
    print()
    print("  Waiting for frames...")
    print("  → CMD 0x02 (set params) arrives every ~3 minutes automatically")
    print("  → CMD 0x05 (write) appears when cloud app sends a command")
    print()
    print("  HOW TO CAPTURE WRITE COMMANDS:")
    print("  1. Keep this script running")
    print("  2. Open myheatpump.com in browser")
    print("  3. Change a setting (mode, setpoint, on/off)")
    print("  4. Watch for CMD 0x05 output below")
    print()

    buf = bytearray()

    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10)
            s.connect((args.host, args.port))
            s.settimeout(120)
            print(f"  Connected to {args.host}:{args.port}")
            print()

            while True:
                try:
                    chunk = s.recv(1024)
                    if not chunk:
                        print("  Connection closed by remote.")
                        break
                    buf.extend(chunk)

                    # Extract complete frames
                    i = 0
                    while i < len(buf) - 1:
                        if buf[i] == 0xAA and buf[i+1] == 0x55:
                            if len(buf) - i >= 13:
                                content_len = struct.unpack_from('<H', buf, i+10)[0]
                                total = 13 + (content_len - 1) + 3
                                if len(buf) - i >= total:
                                    frame = bytes(buf[i:i+total])
                                    cmd = frame[12]
                                    # Filter: always show 0x02 and 0x05; show rest if --all
                                    if cmd in (0x02, 0x05) or args.all:
                                        print_frame(frame)
                                    elif cmd == 0x01:
                                        ts = datetime.now().strftime("%H:%M:%S")
                                        print(f"  [{ts}] CMD 0x01 realtime frame ({total} bytes) — use --all to decode")
                                    buf = buf[i+total:]
                                    i = 0
                                    continue
                                else:
                                    break
                            else:
                                break
                        i += 1
                    else:
                        if i > 0:
                            buf = buf[i:]

                except socket.timeout:
                    print(f"  [{datetime.now().strftime('%H:%M:%S')}] No data for 120s...")
                    continue

        except Exception as e:
            print(f"  Connection error: {e}. Retrying in 5s...")
            time.sleep(5)
            buf.clear()


if __name__ == "__main__":
    main()
