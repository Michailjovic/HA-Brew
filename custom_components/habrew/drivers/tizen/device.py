"""High-level operations on a Samsung Tizen TV in Developer Mode."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from ..base import InstallError, LaunchError, UninstallError, check_id
from .sdb import SDB_PORT, SdbConnection, SdbError

_LOGGER = logging.getLogger(__name__)

REMOTE_DIR = "/home/owner/share/tmp/sdk_tools"
REMOTE_PACKAGE = f"{REMOTE_DIR}/habrew-package.wgt"
_INSTALL_DONE_RX = re.compile(
    r"spend time|install failed|download failed|check certificate error|invalid certificate chain",
    re.IGNORECASE,
)
_INSTALL_FAILED_RX = re.compile(
    r"install failed|check certificate error|invalid certificate chain|download failed",
    re.IGNORECASE,
)
_PERCENT_RX = re.compile(r"installing\[(\d+)\]")
_UNINSTALL_DONE_RX = re.compile(r"spend time|uninstall\w* (?:completed|failed)|failed|not exist", re.IGNORECASE)
_FAIL_CODE_RX = re.compile(r"install failed\s*\[\s*([^\]]+)\]\s*(?:,\s*reason:\s*(.*))?", re.IGNORECASE)


@dataclass(frozen=True)
class TizenDeviceInfo:
    """Basic identity of a TV."""

    duid: str
    model: str
    platform_version: str


@dataclass(frozen=True)
class TizenApp:
    """An installed application as reported by vd_applist."""

    @property
    def origin(self) -> str:
        """sideload | store | system (unknown values count as sideload)."""
        if self.app_type == "normal":
            return "store" if self.install_source == "1" else "system"
        return "sideload"

    app_id: str
    package_id: str
    title: str
    version: str
    app_type: str = ""  # "user" = sideloaded, "normal" = store / preinstalled
    install_source: str = ""  # installed_source_type: "1" = Samsung store


class TizenInstallError(InstallError):
    """vd_appinstall refused the package."""


class TizenLaunchError(LaunchError):
    """The TV refused to start the app."""


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
                app_type=fields.get("type", ""),
                install_source=fields.get("installed_source_type", ""),
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
        self.last_output = ""  # raw output of the last failed install/uninstall (diagnostics)
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

    async def launch(self, app_id: str) -> str:
        """Start an installed app (Smart Hub launcher). Returns the TV's reply."""
        check_id(app_id)
        async with self._connection() as conn:
            reply = await conn.shell(f"0 was_execute {app_id}", timeout=20)
        if re.search(r"launch failed|not exist|not found", reply, re.IGNORECASE) or "launched" not in reply.lower():
            raise TizenLaunchError(reply.strip() or "No reply from the TV")
        return reply.strip()

    async def uninstall(self, app_id: str) -> None:
        """Remove an app from the TV and check that it is really gone.

        Some newer TVs accept the command but keep the app (reported for 2021+ models), so the
        app list is read again afterwards.
        """
        check_id(app_id)
        async with self._connection() as conn:
            try:
                output = await conn.shell(f"0 vd_appuninstall {app_id}", timeout=120, done_rx=_UNINSTALL_DONE_RX)
            except SdbError as err:
                output = str(err)
            _LOGGER.debug("vd_appuninstall %s output:\n%s", app_id, output)
            apps = parse_vd_applist(await conn.shell("0 vd_applist", timeout=30))
        if any(app_id in (a.app_id, a.package_id) for a in apps):
            self.last_output = output[-2000:]
            raise UninstallError(output.strip() or "The TV kept the app")

    async def diagnostics(self) -> dict:
        """Raw facts about the TV for support (redacted by the integration)."""
        async with self._connection() as conn:
            caps = await conn.capability()
            duid = (await conn.shell("0 getduid", timeout=10)).strip()
            applist = await conn.shell("0 vd_applist", timeout=30)
            banner = conn.banner
        entries = [e for e in re.split(r"-{20,}\s*\n", applist.replace("\r", "")) if "=" in e]
        return {
            "banner": banner,
            "capability": caps,
            "duid": duid,
            "app_count": len(parse_vd_applist(applist)),
            "vd_applist_sample": entries[:3],
            "last_error_output": self.last_output,
        }

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

        for value in (package_id, app_id):
            if value:
                check_id(value)
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
                    self.last_output = ""
                    report("install", 100)
                    return
                self.last_output = output[-2000:]
                last_error = _classify_failure(output)
                if last_error.kind in ("author_mismatch", "platform"):
                    break  # retrying with the app id will not help
            raise last_error or SdbError("Installation did not run")
