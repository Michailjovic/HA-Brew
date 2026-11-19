"""What differs between TV platforms, in one place (data only, no plugin machinery)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_PLATFORM, DOMAIN, PLATFORM_TIZEN, PLATFORM_WEBOS
from .drivers.base import PackageMetadata
from .drivers.tizen import TizenApp, read_wgt_metadata
from .drivers.webos import WebosApp, read_ipk_metadata


@dataclass(frozen=True)
class PlatformSpec:
    """Per-platform facts used by the coordinator, flows and panel."""

    key: str
    manufacturer: str
    os_name: str
    suffix: str  # package file extension
    default_pattern: str  # release asset regex for custom GitHub apps
    needs_certificate: bool
    app_cls: type
    read_metadata: Callable[[bytes], PackageMetadata]
    catalog_url: str
    catalog_credit: str


SPECS: dict[str, PlatformSpec] = {
    PLATFORM_TIZEN: PlatformSpec(
        key=PLATFORM_TIZEN,
        manufacturer="Samsung",
        os_name="Tizen",
        suffix=".wgt",
        default_pattern=r"\.wgt$",
        needs_certificate=True,
        app_cls=TizenApp,
        read_metadata=read_wgt_metadata,
        catalog_url="https://github.com/Apps2Samsung/tizen-community-packages",
        catalog_credit="Apps2Samsung community packages",
    ),
    PLATFORM_WEBOS: PlatformSpec(
        key=PLATFORM_WEBOS,
        manufacturer="LG",
        os_name="webOS",
        suffix=".ipk",
        default_pattern=r"\.ipk$",
        needs_certificate=False,
        app_cls=WebosApp,
        read_metadata=read_ipk_metadata,
        catalog_url="https://repo.webosbrew.org",
        catalog_credit="webOS Homebrew Project repository",
    ),
}


def spec_for(data: Mapping[str, Any]) -> PlatformSpec:
    """Spec of a config entry (entries from 0.2.x have no platform key)."""
    return SPECS.get(data.get(CONF_PLATFORM, PLATFORM_TIZEN), SPECS[PLATFORM_TIZEN])


def tv_device_info(entry: Any) -> DeviceInfo:
    """Device registry entry of a TV (shared by all entities of the config entry)."""
    spec = spec_for(entry.data)
    version = entry.data.get("platform_version")
    return DeviceInfo(
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        name=entry.title,
        manufacturer=spec.manufacturer,
        model=entry.data.get("model") or None,
        sw_version=f"{spec.os_name} {version}" if version else None,
    )
