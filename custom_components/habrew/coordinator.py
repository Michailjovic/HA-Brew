"""Coordinator: keeps track of installed apps on the TV and the newest available packages."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import certificates
from .catalog import WEBOSBREW_URL, CatalogClient, CatalogError, parse_webosbrew
from .const import (
    CONF_ASSET_PATTERN,
    CONF_BROADCAST,
    CONF_CATALOG_KEY,
    CONF_CERT_ID,
    CONF_CERTIFICATE,
    CONF_MAC,
    CONF_PASSPHRASE,
    CONF_PRERELEASES,
    CONF_REPO,
    CONF_SOURCE,
    CONF_SSH_KEY,
    CONF_WAKE_ENTITY,
    CONF_WAKE_METHOD,
    CONF_WAKE_TIMEOUT,
    DEFAULT_WAKE_TIMEOUT,
    DEVMODE_RESET_INTERVAL,
    DEVMODE_WARN_HOURS,
    DOMAIN,
    PLATFORM_TIZEN,
    PLATFORM_WEBOS,
    SOURCE_CATALOG,
    STORAGE_VERSION,
    SUBENTRY_APP,
    TV_TIMEOUT,
    UPDATE_INTERVAL,
    USER_AGENT,
    WAKE_ENTITY,
    WAKE_NONE,
    WAKE_WOL,
)
from .drivers.base import (
    DeviceAuthError,
    DeviceConnectError,
    DeviceError,
    InstallError,
    LaunchError,
    UninstallError,
)
from .drivers.tizen import CertificateError, TizenDevice, resign_wgt
from .drivers.webos import DevModeError, WebosDevice, check_session, reset_session
from .drivers.wol import send_magic_packet
from .github import GitHubClient, GitHubError
from .platforms import PlatformSpec, spec_for

_LOGGER = logging.getLogger(__name__)

WAKE_POLL = 3  # seconds between reachability checks while waking up
WAKE_SETTLE = 2  # extra wait after the TV starts answering

type HabrewConfigEntry = ConfigEntry[HabrewCoordinator]


@dataclass
class AppRelease:
    """Newest published package for one app subentry."""

    url: str
    tag: str
    asset_name: str
    release_url: str
    release_notes: str
    version: str
    package_id: str
    app_id: str
    name: str
    required_version: str
    sha256: str = ""
    icon: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppRelease:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class DevModeInfo:
    """LG Developer Mode session as last seen at LG (webOS only)."""

    remaining: int | None = None  # seconds
    checked_at: str | None = None  # ISO timestamps
    last_reset: str | None = None
    error: str | None = None

    @property
    def remaining_hours(self) -> float | None:
        return round(self.remaining / 3600, 1) if self.remaining is not None else None

    @property
    def expires_at(self) -> datetime | None:
        if self.remaining is None or not self.checked_at:
            return None
        checked = dt_util.parse_datetime(self.checked_at)
        return checked + timedelta(seconds=self.remaining) if checked else None


@dataclass
class HabrewData:
    """Snapshot shared by all entities of one TV."""

    reachable: bool = False
    apps: dict[str, Any] = field(default_factory=dict)  # TizenApp | WebosApp by package id
    releases: dict[str, AppRelease] = field(default_factory=dict)  # by subentry id
    errors: dict[str, str] = field(default_factory=dict)  # by subentry id
    devmode: DevModeInfo | None = None


def _version_tuple(text: str) -> tuple[int, ...]:
    """ "6.0" → (6, 0); anything unparsable → ()."""
    parts = []
    for part in (text or "").strip().split("."):
        if not part.isdigit():
            break
        parts.append(int(part))
    return tuple(parts)


def get_catalog_client(hass: HomeAssistant, platform: str = PLATFORM_TIZEN) -> CatalogClient:
    """One catalog cache per platform, shared by all TVs."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    key = "catalog" if platform == PLATFORM_TIZEN else f"catalog_{platform}"
    if key not in domain_data:
        session = async_get_clientsession(hass)
        if platform == PLATFORM_WEBOS:
            domain_data[key] = CatalogClient(session, USER_AGENT, WEBOSBREW_URL, parse_webosbrew)
        else:
            domain_data[key] = CatalogClient(session, USER_AGENT)
    return domain_data[key]


class HabrewCoordinator(DataUpdateCoordinator[HabrewData]):
    """Polls one TV, GitHub and the catalog for its apps."""

    config_entry: HabrewConfigEntry

    def __init__(self, hass: HomeAssistant, entry: HabrewConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=UPDATE_INTERVAL,
        )
        self.spec: PlatformSpec = spec_for(entry.data)
        self.device = self._create_device()
        self.github = GitHubClient(async_get_clientsession(hass), USER_AGENT)
        self.catalog = get_catalog_client(hass, self.spec.key)
        self._devmode_token: str | None = None
        # what HA-Brew installed last: {subentry_id: {"url": release url, "tv_version": version the TV reported}}
        self.installed_releases: dict[str, dict[str, str]] = {}
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._cache_dir = certificates.cache_dir(hass, entry.entry_id)
        self.tv_lock = asyncio.Lock()
        self.progress: dict[str, int] = {}  # subentry id -> percent while installing
        self.data = HabrewData()
        self.active_apps: Any = None  # ActiveAppCoordinator (Samsung only), set in async_setup_entry

    # ------------------------------------------------------------------ helpers

    @property
    def is_webos(self) -> bool:
        return self.spec.key == PLATFORM_WEBOS

    def _create_device(self) -> TizenDevice | WebosDevice:
        data = self.config_entry.data
        if self.is_webos:
            return WebosDevice(data[CONF_HOST], data[CONF_SSH_KEY], data[CONF_PASSPHRASE])
        return TizenDevice(data[CONF_HOST])

    @property
    def app_subentries(self) -> dict[str, ConfigSubentry]:
        return {sid: s for sid, s in self.config_entry.subentries.items() if s.subentry_type == SUBENTRY_APP}

    def installed_app(self, subentry_id: str) -> Any | None:
        release = self.data.releases.get(subentry_id)
        if release is None:
            return None
        return self.data.apps.get(release.package_id) or next(
            (a for a in self.data.apps.values() if a.app_id == release.app_id), None
        )

    def app_id(self, subentry_id: str) -> str | None:
        """Tizen/webOS application id of an app subentry (installed copy first, then the release)."""
        app = self.installed_app(subentry_id)
        if app is not None and app.app_id:
            return app.app_id
        release = self.data.releases.get(subentry_id)
        return release.app_id if release and release.app_id else None

    def latest_version(self, subentry_id: str) -> str | None:
        """Version to offer. A catalog may describe a release with another version string than the
        one the TV reports after installing it; once HA-Brew installed exactly this release and the
        TV still reports that version, the app counts as up to date."""
        release = self.data.releases.get(subentry_id)
        if release is None:
            return None
        app = self.installed_app(subentry_id)
        done = self.installed_releases.get(subentry_id)
        if app and done and done.get("url") == release.url and done.get("tv_version") == app.version:
            return app.version
        return release.version

    def _check_platform(self, release: AppRelease) -> None:
        """Refuse before uploading when the package needs a newer Tizen than the TV runs."""
        required = _version_tuple(release.required_version)
        current = _version_tuple(self.config_entry.data.get("platform_version", ""))
        if required and current and required > current:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="platform_too_old",
                translation_placeholders={
                    "os": self.spec.os_name,
                    "required": release.required_version,
                    "current": self.config_entry.data.get("platform_version", ""),
                },
            )

    def _cache_path(self, subentry_id: str) -> Path:
        return self._cache_dir / f"{subentry_id}{self.spec.suffix}"

    async def async_load(self) -> None:
        """Restore the last known state so entities have values while the TV is off."""
        stored = await self._store.async_load() or {}
        app_cls = self.spec.app_cls
        app_names = {f.name for f in fields(app_cls)}
        devmode = None
        if self.is_webos:
            dm = stored.get("devmode") or {}
            devmode = DevModeInfo(**{k: v for k, v in dm.items() if k in {f.name for f in fields(DevModeInfo)}})
            self._devmode_token = stored.get("devmode_token")
        self.installed_releases = {k: v for k, v in (stored.get("installed") or {}).items() if k in self.app_subentries}
        self.data = HabrewData(
            reachable=False,
            apps={
                k: app_cls(**{kk: vv for kk, vv in v.items() if kk in app_names})
                for k, v in stored.get("apps", {}).items()
            },
            releases={
                k: AppRelease.from_dict(v) for k, v in stored.get("releases", {}).items() if k in self.app_subentries
            },
            devmode=devmode,
        )

    def _payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "apps": {k: asdict(v) for k, v in self.data.apps.items()},
            "releases": {k: asdict(v) for k, v in self.data.releases.items()},
            "installed": self.installed_releases,
        }
        if self.is_webos:
            out["devmode"] = asdict(self.data.devmode) if self.data.devmode else None
            out["devmode_token"] = self._devmode_token
        return out

    def _save(self) -> None:
        self._store.async_delay_save(self._payload, 5)

    async def async_flush(self) -> None:
        """Write pending state now (the entry reloads whenever an app is added or removed)."""
        await self._store.async_save(self._payload())

    # ------------------------------------------------------------------ polling

    async def _async_update_data(self) -> HabrewData:
        data = HabrewData(
            reachable=self.data.reachable,
            apps=dict(self.data.apps),
            releases={k: v for k, v in self.data.releases.items() if k in self.app_subentries},
            errors={},
            devmode=self.data.devmode,
        )
        if not self.tv_lock.locked():
            await self._refresh_tv(data)
        if self.is_webos:
            await self._refresh_devmode(data)
        for subentry_id, subentry in self.app_subentries.items():
            try:
                if subentry.data.get(CONF_SOURCE) == SOURCE_CATALOG:
                    await self._refresh_catalog_release(data, subentry_id, subentry)
                else:
                    await self._refresh_github_release(data, subentry_id, subentry)
            except (GitHubError, CatalogError, ValueError) as err:
                data.errors[subentry_id] = str(err)
                _LOGGER.warning("%s: %s", subentry.title, err)
        self.data = data
        self._save()
        return data

    async def async_refresh_tv(self) -> None:
        """Re-read the app list from the TV only (used by the panel)."""
        data = HabrewData(
            reachable=self.data.reachable,
            apps=dict(self.data.apps),
            releases=self.data.releases,
            errors=self.data.errors,
            devmode=self.data.devmode,
        )
        await self._refresh_tv(data)
        self.async_set_updated_data(data)
        self._save()

    async def _refresh_tv(self, data: HabrewData) -> None:
        try:
            async with self.tv_lock:
                apps = await asyncio.wait_for(self.device.list_apps(), TV_TIMEOUT * 5)
                if self.is_webos:
                    self._devmode_token = await asyncio.wait_for(self.device.session_token(), TV_TIMEOUT * 2)
        except DeviceAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (DeviceConnectError, TimeoutError, OSError):
            data.reachable = False
            return
        except DeviceError as err:
            _LOGGER.debug("Reading app list failed: %s", err)
            data.reachable = False
            return
        data.reachable = True
        data.apps = {a.package_id or a.app_id: a for a in apps}

    # ------------------------------------------------------------------ webOS Developer Mode session

    async def _refresh_devmode(self, data: HabrewData, force_reset: bool = False) -> None:
        """Check the session at LG and restart it once a day (works while the TV is off)."""
        info = DevModeInfo(**asdict(data.devmode)) if data.devmode else DevModeInfo()
        data.devmode = info
        if not self._devmode_token:
            info.error = "Session token not read yet - turn the TV on once."
            self._update_devmode_issue(info)
            return
        session = async_get_clientsession(self.hass)
        now = dt_util.utcnow()
        last_reset = dt_util.parse_datetime(info.last_reset) if info.last_reset else None
        try:
            if force_reset or last_reset is None or now - last_reset >= DEVMODE_RESET_INTERVAL:
                await reset_session(session, self._devmode_token, USER_AGENT)
                info.last_reset = now.isoformat()
            info.remaining = await check_session(session, self._devmode_token, USER_AGENT)
            info.checked_at = now.isoformat()
            info.error = None
        except DevModeError as err:
            info.error = str(err)
            _LOGGER.warning("%s: Developer Mode session: %s", self.config_entry.title, err)
        self._update_devmode_issue(info)

    def _update_devmode_issue(self, info: DevModeInfo) -> None:
        issue_id = f"devmode_{self.config_entry.entry_id}"
        hours = info.remaining_hours
        if info.error and info.checked_at is None and not self._devmode_token:
            return  # nothing known yet; no point in alarming before the first contact
        if info.error or (hours is not None and hours < DEVMODE_WARN_HOURS):
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR if (hours is not None and hours < 72) else ir.IssueSeverity.WARNING,
                translation_key="devmode_expiring",
                translation_placeholders={
                    "tv": self.config_entry.title,
                    "hours": str(int(hours)) if hours is not None else "?",
                    "error": info.error or "-",
                },
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    async def async_extend_devmode(self) -> None:
        """Restart the Developer Mode session now (button / panel)."""
        if not self._devmode_token or (self.data.devmode and self.data.devmode.error):
            try:
                async with self.tv_lock:
                    self._devmode_token = await asyncio.wait_for(self.device.session_token(), TV_TIMEOUT * 2)
            except (DeviceError, TimeoutError, OSError) as err:
                if not self._devmode_token:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="tv_unreachable",
                        translation_placeholders={"error": str(err)},
                    ) from err
        data = HabrewData(
            reachable=self.data.reachable,
            apps=self.data.apps,
            releases=self.data.releases,
            errors=self.data.errors,
            devmode=self.data.devmode,
        )
        await self._refresh_devmode(data, force_reset=True)
        self.async_set_updated_data(data)
        self._save()
        if data.devmode and data.devmode.error:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="devmode_failed",
                translation_placeholders={"error": data.devmode.error},
            )

    async def _refresh_github_release(self, data: HabrewData, subentry_id: str, subentry: ConfigSubentry) -> None:
        asset = await self.github.latest_asset(
            subentry.data[CONF_REPO],
            subentry.data[CONF_ASSET_PATTERN],
            subentry.data.get(CONF_PRERELEASES, False),
        )
        current = data.releases.get(subentry_id)
        cache = self._cache_path(subentry_id)
        if current and current.url == asset.url and await self.hass.async_add_executor_job(cache.exists):
            current.release_notes = asset.release_notes
            return
        _LOGGER.debug("Downloading %s %s", asset.repo, asset.name)
        package = await self.github.download(asset.url)
        meta = await self.hass.async_add_executor_job(self.spec.read_metadata, package)
        await self.hass.async_add_executor_job(self._write_cache, cache, package, asset.url)
        data.releases[subentry_id] = AppRelease(
            url=asset.url,
            tag=asset.tag,
            asset_name=asset.name,
            release_url=asset.release_url,
            release_notes=asset.release_notes,
            version=meta.version or asset.tag.lstrip("v"),
            package_id=meta.package_id,
            app_id=meta.app_id,
            name=meta.name,
            required_version=meta.required_version,
        )

    async def _refresh_catalog_release(self, data: HabrewData, subentry_id: str, subentry: ConfigSubentry) -> None:
        catalog = await self.catalog.get()
        entry = catalog.entries.get(subentry.data[CONF_CATALOG_KEY])
        if entry is None:
            raise CatalogError(f"{subentry.title} is no longer in the catalog")
        data.releases[subentry_id] = AppRelease(
            url=entry.url,
            tag=entry.version,
            asset_name=entry.file,
            release_url=f"https://github.com/{entry.repo}" if entry.repo else "",
            release_notes=entry.description,
            version=entry.version,
            package_id=entry.package_id,
            app_id=entry.app_id,
            name=entry.name,
            required_version=entry.required_version,
            sha256=entry.sha256,
            icon=entry.icon,
        )

    @staticmethod
    def _write_cache(path: Path, package: bytes, url: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(package)
        path.with_suffix(".json").write_text(json.dumps({"url": url}))

    @staticmethod
    def _read_cache(path: Path, url: str) -> bytes | None:
        try:
            meta = json.loads(path.with_suffix(".json").read_text())
            if meta.get("url") != url:
                return None
            return path.read_bytes()
        except (OSError, ValueError):
            return None

    # ------------------------------------------------------------------ wake / launch

    @property
    def wake_method(self) -> str:
        return self.config_entry.options.get(CONF_WAKE_METHOD, WAKE_NONE)

    async def _probe(self) -> bool:
        try:
            await asyncio.wait_for(self.device.get_info(), TV_TIMEOUT * 2)
        except (DeviceError, TimeoutError, OSError):
            return False
        return True

    async def async_wake(self) -> None:
        """Send the configured wake-up (WoL packet or turn_on of an entity)."""
        opts = self.config_entry.options
        if self.wake_method == WAKE_WOL:
            await self.hass.async_add_executor_job(
                send_magic_packet,
                opts[CONF_MAC],
                opts.get(CONF_BROADCAST) or "255.255.255.255",
            )
        elif self.wake_method == WAKE_ENTITY:
            entity_id = opts[CONF_WAKE_ENTITY]
            domain = entity_id.split(".", 1)[0]
            if domain == "button":
                await self.hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)
            elif domain == "script":
                await self.hass.services.async_call("script", "turn_on", {"entity_id": entity_id}, blocking=True)
            else:
                await self.hass.services.async_call("homeassistant", "turn_on", {"entity_id": entity_id}, blocking=True)

    async def async_ensure_awake(self) -> None:
        """Make sure the TV answers sdb, waking it up first if configured."""
        if await self._probe():
            return
        if self.wake_method == WAKE_NONE:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="tv_unreachable",
                translation_placeholders={"error": "offline"},
            )
        _LOGGER.debug("Waking up %s via %s", self.config_entry.title, self.wake_method)
        await self.async_wake()
        loop = asyncio.get_running_loop()
        timeout = self.config_entry.options.get(CONF_WAKE_TIMEOUT, DEFAULT_WAKE_TIMEOUT)
        start = loop.time()
        resent = False
        while loop.time() - start < timeout:
            await asyncio.sleep(WAKE_POLL)
            if await self._probe():
                await asyncio.sleep(WAKE_SETTLE)  # sdbd answers a moment before the app manager is ready
                return
            if not resent and loop.time() - start > timeout / 2:
                await self.async_wake()  # a second attempt helps TVs in deep standby
                resent = True
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="wake_failed")

    async def async_launch(self, app_id: str) -> None:
        await self.async_ensure_awake()
        try:
            async with self.tv_lock:
                await self.device.launch(app_id)
        except (LaunchError, ValueError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="launch_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except (DeviceError, TimeoutError, OSError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="tv_unreachable",
                translation_placeholders={"error": str(err)},
            ) from err

    # ------------------------------------------------------------------ install

    def _set_progress(self, subentry_id: str, pct: int | None) -> None:
        if pct is None:
            self.progress.pop(subentry_id, None)
        elif self.progress.get(subentry_id) == pct:
            return
        else:
            self.progress[subentry_id] = pct
        self.async_update_listeners()

    async def async_install(self, subentry_id: str, progress: Callable[[int], None] | None = None) -> None:
        """Install the newest package on the TV (Tizen: signed with the app's certificate first)."""
        if subentry_id in self.progress:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="install_running")
        subentry = self.config_entry.subentries.get(subentry_id)
        if subentry is None or subentry.subentry_type != SUBENTRY_APP:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="unknown_app")
        release = self.data.releases.get(subentry_id)
        if release is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="no_release",
                translation_placeholders={"app": subentry.title},
            )
        self._check_platform(release)
        cert_subentry = None
        if self.spec.needs_certificate:
            cert_subentry = self.config_entry.subentries.get(subentry.data.get(CONF_CERTIFICATE) or "")
            if cert_subentry is None:
                raise HomeAssistantError(translation_domain=DOMAIN, translation_key="certificate_missing")

        def report(pct: int) -> None:
            self._set_progress(subentry_id, pct)
            if progress:
                progress(pct)

        report(1)
        try:
            await self.async_ensure_awake()
            await self._install(subentry_id, release, cert_subentry, report)
        finally:
            self._set_progress(subentry_id, None)
        await self.async_refresh_tv()
        if app := self.installed_app(subentry_id):
            self.installed_releases[subentry_id] = {"url": release.url, "tv_version": app.version}
            self._save()
            self.async_update_listeners()

    async def async_uninstall(self, app_id: str) -> None:
        """Remove an app from the TV (and check that it is gone)."""
        await self.async_ensure_awake()
        try:
            async with self.tv_lock:
                await self.device.uninstall(app_id)
        except (UninstallError, ValueError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="uninstall_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except DeviceAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except (DeviceError, TimeoutError, OSError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="tv_unreachable",
                translation_placeholders={"error": str(err)},
            ) from err
        finally:
            await self.async_refresh_tv()
        for sid in [sid for sid in self.installed_releases if self.installed_app(sid) is None]:
            self.installed_releases.pop(sid)
        self._save()

    async def _install(
        self,
        subentry_id: str,
        release: AppRelease,
        cert_subentry: ConfigSubentry | None,
        report: Callable[[int], None],
    ) -> None:
        cache = self._cache_path(subentry_id)
        package = await self.hass.async_add_executor_job(self._read_cache, cache, release.url)
        if package is None:
            try:
                package = await self.github.download(release.url)
            except GitHubError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="download_failed",
                    translation_placeholders={"error": str(err)},
                ) from err
            if release.sha256 and hashlib.sha256(package).hexdigest() != release.sha256:
                raise HomeAssistantError(translation_domain=DOMAIN, translation_key="checksum_mismatch")
            await self.hass.async_add_executor_job(self._write_cache, cache, package, release.url)
        report(5)
        if cert_subentry is not None:
            try:
                profile = await self.hass.async_add_executor_job(
                    certificates.load_profile,
                    self.hass,
                    self.config_entry.entry_id,
                    cert_subentry.data[CONF_CERT_ID],
                )
                package = await self.hass.async_add_executor_job(resign_wgt, package, profile)
            except (CertificateError, OSError) as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="certificate_invalid",
                    translation_placeholders={"error": str(err)},
                ) from err
        report(10)

        def on_progress(stage: str, pct: int) -> None:
            report(10 + pct * 70 // 100 if stage == "upload" else 80 + pct * 19 // 100)

        try:
            async with self.tv_lock:
                await self.device.install(package, release.package_id, release.app_id, on_progress)
        except InstallError as err:
            key = {
                "author_mismatch": "install_author_mismatch",
                "certificate": "install_certificate",
                "platform": "install_platform",
            }.get(err.kind, "install_failed")
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=key,
                translation_placeholders={
                    "error": str(err),
                    "certificate": cert_subentry.title if cert_subentry else "",
                },
            ) from err
        except DeviceAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except DeviceConnectError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="tv_unreachable",
                translation_placeholders={"error": str(err)},
            ) from err
        except (DeviceError, ValueError, TimeoutError, OSError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="install_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        report(100)
