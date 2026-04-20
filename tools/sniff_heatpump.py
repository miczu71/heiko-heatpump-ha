#!/usr/bin/env python3
"""
Passive sniffer for the Heiko heat pump.

Connects to the USR-W600 TCP bridge alongside the running HA integration
and logs every frame it sees. Special focus on CMD 0x05 (write) frames —
if the cloud or the physical panel pushes any writes to the bus, we see
the exact bytes the pump accepts, including payload layout and CRC form.

Run while you:
  (a) open the myheatpump.com app and change a setting, OR
  (b) press a button on the pump's physical control panel.

Any CMD 0x05 captured is the answer — copy its bytes and we can replay.
"""

from __future__ import annotations

import argparse
import socket
import struct
import sys
import time
from datetime import datetime
from pathlib import Path

# Reuse the component's protocol module so we stay aligned with the integration
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "heiko_heatpump"))
from protocol import (  # noqa: E402
    FrameBuffer,
    parse_frame,
    crc16_modbus,
    PARAM_MAP,
    CMD_REALTIME, CMD_SETPARAMS, CMD_ACK_RT, CMD_ACK_SET,
    CMD_WRITE, CMD_REQ_RT, CMD_REQ_SET,
)

CMD_NAMES = {
    CMD_REALTIME:  "CMD 0x01 RT-DATA ",
    CMD_SETPARAMS: "CMD 0x02 SETDATA ",
    CMD_ACK_RT:    "CMD 0x03 ACK-RT  ",
    CMD_ACK_SET:   "CMD 0x04 ACK-SET ",
    CMD_WRITE:     "CMD 0x05 WRITE   ",
    CMD_REQ_RT:    "CMD 0x06 REQ-RT  ",
    CMD_REQ_SET:   "CMD 0x07 REQ-SET ",
}

# Reverse lookup index → friendly name from PARAM_MAP (for live-change reports)
IDX_NAME: dict[int, str] = {idx: name for name, (idx, _u, _d) in PARAM_MAP.items()}


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def hexdump(b: bytes, limit: int = 64) -> str:
    h = b.hex(" ")
    if len(b) > limit:
        return h[: limit * 3] + f"… ({len(b)} B total)"
    return h


def decode_write_payload(payload: bytes) -> str:
    """Best-effort decode of a CMD 0x05 payload.

    The most likely layouts are:
      - LE uint16 index + LE float32 value  (6 bytes)
      - LE uint8  index + LE float32 value  (5 bytes)
      - 00 00 prefix + LE uint16 index + float32   (8 bytes, mirrors CMD 0x01)
    We print all plausible interpretations so you can recognise the real one.
    """
    lines = [f"raw payload = {payload.hex(' ')}  ({len(payload)} B)"]
    if len(payload) >= 6:
        idx16 = struct.unpack_from("<H", payload, 0)[0]
        val = struct.unpack_from("<f", payload, 2)[0]
        name = IDX_NAME.get(idx16, "?")
        lines.append(f"  as [u16 idx][f32 val] → idx={idx16} ({name}) value={val:g}")
    if len(payload) >= 5:
        idx8 = payload[0]
        val = struct.unpack_from("<f", payload, 1)[0]
        name = IDX_NAME.get(idx8, "?")
        lines.append(f"  as [u8  idx][f32 val] → idx={idx8} ({name}) value={val:g}")
    if len(payload) >= 8:
        idx16 = struct.unpack_from("<H", payload, 2)[0]
        val = struct.unpack_from("<f", payload, 4)[0]
        name = IDX_NAME.get(idx16, "?")
        lines.append(f"  as [0000][u16 idx][f32 val] → idx={idx16} ({name}) value={val:g}")
    return "\n    ".join(lines)


def decode_setdata_floats(payload: bytes) -> dict[int, float]:
    """Return {index: value} for the named PARAM_MAP indices present in a payload."""
    out: dict[int, float] = {}
    for name, (idx, _u, _d) in PARAM_MAP.items():
        off = 2 + idx * 4
        if off + 4 <= len(payload):
            v = struct.unpack_from("<f", payload, off)[0]
            if -1e6 < v < 1e6:
                out[idx] = v
    return out


def crc_analysis(raw: bytes) -> str:
    """For CMD 0x05 frames, report whether the CRC uses the +0x0903 pump offset
    or plain CRC-16/Modbus. This settles whether the cloud sends the same CRC
    form we do."""
    if len(raw) < 16:
        return "frame too short"
    payload_end = len(raw) - 3  # last 3 = CRC(2) + end(1)
    recv = struct.unpack_from("<H", raw, payload_end)[0]
    plain = crc16_modbus(raw[:payload_end]) & 0xFFFF
    offset = (recv ^ plain) & 0xFFFF
    if offset == 0x0903:
        return f"CRC ok with pump offset (recv=0x{recv:04X}, plain=0x{plain:04X}, xor=0x0903)"
    if offset == 0x0000:
        return f"CRC ok as plain CRC-16/Modbus (recv=0x{recv:04X})"
    return f"CRC mismatch: recv=0x{recv:04X}, plain=0x{plain:04X}, xor=0x{offset:04X}"


def handle_raw_frame(raw: bytes, last_setdata: dict[int, float], writer) -> None:
    frame = parse_frame(raw)
    if frame is None:
        writer(f"[{ts()}] ??? malformed  {hexdump(raw)}")
        return

    cmd_name = CMD_NAMES.get(frame.command, f"CMD 0x{frame.command:02X} UNKNOWN")
    header = (
        f"[{ts()}] {cmd_name} "
        f"target=0x{frame.target:02X} MN={frame.mn.hex(':')} "
        f"dev=0x{frame.device_id:02X} len={len(frame.payload)} "
        f"crc_ok={frame.crc_ok}"
    )
    writer(header)

    if frame.command == CMD_WRITE:
        # The prize. Dump absolutely everything about this frame.
        writer("  ★★★ WRITE FRAME CAPTURED ★★★")
        writer(f"  full raw: {raw.hex(' ')}")
        writer(f"  {crc_analysis(raw)}")
        writer(f"  payload decode:")
        writer("    " + decode_write_payload(frame.payload))

    elif frame.command == CMD_SETPARAMS:
        # Diff against last snapshot — any change tells us someone wrote something
        current = decode_setdata_floats(frame.payload)
        if last_setdata:
            changes = [
                (idx, last_setdata[idx], current[idx])
                for idx in current
                if idx in last_setdata and abs(current[idx] - last_setdata[idx]) > 1e-3
            ]
            if changes:
                writer("  SETDATA changes:")
                for idx, old, new in changes:
                    name = IDX_NAME.get(idx, "?")
                    writer(f"    idx {idx:3d} ({name}): {old:g} → {new:g}")
        last_setdata.clear()
        last_setdata.update(current)

    elif frame.command == CMD_REALTIME:
        # Keep the log readable — just a one-line summary
        floats = decode_setdata_floats(frame.payload)
        mode = floats.get(2)
        freq = floats.get(21)
        tw = floats.get(8)
        writer(
            f"  RT summary: mode={mode} freq={freq} Tw={tw}"
            if mode is not None else f"  RT payload {len(frame.payload)} B"
        )

    elif frame.command in (CMD_ACK_RT, CMD_ACK_SET, CMD_REQ_RT, CMD_REQ_SET):
        # Short frames — show the raw bytes to distinguish client→pump vs pump→client
        writer(f"  raw: {raw.hex(' ')}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Passive heat pump frame sniffer")
    ap.add_argument("--host", default="192.168.0.82")
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--logfile", default="/config/tools/sniff.log",
                    help="Also append output to this file")
    ap.add_argument("--duration", type=int, default=0,
                    help="Stop after N seconds (0 = run until Ctrl-C)")
    args = ap.parse_args()

    log_path = Path(args.logfile)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_f = log_path.open("a", buffering=1)

    def writer(msg: str) -> None:
        print(msg)
        log_f.write(msg + "\n")

    writer("=" * 78)
    writer(f"[{ts()}] Sniffer starting → {args.host}:{args.port}")
    writer("Now: open the myheatpump.com app OR press buttons on the pump panel.")
    writer("Any CMD 0x05 captured is the frame format we need. Ctrl-C to stop.")
    writer("=" * 78)

    sock = socket.create_connection((args.host, args.port), timeout=10)
    sock.settimeout(5.0)
    buf = FrameBuffer()
    last_setdata: dict[int, float] = {}
    started = time.time()

    try:
        while True:
            if args.duration and (time.time() - started) >= args.duration:
                writer(f"[{ts()}] Duration reached, exiting.")
                break
            try:
                data = sock.recv(1024)
            except socket.timeout:
                continue
            if not data:
                writer(f"[{ts()}] TCP connection closed by remote.")
                break
            for raw in buf.feed(data):
                handle_raw_frame(raw, last_setdata, writer)
    except KeyboardInterrupt:
        writer(f"[{ts()}] Interrupted by user.")
    finally:
        sock.close()
        log_f.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
