"""LG webOS end to end: config flow, update entity, Dev Mode session, panel API."""

from __future__ import annotations

import hashlib
from types import MappingProxyType
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState, ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habrew.catalog import parse_webosbrew
from custom_components.habrew.const import DOMAIN
from custom_components.habrew.drivers.base import DeviceConnectError
from custom_components.habrew.drivers.webos import WebosDevice, WebosDeviceInfo
from custom_components.habrew.drivers.webos.devmode import DevModeError
from custom_components.habrew.github import ReleaseAsset

from .mock_webos import PASSPHRASE, SERIAL, MockWebosTv, make_ipk, make_key_pem

ASSET = ReleaseAsset(
    "NuvioMedia/NuvioTVSmart",
    "1.4.4",
    "NuvioTV-webOS-1.4.4.ipk",
    "https://x/nuvio.ipk",
    1,
    "https://x/r",
    "Bug fixes",
    False,
)
INFO = WebosDeviceInfo(serial=SERIAL, model="OLED55MOCK", sdk_version="11.2.0", firmware="43.21.96")


def webosbrew_listing(ipk: bytes) -> dict:
    return {
        "paging": {"page": 1, "maxPage": 1},
        "packages": [
            {
                "id": "youtube.leanback.v4",
                "title": "YouTube AdFree",
                "iconUri": "https://repo.webosbrew.org/apps/icons/youtube.leanback.v4.png",
                "manifest": {
                    "id": "youtube.leanback.v4",
                    "version": "0.5.3",
                    "type": "web",
                    "sourceUrl": "https://github.com/webosbrew/youtube-webos",
                    "rootRequired": False,
                    "ipkUrl": "https://x/yt.ipk",
                    "ipkHash": {"sha256": hashlib.sha256(ipk).hexdigest()},
                },
            },
            {
                "id": "org.webosbrew.hbchannel",
                "title": "Homebrew Channel",
                "manifest": {"id": "org.webosbrew.hbchannel", "version": "0.7.3", "ipkUrl": "https://x/hb.ipk"},
            },
            {
                "id": "org.example.rooty",
                "title": "Needs root",
                "manifest": {
                    "id": "org.example.rooty",
                    "version": "1.0",
                    "rootRequired": True,
                    "ipkUrl": "https://x/r.ipk",
                },
            },
            {"id": "broken", "title": "No URL", "manifest": {"id": "broken"}},
        ],
    }


def test_parse_webosbrew() -> None:
    catalog = parse_webosbrew(webosbrew_listing(b"x"))
    assert set(catalog.entries) == {
        "webosbrew:youtube.leanback.v4",
        "webosbrew:org.webosbrew.hbchannel",
        "webosbrew:org.example.rooty",
    }
    yt = catalog.entries["webosbrew:youtube.leanback.v4"]
    assert (yt.version, yt.package_id, yt.repo, yt.file) == (
        "0.5.3",
        "youtube.leanback.v4",
        "webosbrew/youtube-webos",
        "yt.ipk",
    )
    assert catalog.entries["webosbrew:org.example.rooty"].flags == ["root"]


# ---------------------------------------------------------------------- config flow


@pytest.fixture
def no_setup():
    with patch("custom_components.habrew.async_setup_entry", return_value=True):
        yield


async def test_config_flow_webos(hass: HomeAssistant, no_setup) -> None:
    pem = make_key_pem()
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"platform": "webos", "host": "192.168.1.53"}
    )
    assert result["step_id"] == "webos"

    with patch("custom_components.habrew.config_flow.fetch_key", side_effect=DeviceConnectError("off")):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"passphrase": PASSPHRASE})
    assert result["errors"] == {"base": "key_server"}

    with patch("custom_components.habrew.config_flow.fetch_key", return_value=pem):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"passphrase": "WRONG1"})
        assert result["errors"] == {"base": "invalid_passphrase"}
        with patch.object(WebosDevice, "get_info", side_effect=DeviceConnectError("port closed")):
            result = await hass.config_entries.flow.async_configure(result["flow_id"], {"passphrase": PASSPHRASE})
        assert result["errors"] == {"base": "cannot_connect_webos"}
        with patch.object(WebosDevice, "get_info", return_value=INFO):
            result = await hass.config_entries.flow.async_configure(result["flow_id"], {"passphrase": PASSPHRASE})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "OLED55MOCK"
    entry = result["result"]
    assert entry.unique_id == SERIAL
    assert entry.data["platform"] == "webos" and entry.data["ssh_key"] == pem and entry.data["passphrase"] == PASSPHRASE
    # LG TVs have no certificate subentries
    assert set(entry.supported_subentry_types) == {"app"}


async def test_reauth(hass: HomeAssistant, no_setup) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="LG",
        unique_id=SERIAL,
        data={"host": "192.168.1.53", "platform": "webos", "ssh_key": "old", "passphrase": "OLD123"},
    )
    entry.add_to_hass(hass)
    pem = make_key_pem()
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    with (
        patch("custom_components.habrew.config_flow.fetch_key", return_value=pem),
        patch.object(WebosDevice, "get_info", return_value=INFO),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"passphrase": PASSPHRASE})
    assert result["reason"] == "reauth_successful"
    assert entry.data["ssh_key"] == pem and entry.data["passphrase"] == PASSPHRASE


# ---------------------------------------------------------------------- running entry


@pytest.fixture
async def webos_tv(socket_enabled):
    tv = MockWebosTv()
    await tv.start()
    yield tv
    await tv.stop()


@pytest.fixture
async def lg(hass: HomeAssistant, webos_tv: MockWebosTv):
    ipk = make_ipk(version="1.4.4")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="LG",
        unique_id=SERIAL,
        data={
            "host": "127.0.0.1",
            "platform": "webos",
            "ssh_key": webos_tv.key_pem,
            "passphrase": PASSPHRASE,
            "serial": SERIAL,
            "model": "OLED55MOCK",
            "platform_version": "11.2.0",
        },
        subentries_data=[
            ConfigSubentryData(
                subentry_id="app1",
                subentry_type="app",
                title="Nuvio TV",
                unique_id="nuvio",
                data=MappingProxyType(
                    {
                        "source": "github",
                        "preset": "nuvio_webos",
                        "repo": "NuvioMedia/NuvioTVSmart",
                        "asset_pattern": r"NuvioTV-webOS-.*\.ipk$",
                        "certificate": None,
                        "include_prereleases": False,
                    }
                ),
            ),
        ],
    )
    entry.add_to_hass(hass)
    check = AsyncMock(return_value=999 * 3600)
    reset = AsyncMock()
    catalog = parse_webosbrew(webosbrew_listing(make_ipk("youtube.leanback.v4", "0.5.3", "YouTube AdFree")))
    with (
        patch(
            "custom_components.habrew.coordinator.WebosDevice",
            lambda host, key, passphrase: WebosDevice("127.0.0.1", key, passphrase, port=webos_tv.port),
        ),
        patch("custom_components.habrew.coordinator.GitHubClient.latest_asset", AsyncMock(return_value=ASSET)),
        patch("custom_components.habrew.github.GitHubClient.download", AsyncMock(return_value=ipk)) as download,
        patch("custom_components.habrew.catalog.CatalogClient.get", AsyncMock(return_value=catalog)),
        patch("custom_components.habrew.coordinator.check_session", check),
        patch("custom_components.habrew.coordinator.reset_session", reset),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry, check, reset, download


async def test_update_and_install(hass: HomeAssistant, lg, webos_tv: MockWebosTv) -> None:
    entry, *_ = lg
    state = hass.states.get("update.lg_nuvio_tv")
    assert state.state == "on"
    assert state.attributes["installed_version"] == "1.4.0"
    assert state.attributes["latest_version"] == "1.4.4"
    assert state.attributes["certificate"] is None

    from homeassistant.helpers import device_registry as dr

    [device] = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert device.manufacturer == "LG" and device.sw_version == "webOS 11.2.0"

    await hass.services.async_call("update", "install", {"entity_id": "update.lg_nuvio_tv"}, blocking=True)
    await hass.async_block_till_done()
    assert webos_tv.installed == ["space.nuvio.webos"]
    state = hass.states.get("update.lg_nuvio_tv")
    assert state.state == "off" and state.attributes["installed_version"] == "1.4.4"


async def test_devmode_session(hass: HomeAssistant, lg) -> None:
    entry, check, reset, _ = lg
    # first refresh: token read from the TV, session restarted and checked
    assert reset.await_count == 1 and check.await_count == 1
    state = hass.states.get("sensor.lg_developer_mode_remaining")
    assert state is not None, hass.states.async_entity_ids("sensor")
    assert float(state.state) == 999.0
    assert state.attributes["unit_of_measurement"] == "h"

    # second refresh within 24 h: only checked
    coordinator = entry.runtime_data
    await coordinator.async_refresh()
    assert reset.await_count == 1 and check.await_count == 2

    # the button restarts the session right away
    await hass.services.async_call("button", "press", {"entity_id": "button.lg_extend_developer_mode"}, blocking=True)
    assert reset.await_count == 2

    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, f"devmode_{entry.entry_id}") is None
    check.return_value = 50 * 3600
    await coordinator.async_refresh()
    issue = issues.async_get_issue(DOMAIN, f"devmode_{entry.entry_id}")
    assert issue is not None and issue.severity is ir.IssueSeverity.ERROR
    check.side_effect = DevModeError("LG refused the session: Check user session")
    await coordinator.async_refresh()
    assert "Check user session" in hass.states.get("sensor.lg_developer_mode_remaining").attributes["last_error"]
    check.side_effect = None
    check.return_value = 900 * 3600
    await coordinator.async_refresh()
    assert issues.async_get_issue(DOMAIN, f"devmode_{entry.entry_id}") is None


async def test_panel_api(hass: HomeAssistant, lg, hass_ws_client, webos_tv: MockWebosTv) -> None:
    entry, _check, reset, _download = lg
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "habrew/overview"})
    [tvd] = (await client.receive_json())["result"]["tvs"]
    assert tvd["platform"] == "webos" and tvd["os_name"] == "webOS" and tvd["needs_certificate"] is False
    assert tvd["default_pattern"] == r"\.ipk$"
    assert tvd["devmode"]["remaining_hours"] == 999.0
    hb = next(a for a in tvd["tv_apps"] if a["app_id"] == "org.webosbrew.hbchannel")
    assert hb["origin"] == "sideload" and hb["catalog"][0]["key"] == "webosbrew:org.webosbrew.hbchannel"

    await client.send_json_auto_id({"type": "habrew/catalog", "platform": "webos"})
    res = (await client.receive_json())["result"]
    assert res["platform"] == "webos" and len(res["entries"]) == 3

    # LG apps are added without a certificate
    await client.send_json_auto_id(
        {
            "type": "habrew/app/add",
            "entry_id": entry.entry_id,
            "source": "catalog",
            "catalog_key": "webosbrew:youtube.leanback.v4",
        }
    )
    res = await client.receive_json()
    assert res["success"], res
    await hass.async_block_till_done()

    await client.send_json_auto_id(
        {"type": "habrew/app/launch", "entry_id": entry.entry_id, "app_id": "space.nuvio.webos"}
    )
    assert (await client.receive_json())["success"]
    assert webos_tv.launched == ["space.nuvio.webos"]

    await client.send_json_auto_id({"type": "habrew/devmode/extend", "entry_id": entry.entry_id})
    res = await client.receive_json()
    assert res["success"] and res["result"]["remaining_hours"] == 999.0
    assert reset.await_count == 2


async def test_auth_failure_starts_reauth(hass: HomeAssistant, webos_tv: MockWebosTv) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="LG",
        unique_id=SERIAL,
        data={"host": "127.0.0.1", "platform": "webos", "ssh_key": make_key_pem(), "passphrase": PASSPHRASE},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.habrew.coordinator.WebosDevice",
        lambda host, key, passphrase: WebosDevice("127.0.0.1", key, passphrase, port=webos_tv.port),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_uninstall_and_diagnostics(hass: HomeAssistant, lg, hass_ws_client, webos_tv: MockWebosTv) -> None:
    from custom_components.habrew.diagnostics import async_get_config_entry_diagnostics

    entry, *_ = lg
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = str(diag)
    assert SERIAL not in text and "BEGIN RSA" not in text and PASSPHRASE not in text and "f" * 64 not in text
    assert diag["live"]["system_info"]["modelName"] == "OLED55MOCK"
    assert {a["id"] for a in diag["live"]["dev_apps"]} == {"org.webosbrew.hbchannel", "space.nuvio.webos"}

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "habrew/app/uninstall", "entry_id": entry.entry_id, "app_id": "org.webosbrew.hbchannel"}
    )
    res = await client.receive_json()
    assert res["success"], res
    assert "org.webosbrew.hbchannel" not in webos_tv.apps
    assert "app1" in entry.subentries
