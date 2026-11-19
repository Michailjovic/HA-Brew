"""LG webOS TV in Developer Mode (no root), reached over the Developer Mode SSH server.

Developer Mode app → Dev Mode ON → Key Server ON publishes the private key on
``http://TV:9991/webos_rsa`` (encrypted with the 6-character passphrase shown on screen).
SSH runs on port 9922 as user ``prisoner``: no PTY, only ``exec`` of commands such as
``luna-send-pub``. ``luna-send-pub`` must get ``</dev/null`` (or an open stdin), otherwise it
exits before the reply arrives.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import asyncssh

from ..base import (
    DeviceAuthError,
    DeviceConnectError,
    DeviceError,
    InstallError,
    LaunchError,
    check_id,
)

_LOGGER = logging.getLogger(__name__)

SSH_PORT = 9922
KEY_PORT = 9991
SSH_USER = "prisoner"
REMOTE_TMP = "/media/developer/temp"
TOKEN_FILE = "/var/luna/preferences/devmode_enabled"
DEVMODE_APP = "com.palmdts.devmode"

_CONNECT_TIMEOUT = 8
_UPLOAD_CHUNK = 64 * 1024
# appInstallService states → share of the install phase (0-100)
_STATE_PROGRESS = {
    "ipk verifying": 10,
    "ipk parsing": 25,
    "app closing": 40,
    "installing": 60,
    "installed": 100,
}


@dataclass(frozen=True)
class WebosDeviceInfo:
    """Identity of a TV (getSystemInfo)."""

    serial: str
    model: str
    sdk_version: str
    firmware: str


@dataclass(frozen=True)
class WebosApp:
    """An app installed through Developer Mode (dev/listApps)."""

    app_id: str
    package_id: str
    title: str
    version: str

    @property
    def origin(self) -> str:
        # Without root only Developer Mode apps are visible; all of them are sideloaded.
        return "sideload"


def load_key(pem: str, passphrase: str) -> asyncssh.SSHKey:
    """Decrypt the Developer Mode key (raises DeviceAuthError on a wrong passphrase)."""
    try:
        return asyncssh.import_private_key(pem, passphrase.strip() or None)
    except (asyncssh.KeyImportError, ValueError) as err:
        raise DeviceAuthError(f"Cannot decrypt the Developer Mode key: {err}") from err


async def fetch_key(host: str, port: int = KEY_PORT, timeout: float = _CONNECT_TIMEOUT) -> str:
    """Download ``webos_rsa`` from the TV's Key Server (plain HTTP, LAN only)."""
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, TimeoutError) as err:
        raise DeviceConnectError(f"Key Server on {host}:{port} is not reachable: {err}") from err
    try:
        writer.write(f"GET /webos_rsa HTTP/1.0\r\nHost: {host}\r\n\r\n".encode())
        await writer.drain()
        raw = await asyncio.wait_for(reader.read(), timeout)  # HTTP/1.0: the TV closes after the body
    except (OSError, TimeoutError) as err:
        raise DeviceConnectError(f"Key Server did not answer: {err}") from err
    finally:
        writer.close()
    head, _, body = raw.partition(b"\r\n\r\n")
    if b" 200 " not in head.split(b"\r\n", 1)[0] or b"PRIVATE KEY" not in body:
        raise DeviceConnectError("Key Server did not return a key")
    return body.decode("ascii", "replace").strip() + "\n"


def _luna_command(uri: str, params: dict[str, Any], interactive: bool = False) -> str:
    mode = "-i" if interactive else "-n 1"
    return f"luna-send-pub {mode} {uri} {shlex.quote(json.dumps(params, separators=(',', ':')))} </dev/null"


class WebosDevice:
    """A TV reachable over Developer Mode SSH. Each call opens its own short-lived connection."""

    def __init__(self, host: str, key_pem: str, passphrase: str, port: int = SSH_PORT) -> None:
        self.host = host
        self.port = port
        self._key_pem = key_pem
        self._passphrase = passphrase
        self._key: asyncssh.SSHKey | None = None

    async def _connect(self) -> asyncssh.SSHClientConnection:
        if self._key is None:
            self._key = load_key(self._key_pem, self._passphrase)
        try:
            return await asyncssh.connect(
                self.host,
                self.port,
                username=SSH_USER,
                client_keys=[self._key],
                known_hosts=None,  # the host key changes whenever Developer Mode is reinstalled
                agent_path=None,
                config=[],
                preferred_auth="publickey",
                connect_timeout=_CONNECT_TIMEOUT,
            )
        except asyncssh.PermissionDenied as err:
            raise DeviceAuthError(f"The TV rejected the Developer Mode key: {err}") from err
        except (OSError, TimeoutError, asyncssh.Error) as err:
            raise DeviceConnectError(f"Cannot connect to {self.host}:{self.port}: {err}") from err

    @staticmethod
    async def _run(conn: asyncssh.SSHClientConnection, command: str, timeout: float = 20) -> str:
        try:
            result = await conn.run(command, timeout=timeout)
        except asyncssh.TimeoutError as err:
            raise DeviceError(f"Timeout running {command.split()[0]}") from err
        except asyncssh.Error as err:
            raise DeviceError(f"Command failed: {err}") from err
        return str(result.stdout or "")

    async def _luna(
        self, conn: asyncssh.SSHClientConnection, uri: str, params: dict[str, Any], timeout: float = 20
    ) -> dict[str, Any]:
        out = await self._run(conn, _luna_command(uri, params), timeout)
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        raise DeviceError(f"No reply from {uri}")

    async def get_info(self) -> WebosDeviceInfo:
        async with await self._connect() as conn:
            reply = await self._luna(
                conn,
                "luna://com.webos.service.tv.systemproperty/getSystemInfo",
                {"keys": ["modelName", "serialNumber", "sdkVersion", "firmwareVersion"]},
            )
        if not reply.get("returnValue"):
            raise DeviceError(reply.get("errorText") or "getSystemInfo failed")
        return WebosDeviceInfo(
            serial=reply.get("serialNumber", ""),
            model=reply.get("modelName", ""),
            sdk_version=reply.get("sdkVersion", ""),
            firmware=reply.get("firmwareVersion", ""),
        )

    async def list_apps(self) -> list[WebosApp]:
        async with await self._connect() as conn:
            reply = await self._luna(conn, "luna://com.webos.applicationManager/dev/listApps", {}, timeout=30)
        if not reply.get("returnValue"):
            raise DeviceError(reply.get("errorText") or "listApps failed")
        return [
            WebosApp(
                app_id=a["id"],
                package_id=a["id"],
                title=a.get("title", ""),
                version=str(a.get("version", "")),
            )
            for a in reply.get("apps", [])
            if a.get("id")
        ]

    async def session_token(self) -> str:
        """Developer Mode session token (used to check and extend the session at LG)."""
        async with await self._connect() as conn:
            token = (await self._run(conn, f"cat {TOKEN_FILE}")).strip()
        if not token:
            raise DeviceError("Developer Mode session token not found")
        return token

    async def launch(self, app_id: str, params: dict[str, Any] | None = None) -> str:
        check_id(app_id)
        payload: dict[str, Any] = {"id": app_id}
        if params:
            payload["params"] = params
        async with await self._connect() as conn:
            reply = await self._luna(conn, "luna://com.webos.applicationManager/launch", payload)
        if not reply.get("returnValue"):
            raise LaunchError(reply.get("errorText") or "launch failed")
        return "launched"

    async def install(
        self,
        ipk: bytes,
        package_id: str,
        app_id: str,
        progress: Callable[[str, int], None] | None = None,
    ) -> None:
        """Upload a package over SSH and install it with appInstallService (progress: stage, 0-100)."""

        def report(stage: str, pct: int) -> None:
            if progress:
                progress(stage, pct)

        remote = f"{REMOTE_TMP}/habrew-{check_id(package_id or app_id)}.ipk"
        async with await self._connect() as conn:
            report("upload", 0)
            await self._upload(conn, ipk, remote, lambda sent: report("upload", sent * 100 // max(len(ipk), 1)))
            try:
                report("install", 0)
                await self._install(conn, remote, lambda pct: report("install", pct))
            finally:
                try:
                    await conn.run(f"rm -f {shlex.quote(remote)}", timeout=10)
                except (asyncssh.Error, OSError):
                    pass

    @staticmethod
    async def _upload(
        conn: asyncssh.SSHClientConnection, data: bytes, remote: str, on_sent: Callable[[int], None]
    ) -> None:
        """``prisoner`` has no sftp; the package is streamed through ``cat``."""
        try:
            proc = await conn.create_process(f"cat > {shlex.quote(remote)}", encoding=None)
            for off in range(0, len(data), _UPLOAD_CHUNK):
                proc.stdin.write(data[off : off + _UPLOAD_CHUNK])
                await proc.stdin.drain()
                on_sent(min(off + _UPLOAD_CHUNK, len(data)))
            proc.stdin.write_eof()
            result = await asyncio.wait_for(proc.wait(), 60)
        except (asyncssh.Error, OSError, TimeoutError) as err:
            raise DeviceError(f"Upload failed: {err}") from err
        if result.exit_status not in (0, None):
            raise DeviceError(f"Upload failed: {(result.stderr or b'').decode(errors='replace').strip()}")

    @staticmethod
    async def _install(conn: asyncssh.SSHClientConnection, remote: str, report: Callable[[int], None]) -> None:
        command = _luna_command(
            "luna://com.webos.appInstallService/dev/install",
            {"id": "com.ares.defaultName", "ipkUrl": remote, "subscribe": True},
            interactive=True,
        )
        proc = await conn.create_process(command)
        try:
            await asyncio.wait_for(_follow_install(proc, report), 300)
        except TimeoutError as err:
            raise DeviceError("Installation did not finish in time") from err
        finally:
            proc.close()


async def _follow_install(proc: asyncssh.SSHClientProcess, report: Callable[[int], None]) -> None:
    """Read appInstallService status messages until the package is installed or refused."""
    async for line in proc.stdout:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        _LOGGER.debug("dev/install: %s", line)
        if msg.get("returnValue") is False:
            raise InstallError(msg.get("errorText") or "Installation refused", str(msg.get("errorCode", "")))
        details = msg.get("details") or {}
        state = str(details.get("state", ""))
        if state == "installed":
            report(100)
            return
        if "fail" in state or "errorCode" in details:
            code = str(details.get("errorCode", ""))
            reason = str(details.get("reason") or details.get("errorText") or "")
            raise InstallError(f"{state} [{code}] {reason}".strip(), code, reason)
        for key, pct in _STATE_PROGRESS.items():
            if state.startswith(key):
                report(pct)
                break
    raise DeviceError("The TV closed the connection during installation")
