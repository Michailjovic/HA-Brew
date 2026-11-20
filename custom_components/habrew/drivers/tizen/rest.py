"""Samsung TV local REST API (port 8001, or 8002 over TLS on some models): app status.

GET /api/v2/applications/<app id> answers {"id", "name", "running", "visible", "version"}.
It needs no pairing token, so it does not trigger the TV's "allow connection" prompt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import aiohttp

from ..base import DeviceConnectError, check_id

REST_BASES = ("http://{host}:8001", "https://{host}:8002")
REST_TIMEOUT = 3


@dataclass(frozen=True)
class AppStatus:
    """Whether an app runs and whether it is on screen."""

    app_id: str
    running: bool
    visible: bool


class TizenRest:
    """Minimal client; remembers which port answered."""

    def __init__(self, session: aiohttp.ClientSession, host: str) -> None:
        self._session = session
        self._host = host
        self._base: str | None = None

    async def app_status(self, app_id: str) -> AppStatus | None:
        """Status of one app, or None if the TV does not know it."""
        check_id(app_id)
        bases = [self._base] if self._base else [b.format(host=self._host) for b in REST_BASES]
        error: Exception | None = None
        for base in bases:
            try:
                async with self._session.get(
                    f"{base}/api/v2/applications/{app_id}",
                    ssl=False,
                    timeout=aiohttp.ClientTimeout(total=REST_TIMEOUT),
                ) as resp:
                    if resp.status == 404:
                        self._base = base
                        return None
                    if resp.status != 200:
                        raise DeviceConnectError(f"HTTP {resp.status}")
                    data = json.loads(await resp.text())
            except (aiohttp.ClientError, TimeoutError, ValueError, DeviceConnectError) as err:
                error = err
                continue
            self._base = base
            if not isinstance(data, dict):
                return None
            return AppStatus(app_id, bool(data.get("running")), bool(data.get("visible")))
        self._base = None
        raise DeviceConnectError(str(error) or "no answer")
