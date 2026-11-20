"""HA-Brew: install and update homebrew apps on smart TVs from Home Assistant."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import translation
from homeassistant.helpers.typing import ConfigType

from . import certificates, samsung_login, websocket_api
from .active_app import ActiveAppCoordinator
from .const import (
    CONF_CERT_ID,
    DOMAIN,
    PANEL_COMPONENT,
    PANEL_URL,
    STATIC_URL,
    SUBENTRY_APP,
    SUBENTRY_CERTIFICATE,
    VERSION,
)
from .coordinator import HabrewConfigEntry, HabrewCoordinator
from .platforms import tv_device_info

PLATFORMS: list[Platform] = [Platform.UPDATE, Platform.SENSOR, Platform.BUTTON]
# unique_id suffixes of TV-level entities (everything else is an app subentry id)
TV_ENTITY_SUFFIXES = {"devmode_remaining", "devmode_extend", "active_app"}
LAUNCH_SUFFIX = "_launch"
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the WebSocket API, the Samsung sign-in relay and the sidebar panel."""
    websocket_api.async_register(hass)
    samsung_login.async_register(hass)
    await translation.async_load_integrations(hass, {DOMAIN})
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(Path(__file__).parent / "frontend"), cache_headers=False)]
    )
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL,
        webcomponent_name=PANEL_COMPONENT,
        sidebar_title="HA-Brew",
        sidebar_icon="mdi:television-classic",
        module_url=f"{STATIC_URL}/ha-brew-panel.js?v={VERSION}",
        require_admin=True,
        config={},
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HabrewConfigEntry) -> bool:
    """Set up one TV."""
    valid_certs = {s.data[CONF_CERT_ID] for s in entry.subentries.values() if s.subentry_type == SUBENTRY_CERTIFICATE}
    await hass.async_add_executor_job(certificates.remove_orphans, hass, entry.entry_id, valid_certs)

    _async_cleanup_registries(hass, entry)

    coordinator = HabrewCoordinator(hass, entry)
    await coordinator.async_load()
    entry.runtime_data = coordinator
    await coordinator.async_config_entry_first_refresh()
    if not coordinator.is_webos:
        coordinator.active_apps = ActiveAppCoordinator(hass, coordinator)
        await coordinator.active_apps.async_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


def _async_cleanup_registries(hass: HomeAssistant, entry: HabrewConfigEntry) -> None:
    """Keep the TV device and app entities on the config entry itself (not on subentries).

    Apps are subentries, but they all share one device (the TV); Home Assistant does not allow a device
    to belong to several subentries. Entities of removed apps are deleted here as well.
    """
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    app_ids = {sid for sid, s in entry.subentries.items() if s.subentry_type == SUBENTRY_APP} | TV_ENTITY_SUFFIXES
    for ent in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if ent.unique_id.removeprefix(f"{entry.entry_id}_").removesuffix(LAUNCH_SUFFIX) not in app_ids:
            ent_reg.async_remove(ent.entity_id)
        elif ent.config_subentry_id is not None:
            ent_reg.async_update_entity(ent.entity_id, config_subentry_id=None)
    device = dev_reg.async_get_or_create(config_entry_id=entry.entry_id, **tv_device_info(entry))
    if hasattr(device, "config_subentry_id"):
        # HA 2026.x: a device has a single config entry / subentry
        if device.config_subentry_id is not None:
            dev_reg.async_update_device(device.id, new_config_subentry_id=None)
    else:  # older HA: device links several (entry, subentry) pairs
        for sub_id in device.config_entries_subentries.get(entry.entry_id, set()) - {None}:
            dev_reg.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id, remove_config_subentry_id=sub_id
            )


async def _async_reload(hass: HomeAssistant, entry: HabrewConfigEntry) -> None:
    """Reload when apps or certificates are added/removed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HabrewConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_flush()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: HabrewConfigEntry) -> None:
    """Delete stored certificates, cached packages and repair issues."""
    ir.async_delete_issue(hass, DOMAIN, f"devmode_{entry.entry_id}")
    await hass.async_add_executor_job(certificates.remove_entry_files, hass, entry.entry_id)
