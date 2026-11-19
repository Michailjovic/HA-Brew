"""Built-in application presets (GitHub releases). Everything else comes from the catalogs."""

from __future__ import annotations

from dataclasses import dataclass

from .const import PLATFORM_TIZEN, PLATFORM_WEBOS


@dataclass(frozen=True)
class AppPreset:
    """A known application and where its packages are published."""

    key: str
    name: str
    platform: str
    repo: str
    asset_pattern: str
    package_ids: tuple[str, ...] = ()  # how the app shows up on the TV, to offer the preset for take-over


PRESETS: dict[str, AppPreset] = {
    p.key: p
    for p in (
        AppPreset(
            key="nuvio",
            name="Nuvio TV",
            platform=PLATFORM_TIZEN,
            repo="NuvioMedia/NuvioTVSmart",
            asset_pattern=r"NuvioTV-Tizen-.*\.wgt$",
            package_ids=("NuvioTV001",),
        ),
        AppPreset(
            key="nuvio_webos",
            name="Nuvio TV",
            platform=PLATFORM_WEBOS,
            repo="NuvioMedia/NuvioTVSmart",
            asset_pattern=r"NuvioTV-webOS-.*\.ipk$",
            package_ids=("space.nuvio.webos",),
        ),
        AppPreset(
            key="youtube_webos",
            name="YouTube AdFree",
            platform=PLATFORM_WEBOS,
            repo="webosbrew/youtube-webos",
            asset_pattern=r"youtube\.leanback\.v4_.*\.ipk$",
            package_ids=("youtube.leanback.v4",),
        ),
    )
}


def presets_for(platform: str) -> dict[str, AppPreset]:
    return {k: p for k, p in PRESETS.items() if p.platform == platform}


def preset_for_package(platform: str, package_id: str) -> AppPreset | None:
    return next((p for p in presets_for(platform).values() if package_id in p.package_ids), None)
