"""Diagnostics download: what HA-Brew knows about a TV plus a live read-out, without secrets.

Meant for bug reports from TV models the developers do not own.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import (
    CONF_AUTHOR_SERIAL,
    CONF_CERT_ID,
    CONF_MAC,
    CONF_PASSPHRASE,
    CONF_SERIAL,
    CONF_SSH_KEY,
    SUBENTRY_APP,
    SUBENTRY_CERTIFICATE,
    VERSION,
)
from .coordinator import HabrewConfigEntry
from .drivers.base import DeviceError

# keys anywhere in the output whose values identify the user, the TV or unlock it
TO_REDACT = {
    "host",
    CONF_MAC,
    "broadcast_address",
    CONF_SSH_KEY,
    CONF_PASSPHRASE,
    CONF_SERIAL,
    "serialNumber",
    "duid",
    CONF_CERT_ID,
    CONF_AUTHOR_SERIAL,
    "password",
    "token",
    "devmode_token",
    "duids",
    "extra_duids",
}
LIVE_TIMEOUT = 45


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: HabrewConfigEntry) -> dict[str, Any]:
    coordinator = getattr(entry, "runtime_data", None)
    apps: dict[str, Any] = {}
    certificates: dict[str, Any] = {}
    for sid, sub in entry.subentries.items():
        if sub.subentry_type == SUBENTRY_APP:
            apps[sid] = {"title": sub.title, **dict(sub.data)}
        elif sub.subentry_type == SUBENTRY_CERTIFICATE:
            certificates[sid] = {"title": sub.title, **dict(sub.data)}

    out: dict[str, Any] = {
        "habrew_version": VERSION,
        "entry": {"title": entry.title, "data": dict(entry.data), "options": dict(entry.options)},
        "apps": apps,
        "certificates": certificates,
    }
    if coordinator is not None and coordinator.data is not None:
        data = coordinator.data
        out["state"] = {
            "platform": coordinator.spec.key,
            "reachable": data.reachable,
            "last_update_success": coordinator.last_update_success,
            "apps_on_tv": [asdict(a) | {"origin": a.origin} for a in data.apps.values()],
            "releases": {k: asdict(v) for k, v in data.releases.items()},
            "installed_releases": coordinator.installed_releases,
            "errors": data.errors,
            "devmode": asdict(data.devmode) if data.devmode else None,
        }
        out["live"] = await _live(coordinator)
    return async_redact_data(out, TO_REDACT)


async def _live(coordinator: Any) -> dict[str, Any]:
    """Ask the TV directly; a TV that is off just gives a note."""
    if coordinator.tv_lock.locked():
        return {"skipped": "an installation is running"}
    try:
        async with coordinator.tv_lock:
            return await asyncio.wait_for(coordinator.device.diagnostics(), LIVE_TIMEOUT)
    except (DeviceError, TimeoutError, OSError) as err:
        return {"error": f"{type(err).__name__}: {err}"}
