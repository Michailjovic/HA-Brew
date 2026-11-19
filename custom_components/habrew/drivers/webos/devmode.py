"""Developer Mode session at LG (1000 hours; apps installed in Dev Mode are removed when it runs out).

Check and reset only need the session token from the TV, so they also work while the TV is off.
"""

from __future__ import annotations

import re

import aiohttp

CHECK_URL = "https://developer.lge.com/secure/CheckDevModeSession.dev"
RESET_URL = "https://developer.lge.com/secure/ResetDevModeSession.dev"
SESSION_HOURS = 1000

_REMAINING_RX = re.compile(r"^(\d+):(\d{2}):(\d{2})$")


class DevModeError(Exception):
    """LG refused the request (expired or invalid session) or could not be reached."""


def parse_remaining(text: str) -> int:
    """``"992:14:20"`` → seconds."""
    match = _REMAINING_RX.match(text.strip())
    if not match:
        raise DevModeError(f"Unexpected answer from LG: {text!r}")
    hours, minutes, seconds = (int(x) for x in match.groups())
    return hours * 3600 + minutes * 60 + seconds


async def _call(session: aiohttp.ClientSession, url: str, token: str, user_agent: str) -> dict:
    try:
        async with session.get(
            url,
            params={"sessionToken": token},
            headers={"User-Agent": user_agent},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status >= 400:
                raise DevModeError(f"LG returned HTTP {resp.status}")
            data = await resp.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise DevModeError(f"LG developer site not reachable: {err}") from err
    if not isinstance(data, dict) or data.get("result") != "success":
        message = data.get("errorMsg") if isinstance(data, dict) else data
        raise DevModeError(f"LG refused the session: {message}")
    return data


async def check_session(session: aiohttp.ClientSession, token: str, user_agent: str) -> int:
    """Seconds left in the Developer Mode session."""
    data = await _call(session, CHECK_URL, token, user_agent)
    return parse_remaining(str(data.get("errorMsg", "")))


async def reset_session(session: aiohttp.ClientSession, token: str, user_agent: str) -> None:
    """Restart the session at LG (back to 1000 hours)."""
    await _call(session, RESET_URL, token, user_agent)
