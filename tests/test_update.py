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
    entry, download = setup
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
    entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    assert [e.unique_id for e in entities] == [f"{entry.entry_id}_app1"]
    assert entities[0].config_subentry_id is None and entities[0].device_id == device.id
    assert "assigns an existing device" not in caplog.text
