"""Built-in application presets.

Kept intentionally small for now; a proper catalog (Apps2Samsung community packages,
webOS Homebrew repository) will replace this list.
"""

from __future__ import annotations

from dataclasses import dataclass

from .const import PLATFORM_TIZEN


@dataclass(frozen=True)
class AppPreset:
    """A known application and where its packages are published."""

    key: str
    name: str
    platform: str
    repo: str
    asset_pattern: str


PRESETS: dict[str, AppPreset] = {
    p.key: p
    for p in (
        AppPreset(
            key="nuvio",
            name="Nuvio TV",
            platform=PLATFORM_TIZEN,
            repo="NuvioMedia/NuvioTVSmart",
            asset_pattern=r"NuvioTV-Tizen-.*\.wgt$",
        ),
    )
}
