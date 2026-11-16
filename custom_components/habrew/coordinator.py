"""Coordinator: keeps track of installed apps on the TV and the newest GitHub releases."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import certificates
from .const import (
    CONF_ASSET_PATTERN,
    CONF_CERT_ID,
    CONF_CERTIFICATE,
    CONF_PRERELEASES,
    CONF_REPO,
    DOMAIN,
    STORAGE_VERSION,
    SUBENTRY_APP,
    TV_TIMEOUT,
    UPDATE_INTERVAL,
    USER_AGENT,
)
from .drivers.tizen import (
    CertificateError,
    SdbConnectError,
    SdbError,
    TizenApp,
    TizenDevice,
    TizenInstallError,
    read_wgt_metadata,
    resign_wgt,
)
from .github import GitHubClient, GitHubError

_LOGGER = logging.getLogger(__name__)

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


@dataclass
class HabrewData:
    """Snapshot shared by all entities of one TV."""

    reachable: bool = False
    apps: dict[str, TizenApp] = field(default_factory=dict)  # by package id
    releases: dict[str, AppRelease] = field(default_factory=dict)  # by subentry id
    errors: dict[str, str] = field(default_factory=dict)  # by subentry id


class HabrewCoordinator(DataUpdateCoordinator[HabrewData]):
    """Polls one TV and the GitHub repositories of its apps."""

    config_entry: HabrewConfigEntry

    def __init__(self, hass: HomeAssistant, entry: HabrewConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=f"{DOMAIN} {entry.title}", update_interval=UPDATE_INTERVAL
        )
        self.device = TizenDevice(entry.data[CONF_HOST])
        self.github = GitHubClient(async_get_clientsession(hass), USER_AGENT)
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._cache_dir = certificates.cache_dir(hass, entry.entry_id)
        self.tv_lock = asyncio.Lock()
        self.data = HabrewData()

    # ------------------------------------------------------------------ helpers

    @property
    def app_subentries(self) -> dict[str, ConfigSubentry]:
        return {sid: s for sid, s in self.config_entry.subentries.items() if s.subentry_type == SUBENTRY_APP}

    def installed_app(self, subentry_id: str) -> TizenApp | None:
        release = self.data.releases.get(subentry_id)
        if release is None:
            return None
        return self.data.apps.get(release.package_id) or next(
            (a for a in self.data.apps.values() if a.app_id == release.app_id), None
        )

    def _cache_path(self, subentry_id: str) -> Path:
        return self._cache_dir / f"{subentry_id}.wgt"

    async def async_load(self) -> None:
        """Restore the last known state so entities have values while the TV is off."""
        stored = await self._store.async_load() or {}
        self.data = HabrewData(
            reachable=False,
            apps={k: TizenApp(**v) for k, v in stored.get("apps", {}).items()},
            releases={k: AppRelease(**v) for k, v in stored.get("releases", {}).items() if k in self.app_subentries},
        )

    def _save(self) -> None:
        self._store.async_delay_save(
            lambda: {
                "apps": {k: asdict(v) for k, v in self.data.apps.items()},
                "releases": {k: asdict(v) for k, v in self.data.releases.items()},
            },
            5,
        )

    # ------------------------------------------------------------------ polling

    async def _async_update_data(self) -> HabrewData:
        data = HabrewData(
            reachable=self.data.reachable,
            apps=dict(self.data.apps),
            releases={k: v for k, v in self.data.releases.items() if k in self.app_subentries},
            errors={},
        )
        if not self.tv_lock.locked():
            await self._refresh_tv(data)
        for subentry_id, subentry in self.app_subentries.items():
            try:
                await self._refresh_release(data, subentry_id, subentry)
            except (GitHubError, ValueError) as err:
                data.errors[subentry_id] = str(err)
                _LOGGER.warning("%s: %s", subentry.title, err)
        self.data = data
        self._save()
        return data

    async def _refresh_tv(self, data: HabrewData) -> None:
        try:
            async with self.tv_lock:
                apps = await asyncio.wait_for(self.device.list_apps(), TV_TIMEOUT * 5)
        except (SdbConnectError, TimeoutError, OSError):
            data.reachable = False
            return
        except SdbError as err:
            _LOGGER.debug("Reading app list failed: %s", err)
            data.reachable = False
            return
        data.reachable = True
        data.apps = {a.package_id or a.app_id: a for a in apps}

    async def _refresh_release(self, data: HabrewData, subentry_id: str, subentry: ConfigSubentry) -> None:
        asset = await self.github.latest_asset(
            subentry.data[CONF_REPO], subentry.data[CONF_ASSET_PATTERN], subentry.data.get(CONF_PRERELEASES, False)
        )
        current = data.releases.get(subentry_id)
        cache = self._cache_path(subentry_id)
        if current and current.url == asset.url and await self.hass.async_add_executor_job(cache.exists):
            # same package; refresh release notes only
            current.release_notes = asset.release_notes
            return
        _LOGGER.debug("Downloading %s %s", asset.repo, asset.name)
        package = await self.github.download(asset.url)
        meta = await self.hass.async_add_executor_job(read_wgt_metadata, package)
        await self.hass.async_add_executor_job(self._write_cache, cache, package)
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

    @staticmethod
    def _write_cache(path: Path, package: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(package)

    # ------------------------------------------------------------------ install

    async def async_install(self, subentry_id: str, progress: Callable[[int], None]) -> None:
        """Sign the cached package with the app's certificate and install it on the TV."""
        subentry = self.config_entry.subentries[subentry_id]
        release = self.data.releases.get(subentry_id)
        if release is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="no_release",
                translation_placeholders={"app": subentry.title},
            )
        cert_subentry = self.config_entry.subentries.get(subentry.data[CONF_CERTIFICATE])
        if cert_subentry is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="certificate_missing")

        progress(1)
        cache = self._cache_path(subentry_id)
        try:
            package = await self.hass.async_add_executor_job(cache.read_bytes)
        except OSError:
            package = await self.github.download(release.url)
            await self.hass.async_add_executor_job(self._write_cache, cache, package)
        progress(5)
        try:
            profile = await self.hass.async_add_executor_job(
                certificates.load_profile, self.hass, self.config_entry.entry_id, cert_subentry.data[CONF_CERT_ID]
            )
            signed = await self.hass.async_add_executor_job(resign_wgt, package, profile)
        except (CertificateError, OSError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="certificate_invalid",
                translation_placeholders={"error": str(err)},
            ) from err
        progress(10)

        def on_progress(stage: str, pct: int) -> None:
            progress(10 + pct * 70 // 100 if stage == "upload" else 80 + pct * 19 // 100)

        try:
            async with self.tv_lock:
                await self.device.install(signed, release.package_id, release.app_id, on_progress)
        except TizenInstallError as err:
            key = {
                "author_mismatch": "install_author_mismatch",
                "certificate": "install_certificate",
                "platform": "install_platform",
            }.get(err.kind, "install_failed")
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=key,
                translation_placeholders={"error": str(err), "certificate": cert_subentry.title},
            ) from err
        except SdbConnectError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="tv_unreachable",
                translation_placeholders={"error": str(err)},
            ) from err
        except (SdbError, TimeoutError, OSError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="install_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        progress(100)
        await self.async_request_refresh()
