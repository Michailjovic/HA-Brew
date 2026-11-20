"""Samsung: which of the managed apps is running / on screen (polled through the TV's REST API)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .drivers.base import DeviceError
from .drivers.tizen.rest import TizenRest

if TYPE_CHECKING:
    from .coordinator import HabrewCoordinator

_LOGGER = logging.getLogger(__name__)
ACTIVE_APP_INTERVAL = timedelta(seconds=15)


@dataclass
class ActiveApps:
    """Result of one poll."""

    reachable: bool = False
    visible: str | None = None  # app subentry id
    running: list[str] = field(default_factory=list)  # app subentry ids


class ActiveAppCoordinator(DataUpdateCoordinator[ActiveApps]):
    """Polls only while an entity listens (DataUpdateCoordinator default)."""

    def __init__(self, hass: HomeAssistant, main: HabrewCoordinator) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=main.config_entry,
            name=f"{DOMAIN} {main.config_entry.title} active app",
            update_interval=ACTIVE_APP_INTERVAL,
            always_update=False,
        )
        self.main = main
        self.rest = TizenRest(async_get_clientsession(hass, verify_ssl=False), main.config_entry.data[CONF_HOST])

    async def _async_update_data(self) -> ActiveApps:
        result = ActiveApps()
        for subentry_id in self.main.app_subentries:
            app_id = self.main.app_id(subentry_id)
            if not app_id:
                continue
            try:
                status = await self.rest.app_status(app_id)
            except DeviceError:
                return ActiveApps()  # TV off or REST disabled
            except ValueError:
                continue
            result.reachable = True
            if status is None:
                continue
            if status.running:
                result.running.append(subentry_id)
            if status.visible and result.visible is None:
                result.visible = subentry_id
        return result
