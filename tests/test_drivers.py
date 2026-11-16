"""Tests of the platform-independent Tizen driver."""

from __future__ import annotations

import base64
import hashlib
import io
import urllib.parse
import zipfile

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from custom_components.habrew.drivers.tizen import (
    CertificateError,
    TizenDevice,
    TizenInstallError,
    load_p12_pair,
    load_tizenbrew_config,
    parse_vd_applist,
    read_wgt_metadata,
    resign_wgt,
)
from custom_components.habrew.drivers.tizen.signing import PROP_DIGEST, _prop_object

from .conftest import PASSWORD

lxml = pytest.importorskip("lxml.etree")
NS = {"ds": "http://www.w3.org/2000/09/xmldsig#"}


def test_metadata(wgt):
    meta = read_wgt_metadata(wgt)
    assert (meta.version, meta.package_id, meta.app_id, meta.name) == (
        "1.4.2",
        "NuvioTV001",
        "NuvioTV001.NuvioTV",
        "Nuvio TV",
    )


def test_wrong_password(p12_pair):
    with pytest.raises(CertificateError):
        load_p12_pair(p12_pair[0], p12_pair[1], "nope")


def test_prop_digests_are_canonical():
    for sig_id, digest in PROP_DIGEST.items():
        canonical = _prop_object(sig_id).replace('<Object Id="prop">', f'<Object xmlns="{NS["ds"]}" Id="prop">')
        assert base64.b64encode(hashlib.sha512(canonical.encode()).digest()).decode() == digest


@pytest.mark.parametrize("loader", ["p12", "tizenbrew"])
def test_signature_verifies(loader, p12_pair, tizenbrew_json, wgt):
    profile = load_p12_pair(*p12_pair, PASSWORD) if loader == "p12" else load_tizenbrew_config(tizenbrew_json)
    signed = resign_wgt(wgt, profile)
    zf = zipfile.ZipFile(io.BytesIO(signed))
    names = zf.namelist()
    assert names[:2] == ["signature1.xml", "author-signature.xml"]
    files = {n: zf.read(n) for n in names}
    for sig_file, ident, extra in (
        ("author-signature.xml", profile.author, set()),
        ("signature1.xml", profile.distributor, {"author-signature.xml"}),
    ):
        root = lxml.fromstring(files[sig_file])
        signed_info = root.find("ds:SignedInfo", NS)
        c14n = lxml.tostring(signed_info, method="c14n", exclusive=True)
        sig = base64.b64decode(root.find("ds:SignatureValue", NS).text)
        ident.key.public_key().verify(sig, c14n, padding.PKCS1v15(), hashes.SHA512())
        covered = set()
        for ref in signed_info.findall("ds:Reference", NS):
            uri = ref.get("URI")
            if uri == "#prop":
                continue
            name = urllib.parse.unquote(uri)
            digest = ref.find("ds:DigestValue", NS).text.replace("\n", "")
            assert digest == base64.b64encode(hashlib.sha512(files[name]).digest()).decode()
            covered.add(name)
        assert covered == {"config.xml", "index.html", "js/app bundle.js"} | extra


def test_parse_vd_applist_tizen9():
    out = (
        "-"
        * 93
        + "\n--------------app_id   = NuvioTV001-------------\n--------------app_title   = Nuvio TV-------------\n"
        "--------------app_version   = 1.3.6-------------\n--------------app_tizen_id   = NuvioTV001.NuvioTV-------------\n"
        "--------------app_package_name   = NuvioTV001-------------\n" + "-" * 93 + "\n"
    )
    [app] = parse_vd_applist(out)
    assert (app.package_id, app.app_id, app.version, app.title) == (
        "NuvioTV001",
        "NuvioTV001.NuvioTV",
        "1.3.6",
        "Nuvio TV",
    )


async def test_device_install(sdbd, wgt):
    device = TizenDevice("127.0.0.1", sdbd.port)
    info = await device.get_info()
    assert (info.duid, info.model, info.platform_version) == (sdbd.duid, "QE55MOCK", "9.0")
    progress = []
    await device.install(wgt, "NuvioTV001", "NuvioTV001.NuvioTV", lambda s, p: progress.append((s, p)))
    assert sdbd.pushed == wgt
    assert sdbd.installs == ["NuvioTV001"]
    assert ("install", 100) in progress and progress[0] == ("upload", 0)
    [app] = await device.list_apps()
    assert app.version == "1.4.2"


async def test_device_author_mismatch(sdbd, wgt):
    sdbd.install_result = "author_mismatch"
    with pytest.raises(TizenInstallError) as err:
        await TizenDevice("127.0.0.1", sdbd.port).install(wgt, "NuvioTV001", "NuvioTV001.NuvioTV")
    assert err.value.kind == "author_mismatch"
    assert sdbd.installs == ["NuvioTV001"]  # no pointless retry with the app id
