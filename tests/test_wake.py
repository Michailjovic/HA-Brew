"""Wake-up (WoL / entity) and app launch."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.habrew.drivers.wol import normalize_mac

from .test_catalog_ws import tv  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def fast_wake():
    with (
        patch("custom_components.habrew.coordinator.WAKE_POLL", 0.05),
        patch("custom_components.habrew.coordinator.WAKE_SETTLE", 0),
    ):
        yield


def test_normalize_mac() -> None:
    assert normalize_mac("cc20ac49713d") == "CC:20:AC:49:71:3D"
    assert normalize_mac(" CC-20-AC-49-71-3D ") == "CC:20:AC:49:71:3D"
    with pytest.raises(ValueError):
        normalize_mac("CC:20:AC")


async def _ws(client, payload: dict) -> dict:
    await client.send_json_auto_id(payload)
    return await client.receive_json()


async def test_launch(hass: HomeAssistant, tv, hass_ws_client, sdbd) -> None:  # noqa: F811
    entry, _ = tv
    client = await hass_ws_client(hass)
    res = await _ws(
        client,
        {
            "type": "habrew/app/launch",
            "entry_id": entry.entry_id,
            "app_id": "NuvioTV001.NuvioTV",
        },
    )
    assert res["success"], res
    assert sdbd.launched == ["NuvioTV001.NuvioTV"]
    res = await _ws(
        client,
        {
            "type": "habrew/app/launch",
            "entry_id": entry.entry_id,
            "app_id": "Missing.App",
        },
    )
    assert res["error"]["code"] == "launch_failed"


async def test_offline_without_wake(hass: HomeAssistant, tv, hass_ws_client, sdbd) -> None:  # noqa: F811
    entry, _ = tv
    sdbd.awake = False
    client = await hass_ws_client(hass)
    res = await _ws(
        client,
        {
            "type": "habrew/app/launch",
            "entry_id": entry.entry_id,
            "app_id": "NuvioTV001.NuvioTV",
        },
    )
    assert res["error"]["code"] == "tv_unreachable"
    overview = await _ws(client, {"type": "habrew/overview"})
    assert overview["result"]["tvs"][0]["wake_method"] == "none"


async def test_wake_on_lan(hass: HomeAssistant, tv, hass_ws_client, sdbd) -> None:  # noqa: F811
    entry, _ = tv
    hass.config_entries.async_update_entry(
        entry,
        options={"wake_method": "wol", "mac": "CC:20:AC:49:71:3D", "wake_timeout": 10},
    )
    await hass.async_block_till_done()
    sdbd.awake = False
    packets = []

    def magic(mac, broadcast="255.255.255.255", port=9):
        packets.append((mac, broadcast))
        sdbd.awake = True

    client = await hass_ws_client(hass)
    with patch("custom_components.habrew.coordinator.send_magic_packet", magic):
        res = await _ws(
            client,
            {
                "type": "habrew/app/launch",
                "entry_id": entry.entry_id,
                "app_id": "NuvioTV001.NuvioTV",
            },
        )
    assert res["success"], res
    assert packets == [("CC:20:AC:49:71:3D", "255.255.255.255")]
    assert sdbd.launched == ["NuvioTV001.NuvioTV"]


async def test_wake_entity_fails(hass: HomeAssistant, tv, hass_ws_client, sdbd) -> None:  # noqa: F811
    entry, _ = tv
    calls: list[ServiceCall] = []

    async def turn_on(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("homeassistant", "turn_on", turn_on)
    hass.config_entries.async_update_entry(
        entry,
        options={
            "wake_method": "entity",
            "wake_entity": "media_player.m70",
            "wake_timeout": 1,
        },
    )
    await hass.async_block_till_done()
    sdbd.awake = False
    client = await hass_ws_client(hass)
    res = await _ws(client, {"type": "habrew/wake", "entry_id": entry.entry_id})
    assert res["error"]["code"] == "wake_failed"
    assert len(calls) == 2  # first attempt + one resend
    assert calls[0].data["entity_id"] == "media_player.m70"
