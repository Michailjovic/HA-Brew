"""HA-Brew: install and update homebrew apps on smart TVs from Home Assistant."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import translation
from homeassistant.helpers.typing import ConfigType

from . import certificates, websocket_api
from .const import CONF_CERT_ID, DOMAIN, PANEL_COMPONENT, PANEL_URL, STATIC_URL, SUBENTRY_CERTIFICATE, VERSION
from .coordinator import HabrewConfigEntry, HabrewCoordinator

PLATFORMS: list[Platform] = [Platform.UPDATE]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the WebSocket API and the sidebar panel."""
    websocket_api.async_register(hass)
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

    coordinator = HabrewCoordinator(hass, entry)
    await coordinator.async_load()
    entry.runtime_data = coordinator
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: HabrewConfigEntry) -> None:
    """Reload when apps or certificates are added/removed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HabrewConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: HabrewConfigEntry) -> None:
    """Delete stored certificates and cached packages."""
    await hass.async_add_executor_job(certificates.remove_entry_files, hass, entry.entry_id)
