"""High-level operations on a Samsung Tizen TV in Developer Mode."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from .sdb import SDB_PORT, SdbConnection, SdbError

_LOGGER = logging.getLogger(__name__)

REMOTE_DIR = "/home/owner/share/tmp/sdk_tools"
REMOTE_PACKAGE = f"{REMOTE_DIR}/habrew-package.wgt"
_INSTALL_DONE_RX = re.compile(
    r"spend time|install failed|download failed|check certificate error|invalid certificate chain", re.I
)
_INSTALL_FAILED_RX = re.compile(
    r"install failed|check certificate error|invalid certificate chain|download failed", re.I
)
_PERCENT_RX = re.compile(r"installing\[(\d+)\]")
_FAIL_CODE_RX = re.compile(r"install failed\s*\[\s*([^\]]+)\]\s*(?:,\s*reason:\s*(.*))?", re.I)


@dataclass(frozen=True)
class TizenDeviceInfo:
    """Basic identity of a TV."""

    duid: str
    model: str
    platform_version: str


@dataclass(frozen=True)
class TizenApp:
    """An installed application as reported by vd_applist."""

    app_id: str
    package_id: str
    title: str
    version: str


class TizenInstallError(Exception):
    """vd_appinstall refused the package."""

    def __init__(self, message: str, code: str = "", reason: str = "", kind: str = "unknown") -> None:
        super().__init__(message)
        self.code = code
        self.reason = reason
        self.kind = kind  # author_mismatch | certificate | platform | unknown


def parse_vd_applist(output: str) -> list[TizenApp]:
    """Parse ``0 vd_applist``. Tizen 9 wraps keys and values in dashes."""
    apps: list[TizenApp] = []
    for entry in re.split(r"-{20,}", output):
        fields: dict[str, str] = {}
        for line in entry.replace("\r", "").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip().strip("-").strip()
                if key:
                    fields[key] = value.strip().strip("-").strip()
        if not fields:
            continue
        app_id = fields.get("app_tizen_id") or fields.get("app_id", "")
        package_id = fields.get("app_package_name") or fields.get("app_id", "") or app_id.split(".")[0]
        if not app_id and not package_id:
            continue
        apps.append(
            TizenApp(
                app_id=app_id,
                package_id=package_id,
                title=fields.get("app_title", ""),
                version=fields.get("app_version", ""),
            )
        )
    return apps


def _classify_failure(output: str) -> TizenInstallError:
    match = _FAIL_CODE_RX.search(output)
    code = match.group(1).strip() if match else ""
    reason = (match.group(2) or "").strip(" :") if match else ""
    low = output.lower()
    compact = code.replace(" ", "")
    if "author certificate not match" in low:
        kind = "author_mismatch"
    elif compact.startswith("118012") or "certificate" in low:
        kind = "certificate"
    elif compact.startswith("118019") or compact == "118,-19":
        kind = "platform"
    else:
        kind = "unknown"
    return TizenInstallError(f"Installation failed [{code}] {reason}".strip(), code, reason, kind)


class TizenDevice:
    """A TV reachable over sdb. Each call opens its own short-lived connection."""

    def __init__(self, host: str, port: int = SDB_PORT) -> None:
        self.host = host
        self.port = port

    def _connection(self) -> SdbConnection:
        return SdbConnection(self.host, self.port)

    async def get_info(self) -> TizenDeviceInfo:
        async with self._connection() as conn:
            duid = (await conn.shell("0 getduid", timeout=10)).strip()
            caps = await conn.capability()
            model = conn.banner.split("::")[1].split(":")[0] if "::" in conn.banner else ""
        return TizenDeviceInfo(duid=duid, model=model, platform_version=caps.get("platform_version", ""))

    async def list_apps(self) -> list[TizenApp]:
        async with self._connection() as conn:
            return parse_vd_applist(await conn.shell("0 vd_applist", timeout=30))

    async def install(
        self,
        signed_wgt: bytes,
        package_id: str,
        app_id: str,
        progress: Callable[[str, int], None] | None = None,
    ) -> None:
        """Upload a signed widget and install it (progress: stage, percent 0-100)."""

        def report(stage: str, pct: int) -> None:
            if progress:
                progress(stage, pct)

        async with self._connection() as conn:
            report("upload", 0)
            await conn.push(
                signed_wgt,
                REMOTE_PACKAGE,
                progress=lambda sent, total: report("upload", sent * 100 // max(total, 1)),
            )
            last_error: TizenInstallError | None = None
            for install_id in [i for i in dict.fromkeys([package_id, app_id]) if i]:
                report("install", 0)

                def on_output(text: str) -> None:
                    for pct in _PERCENT_RX.findall(text):
                        report("install", int(pct))

                output = await conn.shell(
                    f"0 vd_appinstall {install_id} {REMOTE_PACKAGE}",
                    timeout=300,
                    done_rx=_INSTALL_DONE_RX,
                    on_output=on_output,
                )
                _LOGGER.debug("vd_appinstall %s output:\n%s", install_id, output)
                if not _INSTALL_FAILED_RX.search(output):
                    report("install", 100)
                    return
                last_error = _classify_failure(output)
                if last_error.kind in ("author_mismatch", "platform"):
                    break  # retrying with the app id will not help
            raise last_error or SdbError("Installation did not run")
