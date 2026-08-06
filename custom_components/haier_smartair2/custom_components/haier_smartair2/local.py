"""Local transport: direct TCP 56800 for plaintext-dongle devices (e.g. maks).

Wraps smartair2 frames in the 80-byte uSDK LAN envelope (marker 0x2714 out /
0x2715 in, MAC as ASCII at [40:52], seq at [75], payload length at [79]).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from homeassistant.core import HomeAssistant

from .const import LOCAL_PORT

_LOGGER = logging.getLogger(__name__)

MARKER_TX = 0x2714
MARKER_RX = 0x2715


def _normalise_mac(mac: str) -> str:
    cleaned = "".join(c for c in mac if c.isalnum()).upper()
    if len(cleaned) != 12:
        raise ValueError(f"MAC must have 12 hex chars: {mac!r}")
    return cleaned


def _envelope(payload: bytes, mac: str, seq: int) -> bytes:
    env = bytearray(80)
    env[2:4] = MARKER_TX.to_bytes(2, "big")
    env[40:52] = mac.encode("ascii")
    env[75] = seq & 0xFF
    env[79] = len(payload)
    return bytes(env) + payload


class HaierLocalClient:
    """Persistent TCP connection to one local device."""

    def __init__(self, hass: HomeAssistant, ip: str, mac: str) -> None:
        self._hass = hass
        self._ip = ip
        self._mac = _normalise_mac(mac)
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._seq = 0
        self._frame: bytes | None = None
        self._listeners: list[Callable[[], None]] = []
        self._stopped = False
        self._lock = asyncio.Lock()

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)

        def remove() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return remove

    def latest_frame(self, _devid: str | None = None) -> bytes | None:
        return self._frame

    def is_online(self, _devid: str | None = None) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    def _notify(self) -> None:
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("listener failed")

    @property
    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) % 256
        return self._seq

    async def async_start(self) -> None:
        await self._connect()

    async def _connect(self) -> None:
        async with self._lock:
            if self.is_online():
                return
            self._reader, self._writer = await asyncio.open_connection(self._ip, LOCAL_PORT)
            self._read_task = self._hass.async_create_task(self._read_loop())
            if self._keepalive_task is None or self._keepalive_task.done():
                self._keepalive_task = self._hass.async_create_task(self._keepalive_loop())

    async def _keepalive_loop(self) -> None:
        """Poll periodically so the dongle keeps the link open and data stays fresh."""
        try:
            while not self._stopped:
                await asyncio.sleep(12)
                try:
                    await self.async_poll("")
                except Exception:  # noqa: BLE001
                    # a failed write means the socket died; reader loop will reconnect
                    if self._writer:
                        self._writer.close()
                    break
        except asyncio.CancelledError:
            raise

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while not self._stopped:
                header = await self._reader.readexactly(80)
                plen = header[79]
                payload = await self._reader.readexactly(plen) if plen else b""
                if int.from_bytes(header[2:4], "big") != MARKER_RX:
                    continue
                if len(payload) >= 12 and payload[9] in (0x02, 0x06):
                    self._frame = payload
                    self._notify()
        except (asyncio.IncompleteReadError, ConnectionError, OSError) as err:
            if not self._stopped:
                _LOGGER.info("Haier local %s lost: %s", self._ip, err)
        except asyncio.CancelledError:
            raise
        finally:
            if not self._stopped:
                self._hass.loop.call_later(
                    3, lambda: self._hass.async_create_task(self._reconnect())
                )

    async def _reconnect(self) -> None:
        if self._stopped or self.is_online():
            return
        try:
            await self._connect()
            await self.async_poll("")
        except Exception:  # noqa: BLE001
            self._hass.loop.call_later(
                5, lambda: self._hass.async_create_task(self._reconnect())
            )

    async def _write(self, payload: bytes) -> None:
        if not self.is_online():
            await self._connect()
        assert self._writer is not None
        self._writer.write(_envelope(payload, self._mac, self._next_seq))
        await self._writer.drain()

    async def async_poll(self, _devid: str | None = None) -> None:
        from .codec import POLL_FRAME

        await self._write(POLL_FRAME)

    async def async_send_frame(self, _devid: str, frame: bytes) -> None:
        await self._write(frame)

    async def async_stop(self) -> None:
        self._stopped = True
        if self._read_task:
            self._read_task.cancel()
        if self._keepalive_task:
            self._keepalive_task.cancel()
        if self._writer:
            self._writer.close()
