"""LG webOS: extend the Developer Mode session now."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import HabrewConfigEntry, HabrewCoordinator
from .platforms import tv_device_info

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: HabrewConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    if coordinator.is_webos:
        async_add_entities([DevModeExtendButton(coordinator)])


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
