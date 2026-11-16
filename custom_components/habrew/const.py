"""Constants for HA-Brew."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "habrew"
VERSION: Final = "0.2.1"
USER_AGENT: Final = f"HA-Brew/{VERSION}"

PLATFORM_TIZEN: Final = "tizen"

CONF_PLATFORM: Final = "platform"

SUBENTRY_CERTIFICATE: Final = "certificate"
SUBENTRY_APP: Final = "app"

# certificate subentry
CONF_CERT_TYPE: Final = "cert_type"
CERT_TYPE_TIZENBREW: Final = "tizenbrew"
CERT_TYPE_P12: Final = "p12"
CONF_CERT_ID: Final = "cert_id"
CONF_CERT_FILE: Final = "cert_file"
CONF_AUTHOR_FILE: Final = "author_file"
CONF_DISTRIBUTOR_FILE: Final = "distributor_file"
CONF_CERT_PASSWORD: Final = "password"
CONF_AUTHOR_CN: Final = "author_cn"
CONF_AUTHOR_SERIAL: Final = "author_serial"
CONF_EXPIRES: Final = "expires"

# app subentry
CONF_SOURCE: Final = "source"
SOURCE_GITHUB: Final = "github"
SOURCE_CATALOG: Final = "catalog"
CONF_CATALOG_KEY: Final = "catalog_key"
CONF_PRESET: Final = "preset"
PRESET_CUSTOM: Final = "custom"
CONF_REPO: Final = "repo"
CONF_ASSET_PATTERN: Final = "asset_pattern"
CONF_CERTIFICATE: Final = "certificate"
CONF_PRERELEASES: Final = "include_prereleases"

UPDATE_INTERVAL: Final = timedelta(minutes=30)
TV_TIMEOUT: Final = 6

STORAGE_VERSION: Final = 1

PANEL_URL: Final = "ha-brew"
PANEL_COMPONENT: Final = "ha-brew-panel"
STATIC_URL: Final = "/habrew_static"
