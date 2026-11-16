"""HA-Brew: install and update homebrew apps on smart TVs from Home Assistant."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from . import certificates
from .const import CONF_CERT_ID, SUBENTRY_CERTIFICATE
from .coordinator import HabrewConfigEntry, HabrewCoordinator

PLATFORMS: list[Platform] = [Platform.UPDATE]


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
