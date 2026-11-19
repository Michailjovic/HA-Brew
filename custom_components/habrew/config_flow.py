"""Config flow: TVs, plus subentries for signing certificates and apps."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    FileSelector,
    FileSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import certificates, samsung_login
from .const import (
    CERT_TYPE_P12,
    CERT_TYPE_SAMSUNG,
    CERT_TYPE_TIZENBREW,
    CONF_ASSET_PATTERN,
    CONF_AUTHOR_CN,
    CONF_AUTHOR_FILE,
    CONF_AUTHOR_SERIAL,
    CONF_BROADCAST,
    CONF_CERT_FILE,
    CONF_CERT_ID,
    CONF_CERT_PASSWORD,
    CONF_CERT_TYPE,
    CONF_CERTIFICATE,
    CONF_DISTRIBUTOR_FILE,
    CONF_DUIDS,
    CONF_EXPIRES,
    CONF_EXTRA_DUIDS,
    CONF_MAC,
    CONF_PASSPHRASE,
    CONF_PLATFORM,
    CONF_PRERELEASES,
    CONF_PRESET,
    CONF_PRIVILEGE,
    CONF_REPO,
    CONF_SERIAL,
    CONF_SOURCE,
    CONF_SSH_KEY,
    CONF_WAKE_ENTITY,
    CONF_WAKE_METHOD,
    CONF_WAKE_TIMEOUT,
    DEFAULT_WAKE_TIMEOUT,
    DOMAIN,
    PLATFORM_TIZEN,
    PLATFORM_WEBOS,
    PRESET_CUSTOM,
    SOURCE_GITHUB,
    SUBENTRY_APP,
    SUBENTRY_CERTIFICATE,
    USER_AGENT,
    WAKE_ENTITY,
    WAKE_NONE,
    WAKE_WOL,
)
from .drivers.base import DeviceAuthError, DeviceConnectError, DeviceError
from .drivers.tizen import (
    CertificateError,
    SdbError,
    SigningProfile,
    TizenDevice,
    load_p12_pair,
    load_tizenbrew_config,
    samsung_cert,
)
from .drivers.webos import WebosDevice, WebosDeviceInfo, fetch_key, load_key
from .drivers.wol import normalize_mac
from .github import GitHubClient, GitHubError, NoMatchingAsset
from .platforms import spec_for
from .presets import PRESETS, presets_for

_LOGGER = logging.getLogger(__name__)

REPO_RX = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


async def _async_webos_pair(host: str, passphrase: str) -> tuple[str, WebosDeviceInfo]:
    """Download the Developer Mode key, decrypt it and log in once. Raises with an error key in args[0]."""
    try:
        pem = await fetch_key(host)
    except DeviceConnectError as err:
        _LOGGER.debug("Key Server of %s: %s", host, err)
        raise ValueError("key_server") from err
    try:
        load_key(pem, passphrase)
    except DeviceAuthError as err:
        raise ValueError("invalid_passphrase") from err
    try:
        info = await WebosDevice(host, pem, passphrase).get_info()
    except DeviceAuthError as err:
        _LOGGER.debug("Login to %s failed: %s", host, err)
        raise ValueError("invalid_passphrase") from err
    except (DeviceError, TimeoutError, OSError) as err:
        _LOGGER.debug("Cannot connect to %s: %s", host, err)
        raise ValueError("cannot_connect_webos") from err
    return pem, info


class HabrewConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a TV."""

    VERSION = 1

    def __init__(self) -> None:
        self._host = ""
        self._name = ""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and user_input.get(CONF_PLATFORM) == PLATFORM_WEBOS:
            self._host = user_input[CONF_HOST].strip()
            self._name = (user_input.get(CONF_NAME) or "").strip()
            return await self.async_step_webos()
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
                    title=(user_input.get(CONF_NAME) or "").strip() or info.model or "Samsung TV",
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
                vol.Required(CONF_PLATFORM, default=PLATFORM_TIZEN): SelectSelector(
                    SelectSelectorConfig(
                        options=[PLATFORM_TIZEN, PLATFORM_WEBOS],
                        translation_key="platform",
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(CONF_NAME): str,
                vol.Required(CONF_HOST): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_webos(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """LG: the Key Server publishes the SSH key, the passphrase on screen decrypts it."""
        errors: dict[str, str] = {}
        if user_input is not None:
            passphrase = user_input[CONF_PASSPHRASE].strip()
            try:
                pem, info = await _async_webos_pair(self._host, passphrase)
            except ValueError as err:
                errors["base"] = str(err)
            else:
                await self.async_set_unique_id(info.serial or self._host)
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: self._host, CONF_SSH_KEY: pem, CONF_PASSPHRASE: passphrase}
                )
                return self.async_create_entry(
                    title=self._name or info.model or "LG TV",
                    data={
                        CONF_HOST: self._host,
                        CONF_PLATFORM: PLATFORM_WEBOS,
                        CONF_SSH_KEY: pem,
                        CONF_PASSPHRASE: passphrase,
                        CONF_SERIAL: info.serial,
                        "model": info.model,
                        "platform_version": info.sdk_version,
                        "firmware": info.firmware,
                    },
                )
        return self.async_show_form(
            step_id="webos",
            data_schema=vol.Schema({vol.Required(CONF_PASSPHRASE): str}),
            description_placeholders={"host": self._host},
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The Developer Mode key changed (Dev Mode was reinstalled or turned off and on)."""
        self._host = entry_data[CONF_HOST]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            passphrase = user_input[CONF_PASSPHRASE].strip()
            try:
                pem, info = await _async_webos_pair(self._host, passphrase)
            except ValueError as err:
                errors["base"] = str(err)
            else:
                if info.serial and entry.unique_id and info.serial != entry.unique_id:
                    return self.async_abort(reason="wrong_tv")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_SSH_KEY: pem, CONF_PASSPHRASE: passphrase}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSPHRASE): str}),
            description_placeholders={"host": self._host, "name": entry.title},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HabrewOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        if not spec_for(config_entry.data).needs_certificate:
            return {SUBENTRY_APP: AppSubentryFlow}
        return {
            SUBENTRY_CERTIFICATE: CertificateSubentryFlow,
            SUBENTRY_APP: AppSubentryFlow,
        }


class HabrewOptionsFlow(OptionsFlow):
    """How to wake the TV before installing or launching apps."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            method = user_input[CONF_WAKE_METHOD]
            data: dict[str, Any] = {
                CONF_WAKE_METHOD: method,
                CONF_WAKE_TIMEOUT: int(user_input[CONF_WAKE_TIMEOUT]),
            }
            if method == WAKE_WOL:
                try:
                    data[CONF_MAC] = normalize_mac(user_input.get(CONF_MAC, ""))
                except ValueError:
                    errors[CONF_MAC] = "invalid_mac"
                data[CONF_BROADCAST] = (user_input.get(CONF_BROADCAST) or "255.255.255.255").strip()
            elif method == WAKE_ENTITY:
                if not user_input.get(CONF_WAKE_ENTITY):
                    errors[CONF_WAKE_ENTITY] = "entity_required"
                data[CONF_WAKE_ENTITY] = user_input.get(CONF_WAKE_ENTITY)
            if not errors:
                return self.async_create_entry(data=data)

        current = {**self.config_entry.options, **(user_input or {})}
        schema = vol.Schema(
            {
                vol.Required(CONF_WAKE_METHOD, default=WAKE_NONE): SelectSelector(
                    SelectSelectorConfig(
                        options=[WAKE_NONE, WAKE_WOL, WAKE_ENTITY],
                        translation_key="wake_method",
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(CONF_MAC): str,
                vol.Optional(CONF_BROADCAST): str,
                vol.Optional(CONF_WAKE_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain=["media_player", "switch", "button", "script", "remote"])
                ),
                vol.Required(CONF_WAKE_TIMEOUT, default=DEFAULT_WAKE_TIMEOUT): NumberSelector(
                    NumberSelectorConfig(
                        min=10,
                        max=300,
                        step=5,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, current),
            errors=errors,
        )


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
    """Create a Samsung signing certificate or upload an existing one."""

    def __init__(self) -> None:
        self._name = ""
        self._samsung: dict[str, Any] = {}
        self._login_token: str | None = None
        self._login_task: asyncio.Task | None = None
        self._session: samsung_cert.SamsungSession | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            self._name = (user_input.get(CONF_NAME) or "").strip()
            if user_input[CONF_CERT_TYPE] == CERT_TYPE_SAMSUNG:
                return await self.async_step_samsung()
            if user_input[CONF_CERT_TYPE] == CERT_TYPE_TIZENBREW:
                return await self.async_step_tizenbrew()
            return await self.async_step_p12()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CERT_TYPE, default=CERT_TYPE_SAMSUNG): SelectSelector(
                        SelectSelectorConfig(
                            options=[CERT_TYPE_SAMSUNG, CERT_TYPE_TIZENBREW, CERT_TYPE_P12],
                            translation_key="cert_type",
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Optional(CONF_NAME): str,
                }
            ),
        )

    # ------------------------------------------------------------------ new certificate (Samsung account)

    def _known_duids(self) -> list[str]:
        """DUIDs of every Samsung TV in HA-Brew: one certificate then works on all of them."""
        duids = [self._get_entry().data.get("duid", "")]
        duids += [
            e.data.get("duid", "")
            for e in self.hass.config_entries.async_entries(DOMAIN)
            if spec_for(e.data).needs_certificate
        ]
        return [d for d in dict.fromkeys(duids) if d]

    async def async_step_samsung(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errors: dict[str, str] = {}
        known = self._known_duids()
        if user_input is not None:
            extra = [d for d in re.split(r"[\s,;]+", user_input.get(CONF_EXTRA_DUIDS) or "") if d]
            duids = list(dict.fromkeys(known + extra))
            if any(not re.fullmatch(r"[A-Za-z0-9._-]{4,64}", d) for d in extra):
                errors[CONF_EXTRA_DUIDS] = "invalid_duid"
            elif not duids or len(duids) > samsung_cert.MAX_DUIDS:
                errors[CONF_EXTRA_DUIDS] = "too_many_duids" if duids else "no_duid"
            else:
                self._samsung = {
                    CONF_AUTHOR_CN: (user_input.get(CONF_AUTHOR_CN) or "").strip() or "HA-Brew",
                    CONF_PRIVILEGE: user_input[CONF_PRIVILEGE].capitalize(),  # Samsung expects Public / Partner
                    CONF_DUIDS: duids,
                }
                return await self.async_step_samsung_login()
        return self.async_show_form(
            step_id="samsung",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Optional(CONF_AUTHOR_CN, default="HA-Brew"): str,
                        vol.Required(CONF_PRIVILEGE, default="public"): SelectSelector(
                            SelectSelectorConfig(
                                options=[p.lower() for p in samsung_cert.PRIVILEGES],
                                translation_key="privilege",
                                mode=SelectSelectorMode.LIST,
                            )
                        ),
                        vol.Optional(CONF_EXTRA_DUIDS): str,
                    }
                ),
                user_input,
            ),
            description_placeholders={"duids": ", ".join(known) or "-", "account_url": "https://account.samsung.com"},
            errors=errors,
        )

    async def async_step_samsung_login(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Wait (up to 15 min) until the helper on the PC forwards the Samsung sign-in."""
        if self._login_task is None:
            self._login_token, pending = samsung_login.start_login(self.hass)
            self._login_task = self.hass.async_create_task(
                asyncio.wait_for(asyncio.shield(pending.future), samsung_login.LOGIN_TIMEOUT)
            )
        if not self._login_task.done():
            return self.async_show_progress(
                step_id="samsung_login",
                progress_action="samsung_login",
                progress_task=self._login_task,
                description_placeholders=samsung_login.commands(self.hass, self._login_token),
            )
        try:
            self._session = self._login_task.result()
        except (TimeoutError, asyncio.CancelledError):
            self._session = None
        samsung_login.finish_login(self.hass, self._login_token)
        return self.async_show_progress_done(next_step_id="samsung_issue" if self._session else "samsung_timeout")

    async def async_step_samsung_timeout(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return self.async_abort(reason="samsung_timeout")

    async def async_step_samsung_issue(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Create keys and CSRs, let Samsung sign them and store the result as a certificate pair."""
        assert self._session is not None
        opts = self._samsung
        try:
            author_key = await self.hass.async_add_executor_job(_existing_author_key, _stored_samsung_certs(self.hass))
            if author_key is None:
                author_key = await self.hass.async_add_executor_job(samsung_cert.generate_key)
            dist_key = await self.hass.async_add_executor_job(samsung_cert.generate_key)
            author_csr = await self.hass.async_add_executor_job(
                samsung_cert.author_csr, author_key, opts[CONF_AUTHOR_CN]
            )
            dist_csr = await self.hass.async_add_executor_job(
                samsung_cert.distributor_csr, dist_key, self._session.email, opts[CONF_DUIDS]
            )
            http = async_get_clientsession(self.hass)
            author_cert = await samsung_cert.issue_author(http, self._session, author_csr)
            dist_cert = await samsung_cert.issue_distributor(http, self._session, dist_csr, opts[CONF_PRIVILEGE])
            password = samsung_cert.new_password()
            files = await self.hass.async_add_executor_job(
                _build_p12_files, author_key, author_cert, dist_key, dist_cert, opts[CONF_PRIVILEGE], password
            )
            profile = await self.hass.async_add_executor_job(
                load_p12_pair, files["author.p12"], files["distributor.p12"], password
            )
        except samsung_cert.SamsungCertError as err:
            _LOGGER.warning("Creating a Samsung certificate failed: %s", err)
            return self.async_abort(
                reason=f"samsung_{err.kind}",
                description_placeholders={"error": str(err), "profile_url": samsung_cert.PROFILE_URL},
            )
        self._name = self._name or f"Samsung ({self._session.email or opts[CONF_AUTHOR_CN]})"
        errors: dict[str, str] = {}
        result = await self._async_store(
            profile,
            files,
            errors,
            cert_type=CERT_TYPE_SAMSUNG,
            extra={CONF_PRIVILEGE: opts[CONF_PRIVILEGE], CONF_DUIDS: opts[CONF_DUIDS]},
        )
        return result or self.async_abort(reason="samsung_failed", description_placeholders={"error": str(errors)})

    @callback
    def async_remove(self) -> None:
        """The dialog was closed: stop waiting for the sign-in."""
        if self._login_task and not self._login_task.done():
            self._login_task.cancel()
        if self._login_token:
            samsung_login.finish_login(self.hass, self._login_token)

    # ------------------------------------------------------------------ upload an existing certificate

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
                files = {
                    "author.p12": author,
                    "distributor.p12": distributor,
                    "password.txt": password.encode(),
                }
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
        self,
        profile: SigningProfile,
        files: dict[str, bytes],
        errors: dict[str, str],
        cert_type: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> SubentryFlowResult | None:
        """Persist the certificate; returns None (with errors set) when it does not fit this TV."""
        entry = self._get_entry()
        if not _profile_matches_duid(profile, entry.data.get("duid", "")):
            errors["base"] = "wrong_device"
            return None
        cert_id = uuid.uuid4().hex
        await self.hass.async_add_executor_job(
            certificates.write_cert_files,
            certificates.cert_dir(self.hass, entry.entry_id, cert_id),
            files,
        )
        expires = profile.author.not_after
        if cert_type is None:
            cert_type = CERT_TYPE_TIZENBREW if "tizenbrewInstallerConfig.json" in files else CERT_TYPE_P12
        default_name = {CERT_TYPE_TIZENBREW: "TizenBrew", CERT_TYPE_P12: profile.author.common_name or "Certificate"}
        return self.async_create_entry(
            title=self._name or default_name.get(cert_type, "Samsung"),
            data={
                **(extra or {}),
                CONF_CERT_TYPE: cert_type,
                CONF_CERT_ID: cert_id,
                CONF_AUTHOR_CN: profile.author.common_name,
                CONF_AUTHOR_SERIAL: profile.author.serial,
                CONF_EXPIRES: expires.isoformat() if expires else None,
            },
            unique_id=profile.author.serial or None,
        )


def _stored_samsung_certs(hass: HomeAssistant) -> list[Path]:
    """Folders of certificates HA-Brew created earlier, on any TV."""
    return [
        certificates.cert_dir(hass, entry.entry_id, sub.data[CONF_CERT_ID])
        for entry in hass.config_entries.async_entries(DOMAIN)
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_CERTIFICATE and sub.data.get(CONF_CERT_TYPE) == CERT_TYPE_SAMSUNG
    ]


def _existing_author_key(paths: list[Path]):
    """Author key of the first readable stored certificate, or None (executor)."""
    for path in paths:
        try:
            password = (path / "password.txt").read_text(encoding="utf-8").strip()
            return samsung_cert.author_key_from_p12((path / "author.p12").read_bytes(), password)
        except (OSError, ValueError, samsung_cert.SamsungCertError) as err:
            _LOGGER.debug("Stored author key not usable: %s", err)
    return None


def _build_p12_files(author_key, author_cert, dist_key, dist_cert, privilege: str, password: str) -> dict[str, bytes]:
    """author.p12 + distributor.p12 with Samsung's CAs, the same layout as an uploaded pair (executor)."""
    return {
        "author.p12": samsung_cert.to_p12(author_key, author_cert, samsung_cert.ca_certificate("author"), password),
        "distributor.p12": samsung_cert.to_p12(dist_key, dist_cert, samsung_cert.ca_certificate(privilege), password),
        "password.txt": password.encode(),
    }


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
        spec = spec_for(self._get_entry().data)
        cert_options = self._certificate_options()
        if spec.needs_certificate and not cert_options:
            return self.async_abort(reason="no_certificates")
        presets = presets_for(spec.key)
        errors: dict[str, str] = {}
        if user_input is not None:
            self._base = user_input
            if user_input[CONF_PRESET] == PRESET_CUSTOM:
                return await self.async_step_custom()
            preset = PRESETS[user_input[CONF_PRESET]]
            if result := await self._async_validate_and_create(preset.name, preset.repo, preset.asset_pattern, errors):
                return result

        preset_options = [SelectOptionDict(value=k, label=p.name) for k, p in presets.items()]
        preset_options.append(SelectOptionDict(value=PRESET_CUSTOM, label="GitHub"))
        fields: dict[Any, Any] = {
            vol.Required(CONF_PRESET, default=preset_options[0]["value"]): SelectSelector(
                SelectSelectorConfig(
                    options=preset_options,
                    mode=SelectSelectorMode.LIST,
                    translation_key="preset",
                )
            ),
        }
        if spec.needs_certificate:
            fields[vol.Required(CONF_CERTIFICATE, default=cert_options[0]["value"])] = SelectSelector(
                SelectSelectorConfig(options=cert_options)
            )
        fields[vol.Required(CONF_PRERELEASES, default=False)] = BooleanSelector()
        schema = vol.Schema(fields)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
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
                vol.Required(CONF_ASSET_PATTERN, default=spec_for(self._get_entry().data).default_pattern): str,
            }
        )
        return self.async_show_form(
            step_id="custom",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
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
                CONF_SOURCE: SOURCE_GITHUB,
                CONF_PRESET: self._base.get(CONF_PRESET, PRESET_CUSTOM),
                CONF_REPO: repo,
                CONF_ASSET_PATTERN: pattern,
                CONF_CERTIFICATE: self._base.get(CONF_CERTIFICATE),
                CONF_PRERELEASES: self._base.get(CONF_PRERELEASES, False),
            },
            unique_id=unique_id,
        )
