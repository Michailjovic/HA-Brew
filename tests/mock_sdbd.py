"""In-process fake of a Samsung TV's sdbd for tests."""

from __future__ import annotations

import asyncio
import struct

_H = struct.Struct("<6I")


def _c(s: str) -> int:
    return int.from_bytes(s.encode(), "little")


CNXN, OPEN, OKAY, CLSE, WRTE = map(_c, ["CNXN", "OPEN", "OKAY", "CLSE", "WRTE"])
SEP = "-" * 93


class MockSdbd:
    def __init__(self, duid: str = "MOCKDUID") -> None:
        self.duid = duid
        self.apps = {"NuvioTV001": ("NuvioTV001.NuvioTV", "Nuvio TV", "1.3.6")}
        self.install_result = "ok"  # ok | author_mismatch
        self.install_version = "1.4.2"  # what the TV reports after a successful install
        self.pushed: bytes | None = None
        self.installs: list[str] = []
        self.launched: list[str] = []
        self.uninstall_allowed = True  # False = TV accepts the command but keeps the app (2021+ models)
        self.awake = True  # False = TV in standby, connections are dropped
        self.port = 0
        self._server: asyncio.base_events.Server | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    def _applist(self) -> str:
        out = SEP + "\n"
        for pkg, (app_id, title, ver) in self.apps.items():
            out += (
                f"--------------app_id   = {pkg}-------------\n--------------app_title   = {title}-------------\n"
                f"--------------app_version   = {ver}-------------\n--------------app_tizen_id   = {app_id}-------------\n"
                f"--------------app_package_name   = {pkg}-------------\n{SEP}\n"
            )
        return out

    async def _handle(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        async def send(cmd, a0, a1, data=b""):
            w.write(_H.pack(cmd, a0, a1, len(data), sum(data) & 0xFFFFFFFF, cmd ^ 0xFFFFFFFF) + data)
            await w.drain()

        if not self.awake:
            w.close()
            return
        rid = 100
        streams: dict[int, dict] = {}
        try:
            while True:
                hdr = await r.readexactly(24)
                cmd, a0, a1, ln, chk, mg = _H.unpack(hdr)
                data = await r.readexactly(ln) if ln else b""
                assert mg == cmd ^ 0xFFFFFFFF and chk == sum(data) & 0xFFFFFFFF
                if cmd == CNXN:
                    await send(CNXN, 0x01000000, 4096, b"device::QE55MOCK::0\0")
                elif cmd == OPEN:
                    svc = data.rstrip(b"\0").decode()
                    rid += 1
                    streams[rid] = {"svc": svc, "local": a0, "buf": b"", "file": b""}
                    await send(OKAY, rid, a0)
                    out = self._shell(svc)
                    if out is not None:
                        for i in range(0, len(out), 60):
                            await send(WRTE, rid, a0, out[i : i + 60].encode())
                        await send(CLSE, rid, a0)
                elif cmd == WRTE:
                    st = streams[a1]
                    await send(OKAY, a1, st["local"])
                    if st["svc"] == "sync:":
                        await self._sync(st, data, a1, send)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            w.close()

    def _shell(self, svc: str) -> str | None:
        if svc == "shell:0 getduid":
            return self.duid + "\n"
        if svc == "shell:0 vd_applist":
            return self._applist()
        if svc == "capability:":
            return "platform_version:9.0\nsdk_toolpath:/home/owner/share/tmp/sdk_tools\n"
        if svc.startswith("shell:0 was_execute"):
            app_id = svc.split()[2]
            if any(a[0] == app_id for a in self.apps.values()):
                self.launched.append(app_id)
                return f"app_id[{app_id.split('.')[0]}] launched\n"
            return f"app_id[{app_id}] launch failed[-1]\n"
        if svc.startswith("shell:0 vd_appuninstall"):
            ident = svc.split()[2]
            pkg = next((k for k, a in self.apps.items() if ident in (k, a[0])), None)
            if pkg and self.uninstall_allowed:
                del self.apps[pkg]
                return f"app_id[{ident}] uninstall start\napp_id[{ident}] uninstall completed\nspend time for wascmd is [900]ms\n"
            return "spend time for wascmd is [100]ms\n"
        if svc.startswith("shell:0 vd_appinstall"):
            ident = svc.split()[2]
            self.installs.append(ident)
            if self.install_result == "author_mismatch":
                return (
                    f"app_id[{ident}] install start\napp_id[{ident}] installing[20]\n"
                    f"app_id[{ident}] install failed[118, -11], reason: Author certificate not match :\n"
                    "spend time for wascmd is [4000]ms\n"
                )
            app_id, title, _ = self.apps.get("NuvioTV001", ("NuvioTV001.NuvioTV", "Nuvio TV", ""))
            self.apps["NuvioTV001"] = (app_id, title, self.install_version)
            return (
                f"app_id[{ident}] install start\napp_id[{ident}] installing[50]\napp_id[{ident}] installing[100]\n"
                f"app_id[{ident}] install completed\nspend time for wascmd is [6000]ms\n"
            )
        if svc.startswith("shell:"):
            return "closed\n"
        return None

    async def _sync(self, st, data, rid, send) -> None:
        st["buf"] += data
        while len(st["buf"]) >= 8:
            tag = st["buf"][:4]
            n = struct.unpack("<I", st["buf"][4:8])[0]
            if tag in (b"SEND", b"DATA"):
                if len(st["buf"]) < 8 + n:
                    return
                body = st["buf"][8 : 8 + n]
                st["buf"] = st["buf"][8 + n :]
                if tag == b"DATA":
                    st["file"] += body
            elif tag == b"DONE":
                st["buf"] = st["buf"][8:]
                self.pushed = st["file"]
                await send(WRTE, rid, st["local"], b"OKAY\0\0\0\0")
            elif tag == b"QUIT":
                st["buf"] = st["buf"][8:]
                await send(CLSE, rid, st["local"])
            else:
                raise AssertionError(tag)
