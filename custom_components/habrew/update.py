"""Update entities: one per configured app."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ASSET_PATTERN, CONF_CERTIFICATE, CONF_EXPIRES, CONF_REPO, DOMAIN, SUBENTRY_APP
from .coordinator import HabrewConfigEntry, HabrewCoordinator

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: HabrewConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type == SUBENTRY_APP:
            async_add_entities([HabrewAppUpdate(coordinator, subentry)], config_subentry_id=subentry_id)


class HabrewAppUpdate(CoordinatorEntity[HabrewCoordinator], UpdateEntity):
    """Newest GitHub release of an app vs. the version installed on the TV."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS | UpdateEntityFeature.RELEASE_NOTES
    )

    def __init__(self, coordinator: HabrewCoordinator, subentry: ConfigSubentry) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._subentry = subentry
        self._attr_unique_id = f"{entry.entry_id}_{subentry.subentry_id}"
        self._attr_name = subentry.title
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name=entry.title,
            manufacturer="Samsung",
            model=entry.data.get("model") or None,
            sw_version=f"Tizen {entry.data['platform_version']}" if entry.data.get("platform_version") else None,
        )

    @property
    def _release(self):
        return self.coordinator.data.releases.get(self._subentry.subentry_id)

    @property
    def installed_version(self) -> str | None:
        app = self.coordinator.installed_app(self._subentry.subentry_id)
        return app.version if app else None

    @property
    def latest_version(self) -> str | None:
        release = self._release
        return release.version if release else None

    @property
    def title(self) -> str | None:
        release = self._release
        return (release.name if release and release.name else None) or self._subentry.title

    @property
    def release_url(self) -> str | None:
        release = self._release
        return release.release_url if release else None

    @property
    def release_summary(self) -> str | None:
        release = self._release
        if not release or not release.release_notes:
            return None
        text = release.release_notes.strip()
        return text if len(text) <= 255 else text[:252] + "..."

    async def async_release_notes(self) -> str | None:
        release = self._release
        return release.release_notes if release else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        release = self._release
        cert = self.coordinator.config_entry.subentries.get(self._subentry.data.get(CONF_CERTIFICATE, ""))
        return {
            "tv_reachable": self.coordinator.data.reachable,
            "repository": self._subentry.data[CONF_REPO],
            "asset_pattern": self._subentry.data[CONF_ASSET_PATTERN],
            "release_tag": release.tag if release else None,
            "asset": release.asset_name if release else None,
            "package_id": release.package_id if release else None,
            "certificate": cert.title if cert else None,
            "certificate_expires": cert.data.get(CONF_EXPIRES) if cert else None,
            "last_error": self.coordinator.data.errors.get(self._subentry.subentry_id),
        }

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        self._attr_in_progress = True
        self._attr_update_percentage = 0
        self.async_write_ha_state()

        @callback
        def progress(pct: int) -> None:
            if pct != self._attr_update_percentage:
                self._attr_update_percentage = pct
                self.async_write_ha_state()

        try:
            await self.coordinator.async_install(self._subentry.subentry_id, progress)
        finally:
            self._attr_in_progress = False
            self._attr_update_percentage = None
            self.async_write_ha_state()
