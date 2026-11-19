"""WebSocket API used by the HA-Brew sidebar panel."""

from __future__ import annotations

import logging
import re
from types import MappingProxyType
from typing import Any

import voluptuous as vol
from awesomeversion import AwesomeVersion
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .catalog import Catalog, CatalogError
from .const import (
    CONF_ASSET_PATTERN,
    CONF_AUTHOR_CN,
    CONF_CATALOG_KEY,
    CONF_CERT_TYPE,
    CONF_CERTIFICATE,
    CONF_EXPIRES,
    CONF_PRERELEASES,
    CONF_PRESET,
    CONF_REPO,
    CONF_SOURCE,
    DOMAIN,
    PLATFORM_TIZEN,
    PRESET_CUSTOM,
    SOURCE_CATALOG,
    SOURCE_GITHUB,
    SUBENTRY_APP,
    SUBENTRY_CERTIFICATE,
    USER_AGENT,
)
from .coordinator import HabrewConfigEntry, HabrewCoordinator, get_catalog_client
from .github import GitHubClient, GitHubError, NoMatchingAsset
from .platforms import SPECS, spec_for
from .presets import preset_for_package

_LOGGER = logging.getLogger(__name__)
REPO_RX = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@callback
def async_register(hass: HomeAssistant) -> None:
    for handler in (
        ws_overview,
        ws_catalog,
        ws_app_add,
        ws_app_remove,
        ws_app_install,
        ws_refresh,
        ws_app_launch,
        ws_wake,
        ws_devmode_extend,
    ):
        websocket_api.async_register_command(hass, handler)


# ---------------------------------------------------------------------- helpers


def _entry(hass: HomeAssistant, entry_id: str) -> HabrewConfigEntry:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise HomeAssistantError(f"Unknown TV {entry_id}")
    return entry


def _coordinator(hass: HomeAssistant, entry_id: str) -> HabrewCoordinator:
    entry = _entry(hass, entry_id)
    if entry.state is not ConfigEntryState.LOADED:
        raise HomeAssistantError(f"{entry.title} is not loaded")
    return entry.runtime_data


def _is_newer(latest: str | None, installed: str | None) -> bool:
    if not latest or not installed:
        return False
    try:
        return AwesomeVersion(latest) > AwesomeVersion(installed)
    except Exception:  # noqa: BLE001 - unparsable versions
        return latest != installed


def _serialize_devmode(coordinator: HabrewCoordinator | None) -> dict[str, Any] | None:
    info = coordinator.data.devmode if coordinator and coordinator.is_webos else None
    if info is None:
        return None
    expires = info.expires_at
    return {
        "remaining_hours": info.remaining_hours,
        "expires_at": expires.isoformat() if expires else None,
        "checked_at": info.checked_at,
        "last_extended": info.last_reset,
        "error": info.error,
    }


def _serialize_entry(hass: HomeAssistant, entry: HabrewConfigEntry, catalog: Catalog | None) -> dict[str, Any]:
    ent_reg = er.async_get(hass)
    spec = spec_for(entry.data)
    loaded = entry.state is ConfigEntryState.LOADED
    coordinator: HabrewCoordinator | None = entry.runtime_data if loaded else None
    data = coordinator.data if coordinator else None

    certificates = [
        {
            "id": sid,
            "title": s.title,
            "author_cn": s.data.get(CONF_AUTHOR_CN),
            "expires": s.data.get(CONF_EXPIRES),
            "cert_type": s.data.get(CONF_CERT_TYPE),
        }
        for sid, s in entry.subentries.items()
        if s.subentry_type == SUBENTRY_CERTIFICATE
    ]
    cert_titles = {c["id"]: c["title"] for c in certificates}

    apps = []
    managed_packages: dict[str, str] = {}
    for sid, sub in entry.subentries.items():
        if sub.subentry_type != SUBENTRY_APP:
            continue
        release = data.releases.get(sid) if data else None
        installed = coordinator.installed_app(sid) if coordinator else None
        if release:
            managed_packages[release.package_id] = sid
        apps.append(
            {
                "subentry_id": sid,
                "title": sub.title,
                "source": sub.data.get(CONF_SOURCE, SOURCE_GITHUB),
                "repo": sub.data.get(CONF_REPO),
                "asset_pattern": sub.data.get(CONF_ASSET_PATTERN),
                "catalog_key": sub.data.get(CONF_CATALOG_KEY),
                "certificate_id": sub.data.get(CONF_CERTIFICATE),
                "certificate": cert_titles.get(sub.data.get(CONF_CERTIFICATE, "")),
                "entity_id": ent_reg.async_get_entity_id("update", DOMAIN, f"{entry.entry_id}_{sid}"),
                "installed_version": installed.version if installed else None,
                "app_id": installed.app_id if installed else (release.app_id if release else None),
                "latest_version": release.version if release else None,
                "update_available": _is_newer(
                    release.version if release else None,
                    installed.version if installed else None,
                ),
                "package_id": release.package_id if release else None,
                "icon": release.icon if release else None,
                "release_url": release.release_url if release else None,
                "error": data.errors.get(sid) if data else None,
                "progress": coordinator.progress.get(sid) if coordinator else None,
            }
        )

    tv_apps = []
    if data:
        for app in sorted(data.apps.values(), key=lambda a: a.title.lower()):
            matches = catalog.by_package(app.package_id) if catalog else []
            preset = preset_for_package(spec.key, app.package_id)
            tv_apps.append(
                {
                    "preset": {"name": preset.name, "repo": preset.repo, "asset_pattern": preset.asset_pattern}
                    if preset
                    else None,
                    "package_id": app.package_id,
                    "app_id": app.app_id,
                    "title": app.title,
                    "version": app.version,
                    "origin": app.origin,
                    "managed_by": managed_packages.get(app.package_id),
                    "catalog": [
                        {
                            "key": m.key,
                            "name": m.name,
                            "group": m.group or m.name,
                            "variant": m.variant,
                            "version": m.version,
                        }
                        for m in matches
                    ],
                }
            )

    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "platform": spec.key,
        "os_name": spec.os_name,
        "manufacturer": spec.manufacturer,
        "needs_certificate": spec.needs_certificate,
        "default_pattern": spec.default_pattern,
        "devmode": _serialize_devmode(coordinator),
        "host": entry.data.get(CONF_HOST),
        "model": entry.data.get("model"),
        "platform_version": entry.data.get("platform_version"),
        "loaded": loaded,
        "reachable": bool(data and data.reachable),
        "last_update_success": bool(coordinator and coordinator.last_update_success),
        "wake_method": coordinator.wake_method if coordinator else "none",
        "certificates": certificates,
        "apps": apps,
        "tv_apps": tv_apps,
    }


async def _catalog_or_none(hass: HomeAssistant, platform: str) -> Catalog | None:
    client = get_catalog_client(hass, platform)
    try:
        return await client.get()
    except CatalogError as err:
        _LOGGER.debug("Catalog unavailable: %s", err)
        return client.cached


# ---------------------------------------------------------------------- commands


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "habrew/overview"})
@websocket_api.async_response
async def ws_overview(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    entries = hass.config_entries.async_entries(DOMAIN)
    catalogs = {key: await _catalog_or_none(hass, key) for key in {spec_for(e.data).key for e in entries}}
    connection.send_result(
        msg["id"], {"tvs": [_serialize_entry(hass, e, catalogs[spec_for(e.data).key]) for e in entries]}
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "habrew/catalog",
        vol.Optional("refresh", default=False): bool,
        vol.Optional("platform", default=PLATFORM_TIZEN): vol.In(list(SPECS)),
    }
)
@websocket_api.async_response
async def ws_catalog(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    spec = SPECS[msg["platform"]]
    try:
        catalog = await get_catalog_client(hass, spec.key).get(force=msg["refresh"])
    except CatalogError as err:
        connection.send_error(msg["id"], "catalog_unavailable", str(err))
        return
    connection.send_result(
        msg["id"],
        {
            "platform": spec.key,
            "credit": spec.catalog_credit,
            "credit_url": spec.catalog_url,
            "generated_at": catalog.generated_at,
            "categories": catalog.categories,
            "category_colors": catalog.category_colors,
            "entries": [e.as_dict() for e in catalog.entries.values()],
        },
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "habrew/app/add",
        vol.Required("entry_id"): str,
        vol.Optional("certificate"): str,
        vol.Required("source"): vol.In([SOURCE_CATALOG, SOURCE_GITHUB]),
        vol.Optional("catalog_key"): str,
        vol.Optional("name"): str,
        vol.Optional("repo"): str,
        vol.Optional("asset_pattern"): str,
        vol.Optional("include_prereleases", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_app_add(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    try:
        entry = _entry(hass, msg["entry_id"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "not_found", str(err))
        return
    spec = spec_for(entry.data)
    cert_id: str | None = None
    if spec.needs_certificate:
        cert = entry.subentries.get(msg.get("certificate", ""))
        if cert is None or cert.subentry_type != SUBENTRY_CERTIFICATE:
            connection.send_error(msg["id"], "invalid_certificate", "Unknown certificate")
            return
        cert_id = cert.subentry_id

    if msg["source"] == SOURCE_CATALOG:
        try:
            catalog = await get_catalog_client(hass, spec.key).get()
        except CatalogError as err:
            connection.send_error(msg["id"], "catalog_unavailable", str(err))
            return
        item = catalog.entries.get(msg.get("catalog_key", ""))
        if item is None:
            connection.send_error(msg["id"], "not_found", "App is not in the catalog")
            return
        siblings = [e for e in catalog.entries.values() if item.group and e.group == item.group]
        title = msg.get("name") or (
            f"{item.name} ({item.variant})" if len(siblings) > 1 and item.variant else item.name
        )
        unique_id = f"catalog|{item.key}"
        data = {
            CONF_SOURCE: SOURCE_CATALOG,
            CONF_CATALOG_KEY: item.key,
            CONF_CERTIFICATE: cert_id,
        }
    else:
        repo = (msg.get("repo") or "").strip().removeprefix("https://github.com/").strip("/")
        pattern = msg.get("asset_pattern") or spec.default_pattern
        if not REPO_RX.match(repo):
            connection.send_error(msg["id"], "invalid_repo", "Use the form owner/name")
            return
        try:
            re.compile(pattern)
            await GitHubClient(async_get_clientsession(hass), USER_AGENT).latest_asset(
                repo, pattern, msg["include_prereleases"]
            )
        except re.error:
            connection.send_error(msg["id"], "invalid_pattern", "Invalid regular expression")
            return
        except NoMatchingAsset as err:
            connection.send_error(msg["id"], "no_asset", str(err))
            return
        except GitHubError as err:
            connection.send_error(msg["id"], "github_error", str(err))
            return
        title = msg.get("name") or repo.split("/")[1]
        unique_id = f"{repo.lower()}|{pattern}"
        data = {
            CONF_SOURCE: SOURCE_GITHUB,
            CONF_PRESET: PRESET_CUSTOM,
            CONF_REPO: repo,
            CONF_ASSET_PATTERN: pattern,
            CONF_CERTIFICATE: cert_id,
            CONF_PRERELEASES: msg["include_prereleases"],
        }

    if any(s.unique_id == unique_id for s in entry.subentries.values()):
        connection.send_error(msg["id"], "already_configured", "This app is already added to this TV")
        return
    subentry = ConfigSubentry(
        data=MappingProxyType(data),
        subentry_type=SUBENTRY_APP,
        title=title,
        unique_id=unique_id,
    )
    hass.config_entries.async_add_subentry(entry, subentry)
    connection.send_result(msg["id"], {"subentry_id": subentry.subentry_id})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "habrew/app/remove",
        vol.Required("entry_id"): str,
        vol.Required("subentry_id"): str,
    }
)
@websocket_api.async_response
async def ws_app_remove(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    try:
        entry = _entry(hass, msg["entry_id"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "not_found", str(err))
        return
    sub = entry.subentries.get(msg["subentry_id"])
    if sub is None or sub.subentry_type != SUBENTRY_APP:
        connection.send_error(msg["id"], "not_found", "Unknown app")
        return
    hass.config_entries.async_remove_subentry(entry, sub.subentry_id)
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "habrew/app/install",
        vol.Required("entry_id"): str,
        vol.Required("subentry_id"): str,
    }
)
@websocket_api.async_response
async def ws_app_install(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    try:
        coordinator = _coordinator(hass, msg["entry_id"])
        await coordinator.async_install(msg["subentry_id"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], err.translation_key or "install_failed", str(err))
        return
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "habrew/refresh", vol.Required("entry_id"): str})
@websocket_api.async_response
async def ws_refresh(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    try:
        coordinator = _coordinator(hass, msg["entry_id"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "not_found", str(err))
        return
    await coordinator.async_refresh()
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "habrew/app/launch",
        vol.Required("entry_id"): str,
        vol.Required("app_id"): str,
    }
)
@websocket_api.async_response
async def ws_app_launch(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    try:
        coordinator = _coordinator(hass, msg["entry_id"])
        await coordinator.async_launch(msg["app_id"])
    except HomeAssistantError as err:
        connection.send_error(msg["id"], err.translation_key or "launch_failed", str(err))
        return
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "habrew/wake", vol.Required("entry_id"): str})
@websocket_api.async_response
async def ws_wake(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    try:
        coordinator = _coordinator(hass, msg["entry_id"])
        await coordinator.async_ensure_awake()
    except HomeAssistantError as err:
        connection.send_error(msg["id"], err.translation_key or "wake_failed", str(err))
        return
    await coordinator.async_refresh_tv()
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "habrew/devmode/extend", vol.Required("entry_id"): str})
@websocket_api.async_response
async def ws_devmode_extend(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    try:
        coordinator = _coordinator(hass, msg["entry_id"])
        if not coordinator.is_webos:
            raise HomeAssistantError("Only LG webOS TVs have a Developer Mode session")
        await coordinator.async_extend_devmode()
    except HomeAssistantError as err:
        connection.send_error(msg["id"], err.translation_key or "devmode_failed", str(err))
        return
    connection.send_result(msg["id"], _serialize_devmode(coordinator))
