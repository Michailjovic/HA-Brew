"""End-to-end: entry setup, update entity state and installation against the mock TV."""

from __future__ import annotations

from types import MappingProxyType
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habrew import certificates
from custom_components.habrew.const import DOMAIN
from custom_components.habrew.drivers.tizen import TizenDevice
from custom_components.habrew.github import ReleaseAsset

from .conftest import DUID

ASSET = ReleaseAsset(
    "NuvioMedia/NuvioTVSmart",
    "1.4.2",
    "NuvioTV-Tizen-1.4.2.wgt",
    "https://x/a.wgt",
    1,
    "https://x/r",
    "Bug fixes",
    False,
)


@pytest.fixture
async def setup(hass: HomeAssistant, sdbd, tizenbrew_json, wgt):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="M70",
        unique_id=DUID,
        data={"host": "127.0.0.1", "platform": "tizen", "duid": DUID, "model": "QE55MOCK", "platform_version": "9.0"},
        subentries_data=[
            ConfigSubentryData(
                subentry_id="cert1",
                subentry_type="certificate",
                title="TizenBrew",
                unique_id="s1",
                data=MappingProxyType({"cert_type": "tizenbrew", "cert_id": "c1"}),
            ),
            ConfigSubentryData(
                subentry_id="app1",
                subentry_type="app",
                title="Nuvio TV",
                unique_id="nuvio",
                data=MappingProxyType(
                    {
                        "preset": "nuvio",
                        "repo": "NuvioMedia/NuvioTVSmart",
                        "asset_pattern": r"NuvioTV-Tizen-.*\.wgt$",
                        "certificate": "cert1",
                        "include_prereleases": False,
                    }
                ),
            ),
        ],
    )
    entry.add_to_hass(hass)
    await hass.async_add_executor_job(
        certificates.write_cert_files,
        certificates.cert_dir(hass, entry.entry_id, "c1"),
        {"tizenbrewInstallerConfig.json": tizenbrew_json},
    )
    with (
        patch("custom_components.habrew.coordinator.TizenDevice", lambda host: TizenDevice("127.0.0.1", sdbd.port)),
        patch("custom_components.habrew.coordinator.GitHubClient.latest_asset", AsyncMock(return_value=ASSET)),
        patch("custom_components.habrew.coordinator.GitHubClient.download", AsyncMock(return_value=wgt)) as dl,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry, dl


async def test_update_entity(hass: HomeAssistant, setup, sdbd, wgt) -> None:
    _entry, download = setup
    state = hass.states.get("update.m70_nuvio_tv")
    assert state is not None, hass.states.async_entity_ids()
    assert state.state == "on"
    assert state.attributes["installed_version"] == "1.3.6"
    assert state.attributes["latest_version"] == "1.4.2"
    assert state.attributes["tv_reachable"] is True
    assert state.attributes["certificate"] == "TizenBrew"
    assert download.await_count == 1

    await hass.services.async_call("update", "install", {"entity_id": "update.m70_nuvio_tv"}, blocking=True)
    await hass.async_block_till_done()
    assert sdbd.installs == ["NuvioTV001"]
    assert sdbd.pushed is not None and sdbd.pushed[:2] == b"PK"
    state = hass.states.get("update.m70_nuvio_tv")
    assert state.attributes["installed_version"] == "1.4.2"
    assert state.state == "off"
    assert download.await_count == 1  # cached package reused


async def test_install_author_mismatch(hass: HomeAssistant, setup, sdbd) -> None:
    sdbd.install_result = "author_mismatch"
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call("update", "install", {"entity_id": "update.m70_nuvio_tv"}, blocking=True)
    assert err.value.translation_key == "install_author_mismatch"
    assert hass.states.get("update.m70_nuvio_tv").attributes["in_progress"] is False


async def test_tv_offline_keeps_versions(hass: HomeAssistant, setup, sdbd) -> None:
    entry, _ = setup
    await sdbd.stop()
    coordinator = entry.runtime_data
    with patch.object(coordinator.device, "port", 1):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    state = hass.states.get("update.m70_nuvio_tv")
    assert state.attributes["tv_reachable"] is False
    assert state.attributes["installed_version"] == "1.3.6"


async def test_migrates_device_from_subentry(hass: HomeAssistant, sdbd, tizenbrew_json, wgt, caplog) -> None:
    """0.2.0 attached the TV device to an app subentry; setup moves it back to the entry."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="M70",
        unique_id=DUID,
        data={"host": "127.0.0.1", "platform": "tizen", "duid": DUID, "model": "QE55MOCK", "platform_version": "9.0"},
        subentries_data=[
            ConfigSubentryData(
                subentry_id="cert1",
                subentry_type="certificate",
                title="TizenBrew",
                unique_id="s1",
                data=MappingProxyType({"cert_type": "tizenbrew", "cert_id": "c1"}),
            ),
            ConfigSubentryData(
                subentry_id="app1",
                subentry_type="app",
                title="Nuvio TV",
                unique_id="nuvio",
                data=MappingProxyType(
                    {"repo": "NuvioMedia/NuvioTVSmart", "asset_pattern": r"\.wgt$", "certificate": "cert1"}
                ),
            ),
        ],
    )
    entry.add_to_hass(hass)
    dev_reg, ent_reg = dr.async_get(hass), er.async_get(hass)
    dev_reg.async_get_or_create(config_entry_id=entry.entry_id, config_subentry_id="app1", identifiers={(DOMAIN, DUID)})
    ent_reg.async_get_or_create(
        "update", DOMAIN, f"{entry.entry_id}_app1", config_entry=entry, config_subentry_id="app1"
    )
    ent_reg.async_get_or_create("update", DOMAIN, f"{entry.entry_id}_gone", config_entry=entry)
    await hass.async_add_executor_job(
        certificates.write_cert_files,
        certificates.cert_dir(hass, entry.entry_id, "c1"),
        {"tizenbrewInstallerConfig.json": tizenbrew_json},
    )
    with (
        patch("custom_components.habrew.coordinator.TizenDevice", lambda host: TizenDevice("127.0.0.1", sdbd.port)),
        patch("custom_components.habrew.coordinator.GitHubClient.latest_asset", AsyncMock(return_value=ASSET)),
        patch("custom_components.habrew.coordinator.GitHubClient.download", AsyncMock(return_value=wgt)),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    [device] = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
    assert device.config_subentry_id is None
    entities = [e for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id) if e.domain == "update"]
    assert [e.unique_id for e in entities] == [f"{entry.entry_id}_app1"]  # "_gone" removed
    assert entities[0].config_subentry_id is None and entities[0].device_id == device.id
    assert "assigns an existing device" not in caplog.text


async def test_release_identity(hass: HomeAssistant, setup, sdbd) -> None:
    """The TV reports another version string than the release: no endless update offer."""
    sdbd.install_version = "1.4.2-build7"
    await hass.services.async_call("update", "install", {"entity_id": "update.m70_nuvio_tv"}, blocking=True)
    await hass.async_block_till_done()
    state = hass.states.get("update.m70_nuvio_tv")
    assert state.attributes["installed_version"] == "1.4.2-build7"
    assert state.state == "off"


async def test_platform_precheck(hass: HomeAssistant, setup, sdbd) -> None:
    entry, _ = setup
    entry.runtime_data.data.releases["app1"].required_version = "10.0"
    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call("update", "install", {"entity_id": "update.m70_nuvio_tv"}, blocking=True)
    assert err.value.translation_key == "platform_too_old"
    assert sdbd.installs == [] and sdbd.pushed is None


async def test_uninstall(hass: HomeAssistant, setup, sdbd, hass_ws_client) -> None:
    entry, _ = setup
    client = await hass_ws_client(hass)

    sdbd.uninstall_allowed = False
    await client.send_json_auto_id(
        {"type": "habrew/app/uninstall", "entry_id": entry.entry_id, "app_id": "NuvioTV001", "subentry_id": "app1"}
    )
    res = await client.receive_json()
    assert not res["success"] and res["error"]["code"] == "uninstall_failed"
    assert "app1" in entry.subentries  # still managed

    sdbd.uninstall_allowed = True
    await client.send_json_auto_id(
        {"type": "habrew/app/uninstall", "entry_id": entry.entry_id, "app_id": "NuvioTV001", "subentry_id": "app1"}
    )
    res = await client.receive_json()
    assert res["success"], res
    await hass.async_block_till_done()
    assert "NuvioTV001" not in sdbd.apps
    assert "app1" not in entry.subentries


async def test_clean_reinstall(hass: HomeAssistant, setup, sdbd, hass_ws_client) -> None:
    """Way out of 'Author certificate not match': uninstall, then install fresh."""
    entry, _ = setup
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "habrew/app/uninstall",
            "entry_id": entry.entry_id,
            "app_id": "NuvioTV001",
            "subentry_id": "app1",
            "reinstall": True,
        }
    )
    res = await client.receive_json()
    assert res["success"], res
    assert sdbd.installs == ["NuvioTV001"]
    assert sdbd.apps["NuvioTV001"][2] == "1.4.2"
    assert "app1" in entry.subentries


async def test_diagnostics(hass: HomeAssistant, setup, sdbd) -> None:
    from custom_components.habrew.diagnostics import async_get_config_entry_diagnostics

    entry, _ = setup
    diag = await async_get_config_entry_diagnostics(hass, entry)
    text = str(diag)
    assert DUID not in text and "127.0.0.1" not in text
    assert diag["entry"]["data"]["duid"] == "**REDACTED**"
    assert diag["state"]["apps_on_tv"][0]["package_id"] == "NuvioTV001"
    assert diag["live"]["capability"]["platform_version"] == "9.0"
    assert diag["live"]["app_count"] == 1 and diag["live"]["vd_applist_sample"]
    assert diag["certificates"]["cert1"]["cert_id"] == "**REDACTED**"


async def test_launch_button(hass: HomeAssistant, setup, sdbd) -> None:
    state = hass.states.get("button.m70_launch_nuvio_tv")
    assert state is not None, [e for e in hass.states.async_entity_ids() if e.startswith("button.")]
    await hass.services.async_call("button", "press", {"entity_id": "button.m70_launch_nuvio_tv"}, blocking=True)
    assert sdbd.launched == ["NuvioTV001.NuvioTV"]


async def test_active_app_sensor(hass: HomeAssistant, setup) -> None:
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    from custom_components.habrew.drivers.base import DeviceConnectError
    from custom_components.habrew.drivers.tizen.rest import AppStatus

    entity = "sensor.m70_active_app"
    state = hass.states.get(entity)
    assert state is not None
    assert state.state == "off"  # nothing answers on 127.0.0.1:8001
    assert "Nuvio TV" in state.attributes["options"]

    async def visible(self, app_id):
        assert app_id == "NuvioTV001.NuvioTV"
        return AppStatus(app_id, True, True)

    with patch("custom_components.habrew.active_app.TizenRest.app_status", visible):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=20))
        await hass.async_block_till_done()
    state = hass.states.get(entity)
    assert state.state == "Nuvio TV"
    assert state.attributes["running"] == ["Nuvio TV"]
    assert state.attributes["app_id"] == "NuvioTV001.NuvioTV"

    async def background(self, app_id):
        return AppStatus(app_id, True, False)

    with patch("custom_components.habrew.active_app.TizenRest.app_status", background):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=40))
        await hass.async_block_till_done()
    assert hass.states.get(entity).state == "other"

    async def offline(self, app_id):
        raise DeviceConnectError("refused")

    with patch("custom_components.habrew.active_app.TizenRest.app_status", offline):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=60))
        await hass.async_block_till_done()
    assert hass.states.get(entity).state == "off"


async def test_rest_client(hass: HomeAssistant, aioclient_mock) -> None:
    import aiohttp
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from custom_components.habrew.drivers.base import DeviceConnectError
    from custom_components.habrew.drivers.tizen.rest import TizenRest

    aioclient_mock.get("http://tv:8001/api/v2/applications/a.b", exc=aiohttp.ClientError())
    aioclient_mock.get("https://tv:8002/api/v2/applications/a.b", text='{"id":"a.b","running":true,"visible":false}')
    aioclient_mock.get("https://tv:8002/api/v2/applications/c.d", status=404)
    rest = TizenRest(async_get_clientsession(hass), "tv")
    status = await rest.app_status("a.b")
    assert status is not None and status.running and not status.visible
    assert await rest.app_status("c.d") is None  # remembered port 8002, app unknown

    aioclient_mock.clear_requests()
    aioclient_mock.get("https://tv:8002/api/v2/applications/a.b", exc=TimeoutError())
    with pytest.raises(DeviceConnectError):
        await rest.app_status("a.b")
    with pytest.raises(ValueError):
        await rest.app_status("bad id;")
