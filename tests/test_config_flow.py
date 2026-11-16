"""Config flow and subentry flow tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habrew.const import DOMAIN
from custom_components.habrew.drivers.tizen import SdbConnectError, TizenDeviceInfo
from custom_components.habrew.github import NoMatchingAsset, ReleaseAsset

from .conftest import DUID, PASSWORD

FILE_ID = "a" * 32
FILE_ID2 = "b" * 32

INFO = TizenDeviceInfo(duid=DUID, model="QE55MOCK", platform_version="9.0")


@pytest.fixture(autouse=True)
def no_setup():
    with patch("custom_components.habrew.async_setup_entry", return_value=True):
        yield


async def test_user_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    with patch("custom_components.habrew.config_flow.TizenDevice.get_info", side_effect=SdbConnectError("x")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"name": "M70", "host": "192.168.1.91", "platform": "tizen"}
        )
    assert result["errors"] == {"base": "cannot_connect"}
    with patch("custom_components.habrew.config_flow.TizenDevice.get_info", return_value=INFO):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"name": "M70", "host": "192.168.1.91", "platform": "tizen"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == DUID
    assert result["data"]["model"] == "QE55MOCK"


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="M70",
        unique_id=DUID,
        data={"host": "127.0.0.1", "platform": "tizen", "duid": DUID, "model": "QE55MOCK", "platform_version": "9.0"},
    )
    entry.add_to_hass(hass)
    return entry


async def test_certificate_tizenbrew(hass: HomeAssistant, tizenbrew_json) -> None:
    entry = _entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "certificate"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "TizenBrew", "cert_type": "tizenbrew"}
    )
    assert result["step_id"] == "tizenbrew"
    with patch("custom_components.habrew.config_flow._read_upload", return_value=b"{}"):
        bad = await hass.config_entries.subentries.async_configure(result["flow_id"], {"cert_file": FILE_ID})
    assert bad["errors"] == {"base": "invalid_cert"}
    with patch("custom_components.habrew.config_flow._read_upload", return_value=tizenbrew_json):
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"cert_file": FILE_ID})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    [sub] = [s for s in entry.subentries.values() if s.subentry_type == "certificate"]
    assert sub.data["author_cn"] == "Test Author"
    cert_dir = hass.config.path(".storage", DOMAIN, entry.entry_id, "certs", sub.data["cert_id"])
    assert (await hass.async_add_executor_job(lambda: __import__("os").listdir(cert_dir))) == [
        "tizenbrewInstallerConfig.json"
    ]


async def test_certificate_wrong_device(hass: HomeAssistant, tizenbrew_json) -> None:
    entry = _entry(hass)
    hass.config_entries.async_update_entry(entry, data={**entry.data, "duid": "OTHERTV"})
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "certificate"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "TB", "cert_type": "tizenbrew"}
    )
    with patch("custom_components.habrew.config_flow._read_upload", return_value=tizenbrew_json):
        result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"cert_file": FILE_ID})
    assert result["errors"] == {"base": "wrong_device"}


async def test_certificate_p12(hass: HomeAssistant, p12_pair) -> None:
    entry = _entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "certificate"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "A2S", "cert_type": "p12"}
    )
    assert result["step_id"] == "p12"
    with patch("custom_components.habrew.config_flow._read_upload", side_effect=list(p12_pair)):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {"author_file": FILE_ID, "distributor_file": FILE_ID2, "password": PASSWORD}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


ASSET = ReleaseAsset(
    "NuvioMedia/NuvioTVSmart", "1.4.2", "NuvioTV-Tizen-1.4.2.wgt", "https://x/a.wgt", 1, "https://x/r", "notes", False
)


async def test_app_flow(hass: HomeAssistant, tizenbrew_json) -> None:
    entry = _entry(hass)
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "app"), context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "no_certificates"

    from types import MappingProxyType

    from homeassistant.config_entries import ConfigSubentry

    cert = ConfigSubentry(
        data=MappingProxyType({"cert_id": "abc"}), subentry_type="certificate", title="TizenBrew", unique_id="1"
    )
    hass.config_entries.async_add_subentry(entry, cert)

    result = await hass.config_entries.subentries.async_init((entry.entry_id, "app"), context={"source": SOURCE_USER})
    assert result["step_id"] == "user"
    with patch("custom_components.habrew.config_flow.GitHubClient.latest_asset", AsyncMock(return_value=ASSET)):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {"preset": "nuvio", "certificate": cert.subentry_id, "include_prereleases": False}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    [app] = [s for s in entry.subentries.values() if s.subentry_type == "app"]
    assert app.data["repo"] == "NuvioMedia/NuvioTVSmart" and app.data["certificate"] == cert.subentry_id

    # custom repository with no matching asset
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "app"), context={"source": SOURCE_USER})
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"preset": "custom", "certificate": cert.subentry_id, "include_prereleases": False}
    )
    assert result["step_id"] == "custom"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "X", "repo": "not a repo", "asset_pattern": r"\.wgt$"}
    )
    assert result["errors"] == {"repo": "invalid_repo"}
    with patch(
        "custom_components.habrew.config_flow.GitHubClient.latest_asset", AsyncMock(side_effect=NoMatchingAsset("x"))
    ):
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], {"name": "X", "repo": "https://github.com/a/b", "asset_pattern": r"\.wgt$"}
        )
    assert result["errors"] == {"base": "no_asset"}
