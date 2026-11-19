"""LG webOS driver against the fake Developer Mode SSH server (no Home Assistant involved)."""

from __future__ import annotations

import pytest

from custom_components.habrew.drivers.base import DeviceAuthError, DeviceConnectError, InstallError, LaunchError
from custom_components.habrew.drivers.webos import (
    WebosDevice,
    fetch_key,
    load_key,
    parse_remaining,
    read_ipk_metadata,
)
from custom_components.habrew.drivers.webos.devmode import DevModeError

from .mock_webos import PASSPHRASE, SERIAL, TOKEN, MockKeyServer, MockWebosTv, make_ipk, make_key_pem


@pytest.fixture
async def webos_tv(socket_enabled):
    tv = MockWebosTv()
    await tv.start()
    yield tv
    await tv.stop()


def _device(tv: MockWebosTv, pem: str | None = None, passphrase: str = PASSPHRASE) -> WebosDevice:
    return WebosDevice("127.0.0.1", pem or tv.key_pem, passphrase, port=tv.port)


def test_read_ipk_metadata() -> None:
    meta = read_ipk_metadata(make_ipk("youtube.leanback.v4", "0.5.3", "YouTube AdFree"))
    assert (meta.package_id, meta.app_id, meta.version, meta.name) == (
        "youtube.leanback.v4",
        "youtube.leanback.v4",
        "0.5.3",
        "YouTube AdFree",
    )
    with pytest.raises(ValueError):
        read_ipk_metadata(b"PK\x03\x04 not an ipk")


def test_parse_remaining() -> None:
    assert parse_remaining("992:14:20") == 992 * 3600 + 14 * 60 + 20
    with pytest.raises(DevModeError):
        parse_remaining("GNL")


def test_load_key() -> None:
    pem = make_key_pem()
    assert load_key(pem, PASSPHRASE).get_algorithm() == "ssh-rsa"
    with pytest.raises(DeviceAuthError):
        load_key(pem, "WRONG1")


async def test_fetch_key(socket_enabled) -> None:
    server = MockKeyServer(make_key_pem())
    await server.start()
    try:
        pem = await fetch_key("127.0.0.1", server.port)
    finally:
        await server.stop()
    assert pem.startswith("-----BEGIN RSA PRIVATE KEY-----") and "END RSA PRIVATE KEY" in pem
    with pytest.raises(DeviceConnectError):
        await fetch_key("127.0.0.1", server.port, timeout=1)


async def test_info_apps_token(webos_tv: MockWebosTv) -> None:
    device = _device(webos_tv)
    info = await device.get_info()
    assert info.serial == SERIAL and info.model == "OLED55MOCK" and info.sdk_version == "11.2.0"
    apps = {a.app_id: a for a in await device.list_apps()}
    assert apps["space.nuvio.webos"].version == "1.4.0"
    assert apps["space.nuvio.webos"].origin == "sideload"
    assert await device.session_token() == TOKEN


async def test_install(webos_tv: MockWebosTv) -> None:
    device = _device(webos_tv)
    progress: list[tuple[str, int]] = []
    await device.install(
        make_ipk(version="1.4.4"), "space.nuvio.webos", "space.nuvio.webos", lambda *p: progress.append(p)
    )
    assert webos_tv.installed == ["space.nuvio.webos"]
    assert webos_tv.apps["space.nuvio.webos"]["version"] == "1.4.4"
    assert progress[0] == ("upload", 0) and ("upload", 100) in progress and progress[-1] == ("install", 100)
    assert webos_tv.files == {}  # temporary package removed

    webos_tv.install_result = "fail"
    with pytest.raises(InstallError) as err:
        await device.install(make_ipk(), "space.nuvio.webos", "space.nuvio.webos")
    assert err.value.code == "-5"
    assert "IPK Extraction Failure" in str(err.value)

    with pytest.raises(ValueError):
        await device.install(make_ipk(), "bad id; rm -rf /", "x")


async def test_launch(webos_tv: MockWebosTv) -> None:
    device = _device(webos_tv)
    await device.launch("space.nuvio.webos")
    assert webos_tv.launched == ["space.nuvio.webos"]
    with pytest.raises(LaunchError):
        await device.launch("com.missing.app")


async def test_auth_and_connect_errors(webos_tv: MockWebosTv) -> None:
    with pytest.raises(DeviceAuthError):
        await _device(webos_tv, pem=make_key_pem()).get_info()  # key from a reinstalled Dev Mode
    with pytest.raises(DeviceAuthError):
        await _device(webos_tv, passphrase="WRONG1").get_info()
    closed = WebosDevice("127.0.0.1", webos_tv.key_pem, PASSPHRASE, port=1)
    with pytest.raises(DeviceConnectError):
        await closed.list_apps()
