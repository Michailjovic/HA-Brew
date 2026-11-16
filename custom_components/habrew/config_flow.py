"""Config flow: TVs, plus subentries for signing certificates and apps."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    FileSelector,
    FileSelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import certificates
from .const import (
    CERT_TYPE_P12,
    CERT_TYPE_TIZENBREW,
    CONF_ASSET_PATTERN,
    CONF_AUTHOR_CN,
    CONF_AUTHOR_FILE,
    CONF_AUTHOR_SERIAL,
    CONF_CERT_FILE,
    CONF_CERT_ID,
    CONF_CERT_PASSWORD,
    CONF_CERT_TYPE,
    CONF_CERTIFICATE,
    CONF_DISTRIBUTOR_FILE,
    CONF_EXPIRES,
    CONF_PLATFORM,
    CONF_PRERELEASES,
    CONF_PRESET,
    CONF_REPO,
    DOMAIN,
    PLATFORM_TIZEN,
    PRESET_CUSTOM,
    SUBENTRY_APP,
    SUBENTRY_CERTIFICATE,
    USER_AGENT,
)
from .drivers.tizen import CertificateError, SdbError, SigningProfile, TizenDevice, load_p12_pair, load_tizenbrew_config
from .github import GitHubClient, GitHubError, NoMatchingAsset
from .presets import PRESETS

_LOGGER = logging.getLogger(__name__)

REPO_RX = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class HabrewConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a TV."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            device = TizenDevice(host)
            try:
                info = await device.get_info()
            except (SdbError, TimeoutError, OSError) as err:
                _LOGGER.debug("Cannot connect to %s: %s", host, err)
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(info.duid or host)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_HOST: host,
                        CONF_PLATFORM: PLATFORM_TIZEN,
                        "duid": info.duid,
                        "model": info.model,
                        "platform_version": info.platform_version,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="Samsung TV"): str,
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PLATFORM, default=PLATFORM_TIZEN): SelectSelector(
                    SelectSelectorConfig(options=[PLATFORM_TIZEN], translation_key="platform")
                ),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=self.add_suggested_values_to_schema(schema, user_input), errors=errors
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_CERTIFICATE: CertificateSubentryFlow, SUBENTRY_APP: AppSubentryFlow}


# ---------------------------------------------------------------------- certificates


def _read_upload(hass: HomeAssistant, file_id: str) -> bytes:
    with process_uploaded_file(hass, file_id) as path:
        return Path(path).read_bytes()


def _profile_matches_duid(profile: SigningProfile, duid: str) -> bool:
    """Distributor certificates list the allowed TVs as URN:tizen:deviceid=<DUID>."""
    if not duid:
        return True
    der = profile.distributor.leaf_der
    if b"URN:tizen:deviceid=" not in der:
        return True  # no device restriction in this certificate
    return f"deviceid={duid}".encode() in der


class CertificateSubentryFlow(ConfigSubentryFlow):
    """Upload a Samsung signing certificate."""

    def __init__(self) -> None:
        self._name = ""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            self._name = user_input[CONF_NAME]
            if user_input[CONF_CERT_TYPE] == CERT_TYPE_TIZENBREW:
                return await self.async_step_tizenbrew()
            return await self.async_step_p12()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default="TizenBrew"): str,
                    vol.Required(CONF_CERT_TYPE, default=CERT_TYPE_TIZENBREW): SelectSelector(
                        SelectSelectorConfig(
                            options=[CERT_TYPE_TIZENBREW, CERT_TYPE_P12],
                            translation_key="cert_type",
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_tizenbrew(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                raw = await self.hass.async_add_executor_job(_read_upload, self.hass, user_input[CONF_CERT_FILE])
                profile = await self.hass.async_add_executor_job(load_tizenbrew_config, raw)
            except (CertificateError, ValueError, OSError) as err:
                _LOGGER.debug("Invalid TizenBrew certificate: %s", err)
                errors["base"] = "invalid_cert"
            else:
                if result := await self._async_store(profile, {"tizenbrewInstallerConfig.json": raw}, errors):
                    return result
        return self.async_show_form(
            step_id="tizenbrew",
            data_schema=vol.Schema({vol.Required(CONF_CERT_FILE): FileSelector(FileSelectorConfig(accept=".json"))}),
            errors=errors,
        )

    async def async_step_p12(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                author = await self.hass.async_add_executor_job(_read_upload, self.hass, user_input[CONF_AUTHOR_FILE])
                distributor = await self.hass.async_add_executor_job(
                    _read_upload, self.hass, user_input[CONF_DISTRIBUTOR_FILE]
                )
                password = user_input[CONF_CERT_PASSWORD]
                profile = await self.hass.async_add_executor_job(load_p12_pair, author, distributor, password)
            except (CertificateError, ValueError, OSError) as err:
                _LOGGER.debug("Invalid certificate pair: %s", err)
                errors["base"] = "invalid_cert"
            else:
                files = {"author.p12": author, "distributor.p12": distributor, "password.txt": password.encode()}
                if result := await self._async_store(profile, files, errors):
                    return result
        return self.async_show_form(
            step_id="p12",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AUTHOR_FILE): FileSelector(FileSelectorConfig(accept=".p12")),
                    vol.Required(CONF_DISTRIBUTOR_FILE): FileSelector(FileSelectorConfig(accept=".p12")),
                    vol.Required(CONF_CERT_PASSWORD): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                }
            ),
            errors=errors,
        )

    async def _async_store(
        self, profile: SigningProfile, files: dict[str, bytes], errors: dict[str, str]
    ) -> SubentryFlowResult | None:
        """Persist the certificate; returns None (with errors set) when it does not fit this TV."""
        entry = self._get_entry()
        if not _profile_matches_duid(profile, entry.data.get("duid", "")):
            errors["base"] = "wrong_device"
            return None
        cert_id = uuid.uuid4().hex
        await self.hass.async_add_executor_job(
            certificates.write_cert_files, certificates.cert_dir(self.hass, entry.entry_id, cert_id), files
        )
        expires = profile.author.not_after
        return self.async_create_entry(
            title=self._name,
            data={
                CONF_CERT_TYPE: CERT_TYPE_TIZENBREW if "tizenbrewInstallerConfig.json" in files else CERT_TYPE_P12,
                CONF_CERT_ID: cert_id,
                CONF_AUTHOR_CN: profile.author.common_name,
                CONF_AUTHOR_SERIAL: profile.author.serial,
                CONF_EXPIRES: expires.isoformat() if expires else None,
            },
            unique_id=profile.author.serial or None,
        )


# ---------------------------------------------------------------------- apps


class AppSubentryFlow(ConfigSubentryFlow):
    """Add an app that should be kept up to date on the TV."""

    def __init__(self) -> None:
        self._base: dict[str, Any] = {}

    def _certificate_options(self) -> list[SelectOptionDict]:
        entry = self._get_entry()
        return [
            SelectOptionDict(value=sid, label=s.title)
            for sid, s in entry.subentries.items()
            if s.subentry_type == SUBENTRY_CERTIFICATE
        ]

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        cert_options = self._certificate_options()
        if not cert_options:
            return self.async_abort(reason="no_certificates")
        errors: dict[str, str] = {}
        if user_input is not None:
            self._base = user_input
            if user_input[CONF_PRESET] == PRESET_CUSTOM:
                return await self.async_step_custom()
            preset = PRESETS[user_input[CONF_PRESET]]
            if result := await self._async_validate_and_create(preset.name, preset.repo, preset.asset_pattern, errors):
                return result

        preset_options = [SelectOptionDict(value=k, label=p.name) for k, p in PRESETS.items()]
        preset_options.append(SelectOptionDict(value=PRESET_CUSTOM, label="GitHub"))
        schema = vol.Schema(
            {
                vol.Required(CONF_PRESET, default=next(iter(PRESETS))): SelectSelector(
                    SelectSelectorConfig(options=preset_options, mode=SelectSelectorMode.LIST, translation_key="preset")
                ),
                vol.Required(CONF_CERTIFICATE, default=cert_options[0]["value"]): SelectSelector(
                    SelectSelectorConfig(options=cert_options)
                ),
                vol.Required(CONF_PRERELEASES, default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=self.add_suggested_values_to_schema(schema, user_input), errors=errors
        )

    async def async_step_custom(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            repo = user_input[CONF_REPO].strip().removeprefix("https://github.com/").strip("/")
            if not REPO_RX.match(repo):
                errors[CONF_REPO] = "invalid_repo"
            else:
                try:
                    re.compile(user_input[CONF_ASSET_PATTERN])
                except re.error:
                    errors[CONF_ASSET_PATTERN] = "invalid_pattern"
            if not errors and (
                result := await self._async_validate_and_create(
                    user_input[CONF_NAME], repo, user_input[CONF_ASSET_PATTERN], errors
                )
            ):
                return result
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_REPO): str,
                vol.Required(CONF_ASSET_PATTERN, default=r"\.wgt$"): str,
            }
        )
        return self.async_show_form(
            step_id="custom", data_schema=self.add_suggested_values_to_schema(schema, user_input), errors=errors
        )

    async def _async_validate_and_create(
        self, name: str, repo: str, pattern: str, errors: dict[str, str]
    ) -> SubentryFlowResult | None:
        """Check that the repository publishes a matching asset; returns None with errors set otherwise."""
        unique_id = f"{repo.lower()}|{pattern}"
        entry = self._get_entry()
        if any(s.unique_id == unique_id for s in entry.subentries.values()):
            return self.async_abort(reason="already_configured")
        client = GitHubClient(async_get_clientsession(self.hass), USER_AGENT)
        try:
            await client.latest_asset(repo, pattern, self._base.get(CONF_PRERELEASES, False))
        except NoMatchingAsset:
            errors["base"] = "no_asset"
            return None
        except GitHubError as err:
            _LOGGER.debug("GitHub validation failed: %s", err)
            errors["base"] = "github_error"
            return None
        return self.async_create_entry(
            title=name,
            data={
                CONF_PRESET: self._base.get(CONF_PRESET, PRESET_CUSTOM),
                CONF_REPO: repo,
                CONF_ASSET_PATTERN: pattern,
                CONF_CERTIFICATE: self._base[CONF_CERTIFICATE],
                CONF_PRERELEASES: self._base.get(CONF_PRERELEASES, False),
            },
            unique_id=unique_id,
        )
