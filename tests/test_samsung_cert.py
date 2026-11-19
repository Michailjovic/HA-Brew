"""Creating a Samsung certificate: CSRs, Samsung API, sign-in relay and the certificate flow."""

from __future__ import annotations

import datetime as dt
import json
import re
import urllib.parse

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habrew import certificates
from custom_components.habrew.const import DOMAIN
from custom_components.habrew.drivers.tizen import load_p12_pair
from custom_components.habrew.drivers.tizen import samsung_cert as sc

from .conftest import DUID

EMAIL = "tv@example.com"
CALLBACK_BODY = "code=" + urllib.parse.quote(
    json.dumps({"access_token": "TOKEN1", "userId": "USER1", "inputEmailID": EMAIL, "access_token_expires_in": 3600})
)

# ---------------------------------------------------------------------- driver


def test_distributor_csr() -> None:
    pem = sc.distributor_csr(sc.generate_key(), EMAIL, [DUID, "SECOND0001", DUID])
    csr = x509.load_pem_x509_csr(pem)
    assert csr.signature_hash_algorithm.name == "sha512"
    assert csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "TizenSDK"
    assert csr.subject.get_attributes_for_oid(NameOID.EMAIL_ADDRESS)[0].value == EMAIL
    san = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    # exact case matters: Samsung expects "URN:tizen:"
    assert [g.value for g in san] == [
        "URN:tizen:packageid=",
        f"URN:tizen:deviceid={DUID}",
        "URN:tizen:deviceid=SECOND0001",
    ]
    with pytest.raises(sc.SamsungCertError):
        sc.distributor_csr(sc.generate_key(), EMAIL, [])
    with pytest.raises(sc.SamsungCertError):
        sc.distributor_csr(sc.generate_key(), EMAIL, [f"D{i:05}" for i in range(51)])


def test_author_csr_and_multipart() -> None:
    csr = sc.author_csr(sc.generate_key(), "Michal")
    assert x509.load_pem_x509_csr(csr).subject.rfc4514_string() == "CN=Michal"
    body = sc.multipart_body([("access_token", "T"), ("platform", "VD")], "author.csr", csr)
    assert body.startswith(
        b"--*****\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Disposition: form-data; name=access_token"
    )
    assert (
        b"name=csr; filename=author.csr; filename*=utf-8''author.csr\r\n\r\n-----BEGIN CERTIFICATE REQUEST-----" in body
    )
    assert body.endswith(b"\r\n--*****--\r\n")


def test_parse_callback() -> None:
    session = sc.parse_callback(CALLBACK_BODY.encode())
    assert session == sc.SamsungSession("TOKEN1", "USER1", EMAIL)
    for bad in (b"", b"code=", b"code=notjson", b"code=" + urllib.parse.quote('{"userId":"x"}').encode()):
        with pytest.raises(sc.SamsungCertError):
            sc.parse_callback(bad)


def test_p12_roundtrip() -> None:
    """The generated pair loads like an uploaded Apps2Samsung pair, with Samsung's CA in the chain."""
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_a, key_d = sc.generate_key(), sc.generate_key()
    cert_a = _sign(x509.load_pem_x509_csr(sc.author_csr(key_a, "Me")), ca_key)
    cert_d = _sign(x509.load_pem_x509_csr(sc.distributor_csr(key_d, EMAIL, [DUID])), ca_key)
    password = sc.new_password()
    assert re.search("[a-z]", password) and re.search("[A-Z]", password) and re.search("[0-9]", password)
    author = sc.to_p12(key_a, cert_a, sc.ca_certificate("author"), password)
    distributor = sc.to_p12(key_d, cert_d, sc.ca_certificate("Public"), password)
    profile = load_p12_pair(author, distributor, password)
    assert profile.author.common_name == "Me"
    assert len(profile.author.chain_der) == 1
    assert sc.author_key_from_p12(author, password).private_numbers() == key_a.private_numbers()


def _sign(csr: x509.CertificateSigningRequest, ca_key) -> x509.Certificate:
    now = dt.datetime.now(dt.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Mock VD CA")]))
        .public_key(csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=365))
    )
    try:
        builder = builder.add_extension(
            csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value, False
        )
    except x509.ExtensionNotFound:
        pass
    return builder.sign(ca_key, hashes.SHA256())


# ---------------------------------------------------------------------- flow


class MockSamsung:
    """Fake svdca.samsungqbe.com: signs whatever CSR arrives."""

    def __init__(self) -> None:
        self.ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.status = 200
        self.error: dict | None = None

    def handler(self, url: str):
        async def respond(method, url_, data):
            text = data.decode() if isinstance(data, bytes) else data
            fields = dict(re.findall(r"name=(\w+)\r\n\r\n([^\r]*)\r\n", text))
            self.calls.append((str(url_), fields))
            from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

            if self.status != 200:
                body = json.dumps({"error": self.error}).encode() if self.error else b"Too many"
                return AiohttpClientMockResponse(method, url_, status=self.status, response=body)
            if url.endswith("/v1/distributors"):
                return AiohttpClientMockResponse(method, url_, status=200, response=b"<profile/>")
            csr_pem = text[
                text.index("-----BEGIN CERTIFICATE REQUEST-----") : text.index("-----END CERTIFICATE REQUEST-----") + 33
            ]
            cert = _sign(x509.load_pem_x509_csr(csr_pem.encode()), self.ca_key)
            return AiohttpClientMockResponse(
                method, url_, status=200, response=cert.public_bytes(serialization.Encoding.PEM)
            )

        return respond


@pytest.fixture
def samsung_api(aioclient_mock):
    api = MockSamsung()
    for url in (sc.AUTHOR_URL, sc.DISTRIBUTOR_URL_V1, sc.DISTRIBUTOR_URL):
        aioclient_mock.post(url, side_effect=api.handler(url))
    return api


@pytest.fixture
async def tv_entry(hass: HomeAssistant):
    hass.config.internal_url = "http://192.168.1.2:8123"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="M70",
        unique_id=DUID,
        data={"host": "127.0.0.1", "platform": "tizen", "duid": DUID, "platform_version": "9.0"},
    )
    entry.add_to_hass(hass)
    # loads the integration (HTTP views) without connecting to a TV
    from unittest.mock import patch

    with patch("custom_components.habrew.async_setup_entry", return_value=True):
        assert await hass.config_entries.async_setup(entry.entry_id)
    return entry


async def _start(hass: HomeAssistant, entry, extra: str = "") -> dict:
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "certificate"), context={"source": "user"}
    )
    assert result["step_id"] == "user"
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"cert_type": "samsung"})
    assert result["step_id"] == "samsung"
    assert DUID in result["description_placeholders"]["duids"]
    data = {"author_cn": "Michal", "privilege": "public"}
    if extra:
        data["extra_duids"] = extra
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], data)
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["progress_action"] == "samsung_login"
    return result


def _token(result: dict) -> str:
    cmd = result["description_placeholders"]["windows"]
    assert cmd.startswith("powershell") and "http://192.168.1.2:8123/api/habrew/samsung_login/" in cmd
    return re.search(r"samsung_login/([^/]+)/helper\.ps1", cmd).group(1)


async def test_create_certificate(hass: HomeAssistant, tv_entry, samsung_api, hass_client_no_auth) -> None:
    result = await _start(hass, tv_entry, extra="OTHERTV001, OTHERTV002")
    token = _token(result)
    assert "curl -fsSL" in result["description_placeholders"]["unix"]

    client = await hass_client_no_auth()
    resp = await client.get(f"/api/habrew/samsung_login/{token}/helper.ps1")
    script = await resp.text()
    assert (
        resp.status == 200
        and "http://localhost:4794/" in script
        and token in script
        and "serviceID=v285zxnl3h" in script
    )
    resp = await client.get(f"/api/habrew/samsung_login/{token}/helper.py")
    assert resp.status == 200 and "4794" in await resp.text()
    assert (await client.get("/api/habrew/samsung_login/wrong/helper.ps1")).status == 404
    assert (await client.post("/api/habrew/samsung_login/wrong", data=CALLBACK_BODY)).status == 404

    resp = await client.post(
        f"/api/habrew/samsung_login/{token}",
        data=CALLBACK_BODY,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status == 200
    await hass.async_block_till_done()
    result = await hass.config_entries.subentries.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    assert result["title"] == f"Samsung ({EMAIL})"
    assert result["data"]["cert_type"] == "samsung"
    assert result["data"]["duids"] == [DUID, "OTHERTV001", "OTHERTV002"]
    assert result["data"]["author_cn"] == "Michal"

    urls = [u for u, _ in samsung_api.calls]
    assert urls == [sc.AUTHOR_URL, sc.DISTRIBUTOR_URL_V1, sc.DISTRIBUTOR_URL]
    assert samsung_api.calls[0][1] == {"access_token": "TOKEN1", "user_id": "USER1", "platform": "VD"}
    assert samsung_api.calls[2][1]["privilege_level"] == "Public"

    # the token is single use
    assert (await client.get(f"/api/habrew/samsung_login/{token}/helper.ps1")).status == 404

    profile = await hass.async_add_executor_job(
        certificates.load_profile, hass, tv_entry.entry_id, result["data"]["cert_id"]
    )
    assert profile.author.common_name == "Michal"
    san = x509.load_der_x509_certificate(profile.distributor.leaf_der).extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    )
    assert f"URN:tizen:deviceid={DUID}" in [g.value for g in san.value]

    # a second certificate reuses the same author key
    result = await _start(hass, tv_entry)
    resp = await client.post(f"/api/habrew/samsung_login/{_token(result)}", data=CALLBACK_BODY)
    await hass.async_block_till_done()
    second = await hass.config_entries.subentries.async_configure(result["flow_id"])
    other = await hass.async_add_executor_job(
        certificates.load_profile, hass, tv_entry.entry_id, second["data"]["cert_id"]
    )
    assert other.author.key.public_key().public_numbers() == profile.author.key.public_key().public_numbers()


@pytest.mark.parametrize(
    ("status", "error", "reason"),
    [
        (403, None, "samsung_rate_limited"),
        (401, {"code": "303", "status": 401, "description": "no email"}, "samsung_no_email"),
        (
            401,
            {"code": "301", "status": 401, "description": "Either userid or accesstoken is incorrect."},
            "samsung_auth",
        ),
        (500, {"code": "999", "status": 500, "description": "boom"}, "samsung_failed"),
    ],
)
async def test_samsung_errors(
    hass: HomeAssistant, tv_entry, samsung_api, hass_client_no_auth, status, error, reason
) -> None:
    samsung_api.status, samsung_api.error = status, error
    result = await _start(hass, tv_entry)
    client = await hass_client_no_auth()
    await client.post(f"/api/habrew/samsung_login/{_token(result)}", data=CALLBACK_BODY)
    await hass.async_block_till_done()
    result = await hass.config_entries.subentries.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason


async def test_invalid_extra_duid(hass: HomeAssistant, tv_entry) -> None:
    result = await hass.config_entries.subentries.async_init(
        (tv_entry.entry_id, "certificate"), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(result["flow_id"], {"cert_type": "samsung"})
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"author_cn": "x", "privilege": "public", "extra_duids": "bad duid!"}
    )
    assert result["errors"] == {"extra_duids": "invalid_duid"}


async def test_closing_dialog_stops_waiting(hass: HomeAssistant, tv_entry, hass_client_no_auth) -> None:
    result = await _start(hass, tv_entry)
    token = _token(result)
    hass.config_entries.subentries.async_abort(result["flow_id"])
    await hass.async_block_till_done()
    client = await hass_client_no_auth()
    assert (await client.get(f"/api/habrew/samsung_login/{token}/helper.ps1")).status == 404
