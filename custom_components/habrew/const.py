"""Constants for HA-Brew."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "habrew"
VERSION: Final = "0.4.1"
USER_AGENT: Final = f"HA-Brew/{VERSION}"

PLATFORM_TIZEN: Final = "tizen"
PLATFORM_WEBOS: Final = "webos"

CONF_PLATFORM: Final = "platform"

# webOS TV (Developer Mode SSH)
CONF_SSH_KEY: Final = "ssh_key"
CONF_PASSPHRASE: Final = "passphrase"
CONF_SERIAL: Final = "serial"
DEVMODE_RESET_INTERVAL: Final = timedelta(hours=24)
DEVMODE_WARN_HOURS: Final = 7 * 24

SUBENTRY_CERTIFICATE: Final = "certificate"
SUBENTRY_APP: Final = "app"

# certificate subentry
CONF_CERT_TYPE: Final = "cert_type"
CERT_TYPE_TIZENBREW: Final = "tizenbrew"
CERT_TYPE_P12: Final = "p12"
CERT_TYPE_SAMSUNG: Final = "samsung"  # created by HA-Brew through a Samsung account
CONF_PRIVILEGE: Final = "privilege"
CONF_EXTRA_DUIDS: Final = "extra_duids"
CONF_DUIDS: Final = "duids"
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

# TV options (wake-up)
CONF_WAKE_METHOD: Final = "wake_method"
WAKE_NONE: Final = "none"
WAKE_WOL: Final = "wol"
WAKE_ENTITY: Final = "entity"
CONF_MAC: Final = "mac"
CONF_BROADCAST: Final = "broadcast_address"
CONF_WAKE_ENTITY: Final = "wake_entity"
CONF_WAKE_TIMEOUT: Final = "wake_timeout"
DEFAULT_WAKE_TIMEOUT: Final = 60

UPDATE_INTERVAL: Final = timedelta(minutes=30)
TV_TIMEOUT: Final = 6

STORAGE_VERSION: Final = 1

PANEL_URL: Final = "ha-brew"
PANEL_COMPONENT: Final = "ha-brew-panel"
STATIC_URL: Final = "/habrew_static"
