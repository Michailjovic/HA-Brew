"""Buttons: launch an app (every TV), extend Developer Mode (LG)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HabrewConfigEntry, HabrewCoordinator
from .platforms import tv_device_info

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: HabrewConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[ButtonEntity] = [LaunchButton(coordinator, sub) for sub in coordinator.app_subentries.values()]
    if coordinator.is_webos:
        entities.append(DevModeExtendButton(coordinator))
    async_add_entities(entities)


class LaunchButton(CoordinatorEntity[HabrewCoordinator], ButtonEntity):
    """Start the app on the TV (wakes the TV first if a wake-up method is configured)."""

    _attr_has_entity_name = True
    _attr_translation_key = "launch"
    _attr_icon = "mdi:play-box-outline"

    def __init__(self, coordinator: HabrewCoordinator, subentry: ConfigSubentry) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._subentry_id = subentry.subentry_id
        self._attr_unique_id = f"{entry.entry_id}_{subentry.subentry_id}_launch"
        self._attr_translation_placeholders = {"app": subentry.title}
        self._attr_device_info = tv_device_info(entry)

    async def async_press(self) -> None:
        app_id = self.coordinator.app_id(self._subentry_id)
        if not app_id:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="unknown_app")
        await self.coordinator.async_launch(app_id)
        if self.coordinator.active_apps is not None:
            await self.coordinator.active_apps.async_request_refresh()


class DevModeExtendButton(CoordinatorEntity[HabrewCoordinator], ButtonEntity):
    """Restart the 1000-hour Developer Mode session at LG."""

    _attr_has_entity_name = True
    _attr_translation_key = "devmode_extend"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:timer-refresh-outline"

    def __init__(self, coordinator: HabrewCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_devmode_extend"
        self._attr_device_info = tv_device_info(entry)

    async def async_press(self) -> None:
        await self.coordinator.async_extend_devmode()
