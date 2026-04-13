"""
Async TCP client for the USR-W600 WiFi-to-RS-485 bridge.

The USR-W600 acts as a TCP server on 192.168.0.82:8899.
Any client connecting to it gets a transparent byte pipe to the RS-485 bus.
The heat pump sends CMD 0x01 frames approximately every 30 seconds unprompted;
we can also poll by sending CMD 0x06.

Reconnection uses truncated exponential backoff (1 s → 2 s → 4 s → … → 60 s).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from .protocol import FrameBuffer, HeatPumpFrame, parse_frame

_LOGGER = logging.getLogger(__name__)

# Reconnect backoff parameters
_BACKOFF_INITIAL = 1.0    # seconds
_BACKOFF_FACTOR  = 2.0
_BACKOFF_MAX     = 60.0   # cap at 1 minute


class HeikoTCPClient:
    """
    Async TCP client that connects to the USR-W600 bridge, receives frames,
    and exposes a send() method for writing frames back.

    Usage:
        client = HeikoTCPClient("192.168.0.82", 8899, on_frame_callback)
        await client.start()
        ...
        await client.stop()
    """

    def __init__(
        self,
        host: str,
        port: int,
        on_frame: Callable[[HeatPumpFrame], Coroutine[Any, Any, None]],
    ) -> None:
        self._host      = host
        self._port      = port
        self._on_frame  = on_frame
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task | None = None
        self._stopping  = False
        self._connected = False
        self._buffer    = FrameBuffer()

    @property
    def connected(self) -> bool:
        return self._connected

    async def start(self) -> None:
        """Start the background connection loop."""
        self._stopping = False
        self._task = asyncio.create_task(self._connection_loop())

    async def stop(self) -> None:
        """Gracefully stop the client."""
        self._stopping = True
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def send(self, frame_bytes: bytes) -> bool:
        """
        Send raw frame bytes to the heat pump.
        Returns True on success, False if not connected.
        """
        if not self._connected or self._writer is None:
            _LOGGER.warning("Cannot send: not connected to %s:%d", self._host, self._port)
            return False
        try:
            self._writer.write(frame_bytes)
            await self._writer.drain()
            return True
        except Exception as exc:
            _LOGGER.error("Send failed: %s", exc)
            self._connected = False
            return False

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _connection_loop(self) -> None:
        """
        Outer loop: attempts to connect, runs receive loop, reconnects on failure.
        Uses truncated exponential backoff.
        """
        backoff = _BACKOFF_INITIAL

        while not self._stopping:
            try:
                _LOGGER.info("Connecting to %s:%d …", self._host, self._port)
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self._host, self._port),
                    timeout=10.0,
                )
                self._writer    = writer
                self._connected = True
                self._buffer    = FrameBuffer()  # reset buffer on new connection
                backoff         = _BACKOFF_INITIAL  # reset backoff on successful connect
                _LOGGER.info("Connected to %s:%d", self._host, self._port)

                await self._receive_loop(reader)

            except asyncio.CancelledError:
                break
            except (OSError, asyncio.TimeoutError) as exc:
                _LOGGER.warning(
                    "Connection to %s:%d failed: %s. Retrying in %.0f s …",
                    self._host, self._port, exc, backoff,
                )
            except Exception as exc:
                _LOGGER.exception("Unexpected error in connection loop: %s", exc)
            finally:
                self._connected = False
                if self._writer:
                    try:
                        self._writer.close()
                    except Exception:
                        pass
                    self._writer = None

            if not self._stopping:
                await asyncio.sleep(backoff)
                backoff = min(backoff * _BACKOFF_FACTOR, _BACKOFF_MAX)

    async def _receive_loop(self, reader: asyncio.StreamReader) -> None:
        """
        Inner loop: reads bytes from the TCP stream, extracts complete frames,
        and dispatches them to the on_frame callback.
        """
        while not self._stopping:
            try:
                # Read in 512-byte chunks; the bridge may deliver partial frames
                data = await asyncio.wait_for(reader.read(512), timeout=90.0)
            except asyncio.TimeoutError:
                # No data for 90 s — heat pump sends every 30 s so this is abnormal
                _LOGGER.warning("No data received for 90 s, reconnecting …")
                return  # triggers reconnect in outer loop
            except Exception as exc:
                _LOGGER.warning("Read error: %s", exc)
                return

            if not data:
                _LOGGER.info("TCP connection closed by remote end.")
                return

            # Feed bytes into the framing buffer and get complete frames
            raw_frames = self._buffer.feed(data)

            for raw in raw_frames:
                frame = parse_frame(raw)
                if frame is not None:
                    try:
                        await self._on_frame(frame)
                    except Exception as exc:
                        _LOGGER.exception("Error in frame callback: %s", exc)
                else:
                    _LOGGER.debug("Discarded malformed frame (%d bytes)", len(raw))
