"""Small GitHub Releases client with ETag caching."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

API = "https://api.github.com"


class GitHubError(Exception):
    """GitHub request failed."""


class NoMatchingAsset(GitHubError):
    """The release exists but no asset matches the configured pattern."""


@dataclass(frozen=True)
class ReleaseAsset:
    """A release asset selected by the configured pattern."""

    repo: str
    tag: str
    name: str
    url: str
    size: int
    release_url: str
    release_notes: str
    prerelease: bool


class GitHubClient:
    """Fetches the newest release asset matching a regex."""

    def __init__(self, session: aiohttp.ClientSession, user_agent: str, token: str | None = None) -> None:
        self._session = session
        self._headers = {"Accept": "application/vnd.github+json", "User-Agent": user_agent}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
        self._etag_cache: dict[str, tuple[str, Any]] = {}

    async def _get_json(self, url: str) -> Any:
        headers = dict(self._headers)
        cached = self._etag_cache.get(url)
        if cached:
            headers["If-None-Match"] = cached[0]
        try:
            async with self._session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 304 and cached:
                    return cached[1]
                if resp.status == 404:
                    raise GitHubError(f"Repository or release not found: {url}")
                if resp.status == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
                    raise GitHubError("GitHub API rate limit exceeded")
                if resp.status >= 400:
                    raise GitHubError(f"GitHub returned HTTP {resp.status} for {url}")
                data = await resp.json()
                if etag := resp.headers.get("ETag"):
                    self._etag_cache[url] = (etag, data)
                return data
        except aiohttp.ClientError as err:
            raise GitHubError(f"Cannot reach GitHub: {err}") from err

    async def latest_asset(self, repo: str, pattern: str, include_prereleases: bool = False) -> ReleaseAsset:
        """Return the newest release (optionally including pre-releases) with a matching asset."""
        rx = re.compile(pattern)
        releases = await self._get_json(f"{API}/repos/{repo}/releases?per_page=10")
        if not isinstance(releases, list) or not releases:
            raise GitHubError(f"{repo} has no releases")
        for release in releases:
            if release.get("draft") or (release.get("prerelease") and not include_prereleases):
                continue
            for asset in release.get("assets", []):
                if rx.search(asset["name"]):
                    return ReleaseAsset(
                        repo=repo,
                        tag=release.get("tag_name", ""),
                        name=asset["name"],
                        url=asset["browser_download_url"],
                        size=asset.get("size", 0),
                        release_url=release.get("html_url", ""),
                        release_notes=release.get("body") or "",
                        prerelease=bool(release.get("prerelease")),
                    )
        raise NoMatchingAsset(f"No release asset in {repo} matches /{pattern}/")

    async def download(self, url: str, max_size: int = 200 * 1024 * 1024) -> bytes:
        headers = {"User-Agent": self._headers["User-Agent"], "Accept": "application/octet-stream"}
        try:
            async with self._session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=300)) as resp:
                if resp.status >= 400:
                    raise GitHubError(f"Download failed with HTTP {resp.status}")
                data = bytearray()
                async for chunk in resp.content.iter_chunked(256 * 1024):
                    data.extend(chunk)
                    if len(data) > max_size:
                        raise GitHubError("Asset is unexpectedly large")
                return bytes(data)
        except aiohttp.ClientError as err:
            raise GitHubError(f"Download failed: {err}") from err
