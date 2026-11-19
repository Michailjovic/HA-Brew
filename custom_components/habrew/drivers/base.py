"""Types shared by all TV drivers (no Home Assistant imports)."""

from __future__ import annotations

import re
from dataclasses import dataclass

# App and package ids end up in commands run on the TV; anything else is refused.
SAFE_ID_RX = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def check_id(value: str) -> str:
    """Return ``value`` if it is a plain app/package id, raise ValueError otherwise."""
    if not SAFE_ID_RX.match(value or ""):
        raise ValueError(f"Invalid app id {value!r}")
    return value


@dataclass(frozen=True)
class PackageMetadata:
    """Identifiers and version declared inside a package file."""

    version: str
    package_id: str
    app_id: str
    required_version: str
    name: str


class DeviceError(Exception):
    """Talking to the TV failed."""


class DeviceConnectError(DeviceError):
    """The TV is off, unreachable or refused the connection."""


class DeviceAuthError(DeviceError):
    """The TV rejected our credentials (webOS: Developer Mode key changed)."""


class InstallError(DeviceError):
    """The TV refused to install a package."""

    def __init__(self, message: str, code: str = "", reason: str = "", kind: str = "unknown") -> None:
        super().__init__(message)
        self.code = code
        self.reason = reason
        self.kind = kind  # author_mismatch | certificate | platform | unknown


class LaunchError(DeviceError):
    """The TV refused to start an app."""
