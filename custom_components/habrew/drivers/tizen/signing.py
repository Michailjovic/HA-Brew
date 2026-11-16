"""Re-signing Tizen web widgets with a Samsung author + distributor certificate.

Implements the W3C widget digital signature profile the way Samsung's own tooling does it
(SHA-512 digests, RSA-SHA512, exclusive C14N, constant ``#prop`` digests). The output is
byte-identical to the tizen-js signer used by TizenBrew Installer and NuvioTVSmart-Installer
(originally from Samsung webIDE-common-tizentv, Apache-2.0).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import urllib.parse
import warnings
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import pkcs12

XMLDSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
# Digest of the canonical <Object Id="prop"> element – constant for each signature role.
PROP_DIGEST = {
    "AuthorSignature": "aXbSAVgmAz0GsBUeZ1UmNDRrxkWhDUVGb45dZcNRq429wX3X+x6kaXT3NdNDTSNVTU+ypkysPMGvQY10fG1EWQ==",
    "DistributorSignature": "/r5npk2VVA46QFJnejgONBEh4BWtjrtu9x/IFeLksjWyGmB/cMWKSJWQl7aU3YRQRZ3AesG8gF7qGyvKX9Snig==",
}
SIGNATURE_FILE_RX = re.compile(r"^(author-signature|signature\d+)\.xml$")


class CertificateError(Exception):
    """Certificate could not be loaded (wrong password, broken file, unsupported format)."""


# ---------------------------------------------------------------------------
# PKCS#12 loading
# ---------------------------------------------------------------------------


def _der_tlv(b: bytes, i: int) -> tuple[int, bytes, int]:
    tag = b[i]
    ln = b[i + 1]
    i += 2
    if ln & 0x80:
        n = ln & 0x7F
        ln = int.from_bytes(b[i : i + n], "big")
        i += n
    return tag, b[i : i + ln], i + ln


def _der_children(b: bytes) -> list[tuple[int, bytes]]:
    out, i = [], 0
    while i < len(b):
        tag, val, i = _der_tlv(b, i)
        out.append((tag, val))
    return out


def _der_wrap(tag: int, body: bytes) -> bytes:
    ln = len(body)
    if ln < 0x80:
        return bytes([tag, ln]) + body
    nb = (ln.bit_length() + 7) // 8
    return bytes([tag, 0x80 | nb]) + ln.to_bytes(nb, "big") + body


_OID_DATA = bytes.fromhex("2a864886f70d010701")
_OID_CERTBAG = bytes.fromhex("2a864886f70d010c0a0103")
_OID_SHROUDED = bytes.fromhex("2a864886f70d010c0a0102")


def _manual_pkcs12(raw: bytes, password: str):
    """Fallback PKCS#12 reader (plain SafeContents + PBES2 shrouded key).

    node-forge (TizenBrew Installer) encodes the e-mail in the distributor subject as a
    PrintableString, which ``cryptography`` rejects. The certificate DER is only embedded
    in the signature, so it does not need to be parsed.
    """
    _, pfx, _ = _der_tlv(raw, 0)
    authsafe = _der_children(pfx)[1][1]
    ct_oid, ct_content = _der_children(authsafe)[:2]
    if ct_oid[1] != _OID_DATA:
        raise CertificateError("Unsupported PKCS#12 authSafe type")
    octet = _der_children(ct_content[1])[0][1]
    certs: list[bytes] = []
    key = None
    for ci in _der_children(_der_children(octet)[0][1]):
        oid, cont = _der_children(ci[1])[:2]
        if oid[1] != _OID_DATA:
            raise CertificateError("Encrypted PKCS#12 SafeContents are not supported")
        safe = _der_children(cont[1])[0][1]
        for bag in _der_children(_der_children(safe)[0][1]):
            parts = _der_children(bag[1])
            val = _der_children(parts[1][1])[0]
            if parts[0][1] == _OID_CERTBAG:
                certs.append(_der_children(_der_children(val[1])[1][1])[0][1])
            elif parts[0][1] == _OID_SHROUDED:
                key = serialization.load_der_private_key(_der_wrap(0x30, val[1]), password.encode())
    if key is None or not certs:
        raise CertificateError("PKCS#12 does not contain a key and a certificate")
    modulus = key.public_key().public_numbers().n.to_bytes(key.key_size // 8, "big")
    leaf = next((c for c in certs if modulus in c), certs[0])
    return key, leaf, [c for c in certs if c is not leaf]


class SigningIdentity:
    """Private key + certificate chain from one PKCS#12 file."""

    def __init__(self, p12: bytes, password: str) -> None:
        try:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")  # BER-encoded files from Apps2Samsung
                    bundle = pkcs12.load_pkcs12(p12, password.encode())
                if bundle.key is None or bundle.cert is None:
                    raise CertificateError("PKCS#12 does not contain a key and a certificate")
                self.key = bundle.key
                self.leaf_der = bundle.cert.certificate.public_bytes(serialization.Encoding.DER)
                self.chain_der = [
                    c.certificate.public_bytes(serialization.Encoding.DER) for c in bundle.additional_certs
                ]
            except ValueError:
                self.key, self.leaf_der, self.chain_der = _manual_pkcs12(p12, password)
        except CertificateError:
            raise
        except Exception as err:  # wrong password, truncated file, ...
            raise CertificateError(f"Cannot open certificate: {err}") from err
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.cert: x509.Certificate | None = x509.load_der_x509_certificate(self.leaf_der)
                self.cert.subject.rfc4514_string()
        except ValueError:
            self.cert = None

    @property
    def common_name(self) -> str:
        if self.cert is None:
            return ""
        attrs = self.cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
        return str(attrs[0].value) if attrs else ""

    @property
    def serial(self) -> str:
        return f"{self.cert.serial_number:x}" if self.cert else ""

    @property
    def not_after(self) -> datetime | None:
        return self.cert.not_valid_after_utc if self.cert else None

    def certs_der(self) -> list[bytes]:
        return [self.leaf_der, *self.chain_der]


@dataclass
class SigningProfile:
    """Author + distributor identity used to sign a package."""

    author: SigningIdentity
    distributor: SigningIdentity


def load_tizenbrew_config(raw: bytes) -> SigningProfile:
    """Load ``tizenbrewInstallerConfig.json`` (TizenBrew Installer)."""
    try:
        cfg = json.loads(raw)
        password = cfg["password"]
        author = base64.b64decode(cfg["authorCert"])
        distributor = base64.b64decode(cfg["distributorCert"])
    except (ValueError, KeyError, TypeError) as err:
        raise CertificateError(f"Not a TizenBrew Installer configuration: {err}") from err
    return SigningProfile(SigningIdentity(author, password), SigningIdentity(distributor, password))


def load_p12_pair(author_p12: bytes, distributor_p12: bytes, password: str) -> SigningProfile:
    """Load an author.p12 + distributor.p12 pair (Apps2Samsung, Tizen Studio)."""
    return SigningProfile(SigningIdentity(author_p12, password), SigningIdentity(distributor_p12, password))


def load_profile_dir(path: Path) -> SigningProfile:
    """Load a stored profile directory (see certificates.py in the integration)."""
    tb = path / "tizenbrewInstallerConfig.json"
    if tb.exists():
        return load_tizenbrew_config(tb.read_bytes())
    password = (path / "password.txt").read_text(encoding="utf-8").strip()
    return load_p12_pair((path / "author.p12").read_bytes(), (path / "distributor.p12").read_bytes(), password)


# ---------------------------------------------------------------------------
# Signature generation
# ---------------------------------------------------------------------------


def _wrap76(s: str) -> str:
    return re.sub(r"(.{76})", r"\1\n", s)


def _encode_uri(name: str) -> str:
    # encodeURIComponent semantics (also "/" -> %2F), as Samsung's signer does
    return urllib.parse.quote(name, safe="!*'()")


def _prop_object(sig_id: str) -> str:
    role = "author" if sig_id == "AuthorSignature" else "distributor"
    return (
        '<Object Id="prop">'
        '<SignatureProperties xmlns:dsp="http://www.w3.org/2009/xmldsig-properties">'
        f'<SignatureProperty Id="profile" Target="#{sig_id}">'
        '<dsp:Profile URI="http://www.w3.org/ns/widgets-digsig#profile"></dsp:Profile>'
        "</SignatureProperty>"
        f'<SignatureProperty Id="role" Target="#{sig_id}">'
        f'<dsp:Role URI="http://www.w3.org/ns/widgets-digsig#role-{role}"></dsp:Role>'
        "</SignatureProperty>"
        f'<SignatureProperty Id="identifier" Target="#{sig_id}">'
        "<dsp:Identifier></dsp:Identifier></SignatureProperty></SignatureProperties></Object>"
    )


def _reference(uri: str, digest_b64: str) -> str:
    transforms = (
        '<Transforms>\n<Transform Algorithm="http://www.w3.org/2006/12/xml-c14n11"></Transform>\n</Transforms>\n'
        if uri == "#prop"
        else ""
    )
    return (
        f'<Reference URI="{uri}">\n{transforms}'
        '<DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha512"></DigestMethod>\n'
        f"<DigestValue>{_wrap76(digest_b64)}</DigestValue>\n</Reference>\n"
    )


def build_signature(sig_id: str, files: list[tuple[str, bytes]], ident: SigningIdentity) -> bytes:
    """Build author-signature.xml / signature1.xml for the given files."""
    refs = "".join(
        _reference(_encode_uri(name), base64.b64encode(hashlib.sha512(data).digest()).decode()) for name, data in files
    )
    refs += _reference("#prop", PROP_DIGEST[sig_id])
    signed_info = (
        "<SignedInfo>\n"
        '<CanonicalizationMethod Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#"></CanonicalizationMethod>\n'
        '<SignatureMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha512"></SignatureMethod>\n'
        f"{refs}</SignedInfo>"
    )
    # Exclusive C14N of SignedInfo = the same text with the default namespace rendered.
    canonical = signed_info.replace("<SignedInfo>", f'<SignedInfo xmlns="{XMLDSIG_NS}">', 1).encode()
    sig_value = base64.b64encode(ident.key.sign(canonical, padding.PKCS1v15(), hashes.SHA512())).decode()

    key_info = "<KeyInfo>\n<X509Data>"
    for der in ident.certs_der():
        b64 = _wrap76(base64.b64encode(der).decode())
        key_info += f"\n<X509Certificate>{'' if b64.startswith(chr(10)) else chr(10)}{b64}\n</X509Certificate>"
    key_info += "\n</X509Data>\n</KeyInfo>\n"

    return (
        f'<Signature xmlns="{XMLDSIG_NS}" Id="{sig_id}">\n'
        f"{signed_info}\n"
        f"<SignatureValue>\n{_wrap76(sig_value)}\n</SignatureValue>\n"
        f"{key_info}"
        f"{_prop_object(sig_id)}\n"
        "</Signature>\n"
    ).encode()


def resign_wgt(wgt: bytes, profile: SigningProfile) -> bytes:
    """Strip existing signatures and sign the widget with author + distributor identity."""
    with zipfile.ZipFile(io.BytesIO(wgt)) as zf:
        files = [
            (info.filename, zf.read(info))
            for info in zf.infolist()
            if not info.is_dir() and not SIGNATURE_FILE_RX.match(info.filename)
        ]
    author_xml = build_signature("AuthorSignature", files, profile.author)
    files = [("author-signature.xml", author_xml), *files]
    dist_xml = build_signature("DistributorSignature", files, profile.distributor)
    files = [("signature1.xml", dist_xml), *files]

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in files:
            zf.writestr(name, data)
    return out.getvalue()
