"""A fake LG webOS Developer Mode SSH server (asyncssh) that answers like a TV does."""

from __future__ import annotations

import asyncio
import io
import json
import re
import tarfile

import asyncssh
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from custom_components.habrew.drivers.webos import read_ipk_metadata

PASSPHRASE = "ABC123"
SERIAL = "509MOCK0001"
TOKEN = "f" * 64


def make_key_pem(passphrase: str = PASSPHRASE) -> str:
    """RSA key in the same legacy encrypted PEM format the TV's Key Server serves."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.BestAvailableEncryption(passphrase.encode()),
    ).decode()


def _tar_gz(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def _ar(members: dict[str, bytes]) -> bytes:
    out = b"!<arch>\n"
    for name, data in members.items():
        header = f"{name + '/':<16}{0:<12}{0:<6}{0:<6}{'100644':<8}{len(data):<10}`\n".encode()
        out += header + data + (b"\n" if len(data) % 2 else b"")
    return out


def make_ipk(app_id: str = "space.nuvio.webos", version: str = "1.4.4", title: str = "Nuvio TV") -> bytes:
    control = _tar_gz({"./control": f"Package: {app_id}\nVersion: {version}\nArchitecture: all\n".encode()})
    appinfo = json.dumps({"id": app_id, "version": version, "title": title, "type": "web"}).encode()
    data = _tar_gz(
        {
            f"./usr/palm/applications/{app_id}/index.html": b"<html></html>",
            f"./usr/palm/applications/{app_id}/appinfo.json": appinfo,
            f"./usr/palm/services/{app_id}.service/services.json": b"{}",
        }
    )
    return _ar({"debian-binary": b"2.0\n", "control.tar.gz": control, "data.tar.gz": data})


class MockWebosTv:
    """SSH on a random port; ``key_pem`` is what the Key Server would hand out."""

    def __init__(self) -> None:
        self.key_pem = make_key_pem()
        self._authorized = asyncssh.import_private_key(self.key_pem, PASSPHRASE).export_public_key().decode()
        self.apps: dict[str, dict] = {
            "org.webosbrew.hbchannel": {
                "id": "org.webosbrew.hbchannel",
                "version": "0.7.3",
                "title": "Homebrew Channel",
            },
            "space.nuvio.webos": {"id": "space.nuvio.webos", "version": "1.4.0", "title": "Nuvio TV"},
        }
        self.files: dict[str, bytes] = {}
        self.installed: list[str] = []
        self.launched: list[str] = []
        self.install_result = "ok"
        self.port = 0
        self._server: asyncssh.SSHAcceptor | None = None

    async def start(self) -> None:
        host_key = asyncssh.generate_private_key("ssh-rsa")
        mock = self

        class Server(asyncssh.SSHServer):
            def begin_auth(self, username: str) -> bool:
                return True

            def public_key_auth_supported(self) -> bool:
                return True

            def validate_public_key(self, username: str, key: asyncssh.SSHKey) -> bool:
                return username == "prisoner" and key.export_public_key().decode() == mock._authorized

        self._server = await asyncssh.create_server(
            Server, "127.0.0.1", 0, server_host_keys=[host_key], process_factory=self._handle, encoding=None
        )
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, process: asyncssh.SSHServerProcess) -> None:
        command = process.command or ""
        try:
            await self._dispatch(process, command)
        finally:
            process.exit(0)

    async def _dispatch(self, process: asyncssh.SSHServerProcess, command: str) -> None:
        if command.startswith("cat > "):
            path = command.removeprefix("cat > ").strip("'")
            self.files[path] = await process.stdin.read()
            return
        if command.startswith("cat /var/luna/preferences/devmode_enabled"):
            process.stdout.write(TOKEN.encode())
            return
        if command.startswith("rm -f "):
            self.files.pop(command.removeprefix("rm -f ").strip("'"), None)
            return
        match = re.match(r"luna-send-pub (-n 1|-i) (\S+) '(.*)' </dev/null$", command)
        if not match:
            process.stderr.write(f"unknown command {command}\n".encode())
            return
        uri, params = match.group(2), json.loads(match.group(3))
        if uri.endswith("/getSystemInfo"):
            reply = {
                "returnValue": True,
                "modelName": "OLED55MOCK",
                "serialNumber": SERIAL,
                "sdkVersion": "11.2.0",
                "firmwareVersion": "43.21.96",
            }
        elif uri.endswith("/dev/listApps"):
            reply = {"returnValue": True, "apps": list(self.apps.values())}
        elif uri.endswith("/launch"):
            if params["id"] in self.apps or params["id"] == "com.palmdts.devmode":
                self.launched.append(params["id"])
                reply = {"returnValue": True}
            else:
                reply = {"returnValue": False, "errorCode": -101, "errorText": "not exist"}
        elif uri.endswith("/dev/install"):
            await self._install(process, params["ipkUrl"])
            return
        else:
            reply = {"returnValue": False, "errorText": f'Denied method call "{uri}"'}
        process.stdout.write((json.dumps(reply) + "\n").encode())

    async def _install(self, process: asyncssh.SSHServerProcess, path: str) -> None:
        def status(state: str, **extra) -> None:
            details = {"state": state, "progress": 100, **extra}
            process.stdout.write((json.dumps({"details": details, "id": "com.ares.defaultName"}) + "\n").encode())

        process.stdout.write(b'{"subscribed":true,"returnValue":true}\n')
        status("ipk verifying")
        data = self.files.get(path)
        if data is None or self.install_result != "ok":
            status("install failed", errorCode=-5, reason="IPK Extraction Failure")
        else:
            meta = read_ipk_metadata(data)
            status("ipk parsing")
            status("installing : start")
            self.apps[meta.app_id] = {"id": meta.app_id, "version": meta.version, "title": meta.name}
            self.installed.append(meta.app_id)
            status("installed")
        # luna-send-pub -i keeps running until the client closes the channel
        try:
            await asyncio.wait_for(process.stdin.read(), 5)
        except (TimeoutError, asyncssh.BreakReceived, asyncssh.TerminalSizeChanged):
            pass


class MockKeyServer:
    """HTTP/1.0 server for ``/webos_rsa`` on a random port."""

    def __init__(self, pem: str) -> None:
        self.pem = pem
        self.port = 0
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await reader.readuntil(b"\r\n\r\n")
            body = self.pem.encode()
            writer.write(b"HTTP/1.0 200 OK\r\nContent-Type: application/octet-stream\r\n\r\n")
            # split like a real TCP stream so the client has to read until EOF
            writer.write(body[:100])
            await writer.drain()
            await asyncio.sleep(0.05)
            writer.write(body[100:])
            await writer.drain()
            writer.close()

        self._server = await asyncio.start_server(handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
