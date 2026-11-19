"""Minimal asyncio client for Samsung's sdb protocol (ADB-compatible, TCP 26101).

The TV only accepts connections from the "Host PC IP" configured in its Developer Mode.
"""

from __future__ import annotations

import asyncio
import logging
import re
import struct
import time
from collections.abc import Callable
from typing import Self

from ..base import DeviceConnectError, DeviceError

_LOGGER = logging.getLogger(__name__)

SDB_PORT = 26101


def _cmd(s: str) -> int:
    return int.from_bytes(s.encode(), "little")


A_CNXN, A_OPEN, A_OKAY, A_CLSE, A_WRTE, A_AUTH = (_cmd(c) for c in ("CNXN", "OPEN", "OKAY", "CLSE", "WRTE", "AUTH"))
_HEADER = struct.Struct("<6I")
_MAX_PAYLOAD = 4096


class SdbError(DeviceError):
    """Transport-level sdb failure."""


class SdbConnectError(SdbError, DeviceConnectError):
    """TV is unreachable or refused the connection."""


class SdbStream:
    """One logical sdb stream (shell, sync, ...)."""

    def __init__(self, conn: SdbConnection, local_id: int) -> None:
        self.conn = conn
        self.local_id = local_id
        self.remote_id = 0
        self.opened: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self.acks: asyncio.Queue[None] = asyncio.Queue()
        self.data: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.closed = False
        self._buf = b""

    async def write(self, payload: bytes) -> None:
        maxd = self.conn.max_payload
        for off in range(0, len(payload), maxd):
            if self.closed:
                raise SdbError("TV closed the stream while writing")
            await self.conn.send(A_WRTE, self.local_id, self.remote_id, payload[off : off + maxd])
            await asyncio.wait_for(self.acks.get(), timeout=30)

    async def read_exact(self, n: int, timeout: float = 60) -> bytes:
        while len(self._buf) < n:
            chunk = await asyncio.wait_for(self.data.get(), timeout=timeout)
            if chunk is None:
                raise SdbError("Stream closed before the reply was complete")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            try:
                await self.conn.send(A_CLSE, self.local_id, self.remote_id)
            except (OSError, SdbError):
                pass


class SdbConnection:
    """A single TCP connection to a TV's sdbd."""

    def __init__(self, host: str, port: int = SDB_PORT) -> None:
        self.host = host
        self.port = port
        self.max_payload = _MAX_PAYLOAD
        self.banner = ""
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._streams: dict[int, SdbStream] = {}
        self._next_id = 1
        self._reader_task: asyncio.Task | None = None
        self._connected: asyncio.Future[bool] | None = None
        self._wlock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def connect(self, timeout: float = 8) -> None:
        try:
            self._reader, self._writer = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), timeout)
        except (OSError, TimeoutError) as err:
            raise SdbConnectError(f"Cannot connect to {self.host}:{self.port}: {err}") from err
        self._connected = asyncio.get_running_loop().create_future()
        self._reader_task = asyncio.get_running_loop().create_task(self._read_loop())
        await self.send(A_CNXN, 0x01000000, _MAX_PAYLOAD, b"host::")
        try:
            await asyncio.wait_for(self._connected, timeout)
        except TimeoutError as err:
            await self.close()
            raise SdbConnectError("TV did not answer the sdb handshake") from err
        except SdbError as err:
            await self.close()
            raise SdbConnectError(
                f"{err} - check that the TV's Developer Mode Host PC IP is this Home Assistant's IP"
            ) from err

    async def close(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except OSError:
                pass
            self._writer = None

    async def send(self, cmd: int, arg0: int, arg1: int, data: bytes = b"") -> None:
        if self._writer is None:
            raise SdbError("Not connected")
        hdr = _HEADER.pack(cmd, arg0, arg1, len(data), sum(data) & 0xFFFFFFFF, cmd ^ 0xFFFFFFFF)
        async with self._wlock:
            self._writer.write(hdr + data)
            await self._writer.drain()

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while True:
                hdr = await self._reader.readexactly(_HEADER.size)
                cmd, arg0, arg1, length, _chk, _magic = _HEADER.unpack(hdr)
                data = await self._reader.readexactly(length) if length else b""
                await self._dispatch(cmd, arg0, arg1, data)
        except asyncio.CancelledError:
            return
        except (asyncio.IncompleteReadError, OSError, SdbError) as err:
            exc = SdbError(f"Connection to TV closed ({type(err).__name__})")
            if self._connected and not self._connected.done():
                self._connected.set_exception(exc)
            for stream in self._streams.values():
                if not stream.opened.done():
                    stream.opened.set_exception(exc)
                stream.closed = True
                stream.data.put_nowait(None)
                stream.acks.put_nowait(None)

    async def _dispatch(self, cmd: int, arg0: int, arg1: int, data: bytes) -> None:
        if cmd == A_CNXN:
            self.max_payload = min(arg1 or _MAX_PAYLOAD, _MAX_PAYLOAD)
            self.banner = data.decode(errors="replace").strip("\x00")
            if self._connected and not self._connected.done():
                self._connected.set_result(True)
            return
        if cmd == A_AUTH:
            if self._connected and not self._connected.done():
                self._connected.set_exception(SdbError("TV requested AUTH, which is not supported"))
            return
        stream = self._streams.get(arg1)
        if stream is None:
            return
        if cmd == A_OKAY:
            if not stream.opened.done():
                stream.remote_id = arg0
                stream.opened.set_result(True)
            else:
                stream.acks.put_nowait(None)
        elif cmd == A_WRTE:
            stream.data.put_nowait(data)
            await self.send(A_OKAY, stream.local_id, stream.remote_id)
        elif cmd == A_CLSE:
            if not stream.opened.done():
                stream.opened.set_exception(SdbError("TV refused the service"))
            stream.closed = True
            stream.data.put_nowait(None)
            stream.acks.put_nowait(None)

    async def open(self, service: str, timeout: float = 10) -> SdbStream:
        sid = self._next_id
        self._next_id += 1
        stream = SdbStream(self, sid)
        self._streams[sid] = stream
        await self.send(A_OPEN, sid, 0, service.encode() + b"\x00")
        await asyncio.wait_for(stream.opened, timeout)
        return stream

    async def shell(
        self,
        command: str,
        timeout: float = 30,
        done_rx: re.Pattern[str] | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> str:
        """Run a command in the TV's restricted shell and return its output."""
        stream = await self.open(f"shell:{command}")
        out = ""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise SdbError(f"Timeout running '{command}'")
                chunk = await asyncio.wait_for(stream.data.get(), remaining)
                if chunk is None:
                    break
                text = chunk.decode(errors="replace")
                out += text
                if on_output:
                    on_output(text)
                if done_rx and done_rx.search(out):
                    # the TV often sends the rest of the line a moment later
                    try:
                        while (chunk := await asyncio.wait_for(stream.data.get(), 1.5)) is not None:
                            text = chunk.decode(errors="replace")
                            out += text
                            if on_output:
                                on_output(text)
                    except TimeoutError:
                        pass
                    break
        finally:
            await stream.close()
        return out

    async def capability(self) -> dict[str, str]:
        try:
            stream = await self.open("capability:")
        except (SdbError, TimeoutError):
            return {}
        raw = b""
        try:
            while True:
                chunk = await asyncio.wait_for(stream.data.get(), 5)
                if chunk is None:
                    break
                raw += chunk
        except TimeoutError:
            pass
        finally:
            await stream.close()
        caps: dict[str, str] = {}
        for line in raw.decode(errors="replace").splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                caps[key.strip()] = value.strip()
        return caps

    async def push(
        self,
        data: bytes,
        remote_path: str,
        mode: int = 0o100755,
        progress: Callable[[int, int], None] | None = None,
    ) -> None:
        """Upload a file with the sync protocol."""
        stream = await self.open("sync:")
        try:
            spec = f"{remote_path},{mode}".encode()
            await stream.write(b"SEND" + struct.pack("<I", len(spec)) + spec)
            chunk_max = self.max_payload - 8
            total, sent = len(data), 0
            for off in range(0, total, chunk_max):
                chunk = data[off : off + chunk_max]
                await stream.write(b"DATA" + struct.pack("<I", len(chunk)) + chunk)
                sent += len(chunk)
                if progress:
                    progress(sent, total)
            await stream.write(b"DONE" + struct.pack("<I", int(time.time())))
            resp = await stream.read_exact(8)
            if resp[:4] == b"FAIL":
                msg = await stream.read_exact(struct.unpack("<I", resp[4:])[0])
                raise SdbError(f"Upload failed: {msg.decode(errors='replace')}")
            if resp[:4] != b"OKAY":
                raise SdbError(f"Unexpected upload reply {resp!r}")
            await stream.write(b"QUIT" + b"\x00" * 4)
        finally:
            await stream.close()
