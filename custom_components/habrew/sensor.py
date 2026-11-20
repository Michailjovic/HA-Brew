"""Sensors: LG Developer Mode hours left, Samsung active app."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .active_app import ActiveAppCoordinator
from .coordinator import HabrewConfigEntry, HabrewCoordinator
from .platforms import tv_device_info

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: HabrewConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    if coordinator.is_webos:
        async_add_entities([DevModeRemainingSensor(coordinator)])
    elif coordinator.active_apps is not None:
        async_add_entities([ActiveAppSensor(coordinator.active_apps)])


class DevModeRemainingSensor(CoordinatorEntity[HabrewCoordinator], SensorEntity):
    """Apps installed in Developer Mode disappear when this reaches zero."""

    _attr_has_entity_name = True
    _attr_translation_key = "devmode_remaining"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_suggested_display_precision = 0
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:timer-sand"

    def __init__(self, coordinator: HabrewCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_devmode_remaining"
        self._attr_device_info = tv_device_info(entry)

    @property
    def native_value(self) -> float | None:
        info = self.coordinator.data.devmode
        return info.remaining_hours if info else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        info = self.coordinator.data.devmode
        expires = info.expires_at if info else None
        return {
            "expires_at": expires.isoformat() if expires else None,
            "checked_at": info.checked_at if info else None,
            "last_extended": info.last_reset if info else None,
            "last_error": info.error if info else None,
        }


STATE_OFF = "off"
STATE_OTHER = "other"


class ActiveAppSensor(CoordinatorEntity[ActiveAppCoordinator], SensorEntity):
    """Which managed app is on screen: its name, "other" (something else) or "off" (TV not answering)."""

    _attr_has_entity_name = True
    _attr_translation_key = "active_app"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_icon = "mdi:application-outline"

    def __init__(self, coordinator: ActiveAppCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_active_app"
        self._attr_device_info = tv_device_info(entry)
        self._titles = {sid: sub.title for sid, sub in coordinator.main.app_subentries.items()}
        self._attr_options = [STATE_OFF, STATE_OTHER, *dict.fromkeys(self._titles.values())]

    @property
    def native_value(self) -> str:
        data = self.coordinator.data
        if data is None or not data.reachable:
            return STATE_OFF
        return self._titles.get(data.visible or "", STATE_OTHER)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        running = data.running if data else []
        visible = data.visible if data else None
        return {
            "running": [self._titles[s] for s in running if s in self._titles],
            "app_id": self.coordinator.main.app_id(visible) if visible else None,
        }
