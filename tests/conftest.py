"""Shared fixtures."""

from __future__ import annotations

import base64
import datetime as dt
import io
import json
import zipfile

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from .mock_sdbd import MockSdbd

PASSWORD = "secret123"
DUID = "TESTDUID0001"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def _cert(subject_cn, issuer_cn, key, issuer_key, extra_san=None, ca=False):
    now = dt.datetime.now(dt.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject_cn)]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer_cn)]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    if extra_san:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.UniformResourceIdentifier(u) for u in extra_san]), False
        )
    return builder.sign(issuer_key, hashes.SHA256())


def make_p12(cn: str, duid: str | None = None) -> bytes:
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca = _cert(f"{cn} CA", f"{cn} CA", ca_key, ca_key, ca=True)
    san = [f"URN:tizen:deviceid={duid}"] if duid else None
    leaf = _cert(cn, f"{cn} CA", key, ca_key, extra_san=san)
    return pkcs12.serialize_key_and_certificates(
        b"x", key, leaf, [ca], serialization.BestAvailableEncryption(PASSWORD.encode())
    )


@pytest.fixture(scope="session")
def p12_pair():
    return make_p12("Test Author"), make_p12("TizenSDK", DUID)


@pytest.fixture(scope="session")
def tizenbrew_json(p12_pair):
    author, dist = p12_pair
    return json.dumps(
        {
            "authorCert": base64.b64encode(author).decode(),
            "distributorCert": base64.b64encode(dist).decode(),
            "password": PASSWORD,
        }
    ).encode()


def make_wgt(version="1.4.2", package="NuvioTV001", app="NuvioTV001.NuvioTV") -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr(
            "config.xml",
            f'<?xml version="1.0"?><widget xmlns="http://www.w3.org/ns/widgets" xmlns:tizen="http://tizen.org/ns/widgets" version="{version}">'
            f'<name>Nuvio TV</name><tizen:application id="{app}" package="{package}" required_version="2.3"/></widget>',
        )
        zf.writestr("index.html", "<html></html>")
        zf.writestr("js/app bundle.js", "x" * 20000)
        zf.writestr("author-signature.xml", "old")
    return out.getvalue()


@pytest.fixture
def wgt() -> bytes:
    return make_wgt()


@pytest.fixture
async def sdbd(socket_enabled):
    server = MockSdbd(duid=DUID)
    await server.start()
    yield server
    await server.stop()
