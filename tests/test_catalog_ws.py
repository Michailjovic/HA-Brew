"""Catalog parsing, WebSocket API and panel registration."""

from __future__ import annotations

import hashlib
from types import MappingProxyType
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habrew import certificates
from custom_components.habrew.catalog import asset_stem, parse_snapshot
from custom_components.habrew.const import DOMAIN
from custom_components.habrew.drivers.tizen import TizenDevice

from .conftest import DUID, make_wgt


def snapshot(wgt: bytes) -> dict:
    digest = "sha256:" + hashlib.sha256(wgt).hexdigest()
    return {
        "generatedAt": "2026-11-16T06:00:00Z",
        "providers": [
            {
                "id": "tizen-community",
                "releases": [
                    {
                        "assets": [
                            {
                                "name": "NuvioTV-Official.wgt",
                                "browser_download_url": "https://x/nuvio.wgt",
                                "size": len(wgt),
                                "digest": digest,
                                "package_version": "1.4.2",
                                "package_id": "NuvioTV001",
                                "app_id": "NuvioTV001.NuvioTV",
                                "icon": "https://x/i.png",
                            },
                            {"name": "Native.tpk", "browser_download_url": "https://x/n.tpk"},
                        ]
                    }
                ],
                "catalog": {
                    "categories": {"streaming": "Streaming", "other": "Other"},
                    "apps": [
                        {
                            "file": "NuvioTV-Official.wgt",
                            "name": "Nuvio",
                            "description": "TV-first UI",
                            "category": "streaming",
                            "group": "Nuvio",
                            "variant": "Official web app",
                            "repo": "NuvioMedia/NuvioTVSmart",
                            "version": "1.4.2",
                            "package_id": "NuvioTV001",
                            "app_id": "NuvioTV001.NuvioTV",
                            "required_version": "2.3",
                        },
                        {"file": "Native.tpk", "name": "Native", "category": "other", "repo": "a/b"},
                    ],
                },
            },
            {
                "id": "tizentube",
                "releases": [
                    {
                        "url": "https://github.com/reisxd/TizenTube/releases/tag/v2.1.1",
                        "assets": [
                            {
                                "name": "TizenTubeCobalt.wgt",
                                "browser_download_url": "https://x/tt.wgt",
                                "package_version": "2.1.1",
                                "package_id": "xvvl3S1TT1",
                                "app_id": "xvvl3S1TT1.TizenTubeStandalone",
                                "required_version": "3.0",
                            }
                        ],
                    }
                ],
            },
        ],
    }


def test_parse_snapshot():
    catalog = parse_snapshot(snapshot(make_wgt()))
    assert set(catalog.entries) == {"tizen-community:nuviotv-official.wgt", "tizentube:tizentubecobalt.wgt"}
    nuvio = catalog.entries["tizen-community:nuviotv-official.wgt"]
    assert (nuvio.version, nuvio.package_id, nuvio.icon) == ("1.4.2", "NuvioTV001", "https://x/i.png")
    tt = catalog.entries["tizentube:tizentubecobalt.wgt"]
    assert (tt.name, tt.repo, tt.version) == ("TizenTube", "reisxd/TizenTube", "2.1.1")
    assert asset_stem("Moonfin_Tizen_Legacy_v3.1.0.wgt") == asset_stem("Moonfin_Tizen_Legacy_v3.2.0.wgt")


@pytest.fixture
async def tv(hass: HomeAssistant, sdbd, tizenbrew_json, wgt):
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
        ],
    )
    entry.add_to_hass(hass)
    await hass.async_add_executor_job(
        certificates.write_cert_files,
        certificates.cert_dir(hass, entry.entry_id, "c1"),
        {"tizenbrewInstallerConfig.json": tizenbrew_json},
    )
    catalog = parse_snapshot(snapshot(wgt))
    with (
        patch("custom_components.habrew.coordinator.TizenDevice", lambda host: TizenDevice("127.0.0.1", sdbd.port)),
        patch("custom_components.habrew.catalog.CatalogClient.get", AsyncMock(return_value=catalog)),
        patch("custom_components.habrew.github.GitHubClient.download", AsyncMock(return_value=wgt)) as dl,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry, dl


async def test_panel_registered(hass: HomeAssistant, tv) -> None:
    assert "ha-brew" in hass.data["frontend_panels"]


async def test_ws_flow(hass: HomeAssistant, tv, hass_ws_client, sdbd, caplog) -> None:
    entry, download = tv
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "habrew/overview"})
    res = await client.receive_json()
    assert res["success"], res
    [tvd] = res["result"]["tvs"]
    assert tvd["reachable"] is True and tvd["apps"] == []
    [nuvio] = tvd["tv_apps"]
    assert nuvio["version"] == "1.3.6" and nuvio["catalog"][0]["key"] == "tizen-community:nuviotv-official.wgt"

    await client.send_json_auto_id({"type": "habrew/catalog"})
    res = await client.receive_json()
    assert len(res["result"]["entries"]) == 2

    await client.send_json_auto_id(
        {
            "type": "habrew/app/add",
            "entry_id": entry.entry_id,
            "certificate": "cert1",
            "source": "catalog",
            "catalog_key": "tizen-community:nuviotv-official.wgt",
        }
    )
    res = await client.receive_json()
    assert res["success"], res
    sub_id = res["result"]["subentry_id"]
    await hass.async_block_till_done()

    await client.send_json_auto_id(
        {
            "type": "habrew/app/add",
            "entry_id": entry.entry_id,
            "certificate": "cert1",
            "source": "catalog",
            "catalog_key": "tizen-community:nuviotv-official.wgt",
        }
    )
    res = await client.receive_json()
    assert res["error"]["code"] == "already_configured"

    await client.send_json_auto_id({"type": "habrew/overview"})
    [tvd] = (await client.receive_json())["result"]["tvs"]
    [app] = tvd["apps"]
    assert app["subentry_id"] == sub_id and app["installed_version"] == "1.3.6" and app["latest_version"] == "1.4.2"
    assert app["update_available"] is True and app["icon"] == "https://x/i.png"
    assert tvd["tv_apps"][0]["managed_by"] == sub_id
    state = hass.states.get(app["entity_id"])
    assert state.state == "on" and state.attributes["entity_picture"] == "https://x/i.png"

    await client.send_json_auto_id({"type": "habrew/app/install", "entry_id": entry.entry_id, "subentry_id": sub_id})
    res = await client.receive_json()
    assert res["success"], res
    assert sdbd.installs == ["NuvioTV001"] and download.await_count == 1
    assert hass.states.get(app["entity_id"]).attributes["installed_version"] == "1.4.2"

    await client.send_json_auto_id({"type": "habrew/app/remove", "entry_id": entry.entry_id, "subentry_id": sub_id})
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()
    assert all(s.subentry_type != "app" for s in entry.subentries.values())
    assert hass.states.get(app["entity_id"]) is None
    from homeassistant.helpers import device_registry as dr

    [device] = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert device.config_subentry_id is None
    assert "assigns an existing device" not in caplog.text


async def test_ws_checksum_mismatch(hass: HomeAssistant, tv, hass_ws_client, sdbd) -> None:
    entry, download = tv
    download.return_value = b"tampered"
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "habrew/app/add",
            "entry_id": entry.entry_id,
            "certificate": "cert1",
            "source": "catalog",
            "catalog_key": "tizen-community:nuviotv-official.wgt",
        }
    )
    sub_id = (await client.receive_json())["result"]["subentry_id"]
    await hass.async_block_till_done()
    await client.send_json_auto_id({"type": "habrew/app/install", "entry_id": entry.entry_id, "subentry_id": sub_id})
    res = await client.receive_json()
    assert res["error"]["code"] == "checksum_mismatch"
    assert sdbd.installs == []
