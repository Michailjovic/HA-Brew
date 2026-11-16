"""Storage of signing certificates.

Files live in ``<config>/.storage/habrew/<entry_id>/certs/<cert_id>/`` (never in /config/www or
any web-served folder). Password and private keys therefore stay in Home Assistant's private
storage, the same place config entries keep their secrets.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .drivers.tizen import SigningProfile
from .drivers.tizen.signing import load_profile_dir


def entry_dir(hass: HomeAssistant, entry_id: str) -> Path:
    return Path(hass.config.path(".storage", DOMAIN, entry_id))


def cert_dir(hass: HomeAssistant, entry_id: str, cert_id: str) -> Path:
    return entry_dir(hass, entry_id) / "certs" / cert_id


def cache_dir(hass: HomeAssistant, entry_id: str) -> Path:
    return entry_dir(hass, entry_id) / "cache"


def write_cert_files(path: Path, files: dict[str, bytes]) -> None:
    """Write certificate files with owner-only permissions (executor)."""
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    for name, data in files.items():
        target = path / name
        target.write_bytes(data)
        target.chmod(0o600)


def load_profile(hass: HomeAssistant, entry_id: str, cert_id: str) -> SigningProfile:
    """Load a stored signing profile (executor)."""
    return load_profile_dir(cert_dir(hass, entry_id, cert_id))


def remove_orphans(hass: HomeAssistant, entry_id: str, valid_cert_ids: set[str]) -> None:
    """Delete certificate folders of removed certificate subentries (executor)."""
    root = entry_dir(hass, entry_id) / "certs"
    if not root.is_dir():
        return
    for child in root.iterdir():
        if child.is_dir() and child.name not in valid_cert_ids:
            shutil.rmtree(child, ignore_errors=True)


def remove_entry_files(hass: HomeAssistant, entry_id: str) -> None:
    """Delete everything stored for a config entry (executor)."""
    shutil.rmtree(entry_dir(hass, entry_id), ignore_errors=True)
