#!/usr/bin/env python3
"""
Transparent MITM proxy for the Heiko / Neoheat heat pump cloud link.

The USR-W600's SocketB outbound-connects to `www.myheatpump.com:18899`
in plain TCP. If we redirect that connection to this proxy, we can see
every byte the cloud sends down — including CMD 0x05 (WRITE) frames
that are currently invisible on our local SocketA tap.

How to redirect the W600:
  Option A (simplest) — log into the W600 config at http://192.168.0.82,
    go to Trans Setting → SocketB Connect Setting, and change
    "Server IP Address" from www.myheatpump.com to the IP of the host
    running this proxy (e.g. your HA host). Save + reboot the W600.

  Option B — add a DNS override so that www.myheatpump.com resolves
    to the proxy host only for the W600 (AdGuard/Pi-hole/router static).

Once the W600 connects inbound, the proxy opens a matching outbound
connection to the real cloud (resolved via `--upstream`) and copies
bytes both ways, logging each framed message with direction + decode.

Usage:
  python3 /config/tools/mitm_heatpump.py --listen 0.0.0.0:18899

Then change DHW setpoint (or anything) on the myheatpump.com website.
Any line tagged `[CLOUD→PUMP] CMD 0x05` is the frame format we need.
"""

from __future__ import annotations

import argparse
import asyncio
import struct
import sys
from datetime import datetime
from pathlib import Path

# Reuse component's protocol parser so decode stays aligned
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "heiko_heatpump"))
from protocol import (  # noqa: E402
    FrameBuffer, parse_frame, crc16_modbus, PARAM_MAP,
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

IDX_NAME: dict[int, str] = {idx: name for name, (idx, _u, _d) in PARAM_MAP.items()}


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def decode_write_payload(payload: bytes) -> list[str]:
    """Three plausible CMD 0x05 layouts — print all for disambiguation."""
    lines = [f"raw payload = {payload.hex(' ')}  ({len(payload)} B)"]
    if len(payload) >= 6:
        idx16 = struct.unpack_from("<H", payload, 0)[0]
        val = struct.unpack_from("<f", payload, 2)[0]
        lines.append(f"  [u16 idx][f32] → idx={idx16} ({IDX_NAME.get(idx16, '?')}) value={val:g}")
    if len(payload) >= 5:
        idx8 = payload[0]
        val = struct.unpack_from("<f", payload, 1)[0]
        lines.append(f"  [u8  idx][f32] → idx={idx8} ({IDX_NAME.get(idx8, '?')}) value={val:g}")
    if len(payload) >= 8:
        idx16 = struct.unpack_from("<H", payload, 2)[0]
        val = struct.unpack_from("<f", payload, 4)[0]
        lines.append(f"  [0000][u16 idx][f32] → idx={idx16} ({IDX_NAME.get(idx16, '?')}) value={val:g}")
    return lines


def crc_analysis(raw: bytes) -> str:
    if len(raw) < 16:
        return "frame too short for CRC analysis"
    payload_end = len(raw) - 3
    recv = struct.unpack_from("<H", raw, payload_end)[0]
    plain = crc16_modbus(raw[:payload_end]) & 0xFFFF
    offset = (recv ^ plain) & 0xFFFF
    if offset == 0x0000:
        return f"CRC = plain CRC-16/Modbus (recv=0x{recv:04X})"
    if offset == 0x0903:
        return f"CRC = plain ^ 0x0903 pump offset (recv=0x{recv:04X})"
    return f"CRC offset = 0x{offset:04X} (recv=0x{recv:04X}, plain=0x{plain:04X})"


class Logger:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("a", buffering=1)

    def write(self, msg: str) -> None:
        line = f"[{ts()}] {msg}"
        print(line)
        self._fh.write(line + "\n")

    def close(self) -> None:
        self._fh.close()


def log_frame(direction: str, raw: bytes, log: Logger) -> None:
    frame = parse_frame(raw)
    arrow = "[PUMP→CLOUD]" if direction == "up" else "[CLOUD→PUMP]"

    if frame is None:
        log.write(f"{arrow} ??? malformed {len(raw)} B: {raw.hex(' ')[:200]}")
        return

    cmd_name = CMD_NAMES.get(frame.command, f"CMD 0x{frame.command:02X} UNKNOWN")
    header = (
        f"{arrow} {cmd_name} target=0x{frame.target:02X} "
        f"MN={frame.mn.hex(':')} dev=0x{frame.device_id:02X} "
        f"payload={len(frame.payload)} B crc_ok={frame.crc_ok}"
    )
    log.write(header)

    if frame.command == CMD_WRITE:
        # The prize — dump everything we know
        log.write("  ★★★★★ WRITE FRAME CAPTURED ★★★★★")
        log.write(f"  full raw: {raw.hex(' ')}")
        log.write(f"  {crc_analysis(raw)}")
        for line in decode_write_payload(frame.payload):
            log.write(f"  {line}")

    elif frame.command in (CMD_ACK_RT, CMD_ACK_SET, CMD_REQ_RT, CMD_REQ_SET):
        # Short frames — show raw so we can see what the cloud is emitting
        log.write(f"  raw: {raw.hex(' ')}")

    # CMD 0x01/0x02: too noisy to dump, skip the raw


async def pump_bytes(
    src: asyncio.StreamReader,
    dst: asyncio.StreamWriter,
    direction: str,
    log: Logger,
) -> None:
    """Copy bytes from src → dst, framing and logging along the way."""
    buf = FrameBuffer()
    arrow = "[CLOUD→PUMP]" if direction == "down" else "[PUMP→CLOUD]"
    try:
        while True:
            data = await src.read(4096)
            if not data:
                return
            # Forward to the other side immediately (preserve latency)
            dst.write(data)
            try:
                await dst.drain()
            except ConnectionError:
                return
            # Log the raw chunk so we see even unframed / keep-alive bytes
            hex_preview = data.hex(" ")
            if len(hex_preview) > 400:
                hex_preview = hex_preview[:400] + f"… ({len(data)} B total)"
            log.write(f"{arrow} RAW {len(data)} B: {hex_preview}")
            # Parse for framed logging
            for raw in buf.feed(data):
                log_frame(direction, raw, log)
    except (ConnectionResetError, BrokenPipeError):
        return
    except asyncio.CancelledError:
        raise


async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    upstream_host: str,
    upstream_port: int,
    log: Logger,
) -> None:
    peer = writer.get_extra_info("peername")
    log.write("=" * 78)
    log.write(f"NEW CLIENT from {peer} → forwarding to {upstream_host}:{upstream_port}")

    try:
        up_reader, up_writer = await asyncio.open_connection(upstream_host, upstream_port)
    except OSError as exc:
        log.write(f"Upstream connect failed: {exc}")
        writer.close()
        return

    log.write(f"Upstream connection established to {upstream_host}:{upstream_port}")
    log.write("=" * 78)

    # Two concurrent pumps: client→upstream (pump→cloud) and upstream→client (cloud→pump)
    t_up   = asyncio.create_task(pump_bytes(reader, up_writer, "up", log))
    t_down = asyncio.create_task(pump_bytes(up_reader, writer, "down", log))
    try:
        await asyncio.wait({t_up, t_down}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in (t_up, t_down):
            if not t.done():
                t.cancel()
        for w in (writer, up_writer):
            try:
                w.close()
            except Exception:
                pass
        log.write(f"Session closed: {peer}")


async def main_async(args: argparse.Namespace) -> None:
    log = Logger(Path(args.logfile))
    log.write(f"MITM proxy starting: listen {args.listen} → upstream {args.upstream}")
    log.write("On the W600 web UI → Trans Setting → SocketB → set Server IP Address")
    log.write("to this host's IP. Save + reboot. Then change a setting on myheatpump.com.")

    listen_host, listen_port = args.listen.split(":")
    up_host, up_port_str = args.upstream.split(":")

    server = await asyncio.start_server(
        lambda r, w: handle_client(r, w, up_host, int(up_port_str), log),
        listen_host,
        int(listen_port),
    )
    async with server:
        await server.serve_forever()


def main() -> int:
    ap = argparse.ArgumentParser(description="Heat-pump cloud MITM proxy")
    ap.add_argument("--listen", default="0.0.0.0:18899",
                    help="host:port to listen on (default: 0.0.0.0:18899)")
    ap.add_argument("--upstream", default="www.myheatpump.com:18899",
                    help="real cloud host:port (default: www.myheatpump.com:18899)")
    ap.add_argument("--logfile", default="/config/tools/mitm.log",
                    help="append-only log file")
    args = ap.parse_args()

    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nInterrupted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
