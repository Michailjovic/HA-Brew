"""App catalogs: the Apps2Samsung signed snapshot (Tizen) and the webOS Homebrew repository (LG).

Tizen: https://github.com/Apps2Samsung/tizen-community-packages/blob/main/docs/catalog.md
webOS: https://repo.webosbrew.org/api/apps.json
Both list every installable file with download URL and SHA-256, so the catalogs need no GitHub
API calls. Please credit the catalog when showing it to users.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

CATALOG_URL = "https://apps2samsung.com/catalog/resolved.json"
WEBOSBREW_URL = "https://repo.webosbrew.org/api/apps.json"
WEBOSBREW_PROVIDER = "webosbrew"
CATALOG_TTL = 30 * 60
COMMUNITY_PROVIDER = "tizen-community"

# Friendly names for snapshot providers that do not carry their own catalog metadata.
PROVIDER_NAMES = {
    "jellyfin-tizen-builds": "Jellyfin",
    "jellyfin-legacy": "Jellyfin (legacy)",
    "jellyfin-avplay": "Jellyfin AVPlay",
    "jellyfin-avplay-smarthub": "Jellyfin AVPlay SmartHub",
    "moonfin": "Moonfin",
    "litefin": "Litefin",
    "tizentube": "TizenTube",
}


class CatalogError(Exception):
    """Catalog could not be loaded."""


def asset_stem(name: str) -> str:
    """File name with version numbers removed, stable across releases."""
    return re.sub(r"\d+(?:[._-]\d+)*", "#", name).lower()


@dataclass
class CatalogEntry:
    """One installable package."""

    key: str
    provider: str
    file: str
    name: str
    description: str = ""
    category: str = "other"
    group: str | None = None
    variant: str = ""
    version: str = ""
    package_id: str = ""
    app_id: str = ""
    required_version: str = ""
    url: str = ""
    sha256: str = ""
    size: int = 0
    icon: str = ""
    repo: str = ""
    adult: bool = False
    flags: list[str] = field(default_factory=list)
    cert_level: str = ""
    preview_image: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Catalog:
    """Parsed snapshot."""

    entries: dict[str, CatalogEntry]
    categories: dict[str, str]
    category_colors: dict[str, str]
    generated_at: str = ""

    def by_package(self, package_id: str) -> list[CatalogEntry]:
        return [e for e in self.entries.values() if package_id and e.package_id == package_id]


def _digest(asset: dict[str, Any]) -> str:
    digest = asset.get("digest") or ""
    return digest.split(":", 1)[1] if digest.startswith("sha256:") else ""


def parse_snapshot(data: dict[str, Any]) -> Catalog:
    """Turn resolved.json into catalog entries (web apps only; .tpk is not supported yet)."""
    entries: dict[str, CatalogEntry] = {}
    categories: dict[str, str] = {}
    colors: dict[str, str] = {}
    for provider in data.get("providers", []):
        pid = provider.get("id", "")
        releases = provider.get("releases") or []
        if not pid or not releases:
            continue
        assets = {a["name"]: a for a in releases[0].get("assets", []) if a.get("name")}
        catalog = provider.get("catalog")
        if isinstance(catalog, dict):
            categories.update(catalog.get("categories") or {})
            colors.update(catalog.get("category_colors") or {})
            for app in catalog.get("apps", []):
                file = app.get("file", "")
                asset = assets.get(file)
                if not file.endswith(".wgt") or asset is None:
                    continue
                key = f"{pid}:{asset_stem(file)}"
                entries[key] = CatalogEntry(
                    key=key,
                    provider=pid,
                    file=file,
                    name=app.get("name", file),
                    description=app.get("description", ""),
                    category=app.get("category", "other"),
                    group=app.get("group"),
                    variant=app.get("variant", ""),
                    version=app.get("version") or asset.get("package_version", ""),
                    package_id=app.get("package_id") or asset.get("package_id", ""),
                    app_id=app.get("app_id") or asset.get("app_id", ""),
                    required_version=str(app.get("required_version") or asset.get("required_version") or ""),
                    url=asset.get("browser_download_url", ""),
                    sha256=_digest(asset),
                    size=asset.get("size", 0),
                    icon=asset.get("icon", ""),
                    repo=app.get("repo", ""),
                    adult=app.get("adult") is True,
                    flags=list(app.get("flags") or []),
                    cert_level=app.get("cert_level", ""),
                    preview_image=app.get("preview_image", ""),
                )
        else:
            name = PROVIDER_NAMES.get(pid, pid.replace("-", " ").title())
            repo = ""
            if m := re.match(r"https://(?:api\.)?github\.com/(?:repos/)?([^/]+/[^/]+)", releases[0].get("url", "")):
                repo = m.group(1)
            for file, asset in assets.items():
                if not file.endswith(".wgt"):
                    continue
                key = f"{pid}:{asset_stem(file)}"
                entries[key] = CatalogEntry(
                    key=key,
                    provider=pid,
                    file=file,
                    name=name,
                    category="media" if "fin" in pid else ("streaming" if pid == "tizentube" else "other"),
                    group=name,
                    variant=file.rsplit(".", 1)[0],
                    version=asset.get("package_version", ""),
                    package_id=asset.get("package_id", ""),
                    app_id=asset.get("app_id", ""),
                    required_version=str(asset.get("required_version") or ""),
                    url=asset.get("browser_download_url", ""),
                    sha256=_digest(asset),
                    size=asset.get("size", 0),
                    icon=asset.get("icon", ""),
                    repo=repo,
                )
    categories.setdefault("other", "Other")
    return Catalog(
        entries=entries, categories=categories, category_colors=colors, generated_at=data.get("generatedAt", "")
    )


def parse_webosbrew(data: dict[str, Any]) -> Catalog:
    """Turn the webOS Homebrew repository listing (single page) into catalog entries."""
    entries: dict[str, CatalogEntry] = {}
    for package in data.get("packages", []):
        manifest = package.get("manifest") or {}
        app_id = package.get("id") or manifest.get("id") or ""
        url = manifest.get("ipkUrl") or ""
        if not app_id or not url.startswith("https://"):
            continue
        repo = ""
        if m := re.match(r"https://github\.com/([^/]+/[^/#?]+)", manifest.get("sourceUrl") or ""):
            repo = m.group(1).removesuffix(".git")
        flags = []
        if manifest.get("rootRequired") is True:
            flags.append("root")
        if package.get("pool") == "non-free":
            flags.append("closed-source")
        key = f"{WEBOSBREW_PROVIDER}:{app_id}"
        entries[key] = CatalogEntry(
            key=key,
            provider=WEBOSBREW_PROVIDER,
            file=url.rsplit("/", 1)[-1],
            name=package.get("title") or manifest.get("title") or app_id,
            description=package.get("shortDescription") or manifest.get("appDescription") or "",
            category="native" if manifest.get("type") == "native" else "web",
            version=str(manifest.get("version") or ""),
            package_id=app_id,
            app_id=app_id,
            url=url,
            sha256=((manifest.get("ipkHash") or {}).get("sha256") or "").lower(),
            size=manifest.get("ipkSize") or 0,
            icon=package.get("iconUri") or "",
            repo=repo,
            flags=flags,
        )
    return Catalog(entries=entries, categories={"web": "Web apps", "native": "Native apps"}, category_colors={})


class CatalogClient:
    """Fetches and caches one catalog (shared by all TVs of a platform)."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        user_agent: str,
        url: str = CATALOG_URL,
        parser: Callable[[dict[str, Any]], Catalog] = parse_snapshot,
    ) -> None:
        self._session = session
        self._user_agent = user_agent
        self._url = url
        self._parser = parser
        self._catalog: Catalog | None = None
        self._fetched = 0.0
        self._etag = ""

    @property
    def cached(self) -> Catalog | None:
        return self._catalog

    async def get(self, force: bool = False) -> Catalog:
        if self._catalog and not force and time.monotonic() - self._fetched < CATALOG_TTL:
            return self._catalog
        headers = {"User-Agent": self._user_agent, "Accept": "application/json"}
        if self._etag and self._catalog:
            headers["If-None-Match"] = self._etag
        try:
            async with self._session.get(self._url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 304 and self._catalog:
                    self._fetched = time.monotonic()
                    return self._catalog
                if resp.status >= 400:
                    raise CatalogError(f"Catalog returned HTTP {resp.status}")
                data = await resp.json(content_type=None)
                self._etag = resp.headers.get("ETag", "")
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            if self._catalog:
                _LOGGER.warning("Catalog refresh failed, using cached copy: %s", err)
                return self._catalog
            raise CatalogError(f"Cannot load catalog: {err}") from err
        self._catalog = self._parser(data)
        self._fetched = time.monotonic()
        return self._catalog
