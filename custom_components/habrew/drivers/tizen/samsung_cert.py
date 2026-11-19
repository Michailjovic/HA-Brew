"""Issuing Samsung author + distributor certificates through a Samsung account.

The protocol follows Samsung's Tizen certificate extension (2.0.75), as documented in
https://github.com/gifflet/tizen-cert-cli/blob/main/docs/SAMSUNG-CERT-API-SPEC.md

1. A person signs in at ``LOGIN_URL`` in a browser. Samsung only accepts the redirect
   ``http://localhost:4794/signin/callback`` and POSTs ``code=<JSON>`` there, so a small helper
   must listen on the computer that runs the browser (the integration forwards it).
2. ``code`` carries ``access_token``, ``userId`` and ``inputEmailID``; no token exchange.
3. CSRs (RSA-2048, SHA-512) go to ``svdca.samsungqbe.com`` as hand-built multipart bodies.
   The responses are bare PEM certificates; the CA is appended locally.
"""

from __future__ import annotations

import json
import secrets
import string
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import aiohttp
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from ..base import DeviceError

SERVICE_ID = "v285zxnl3h"
CALLBACK_PORT = 4794
CALLBACK_URL = f"http://localhost:{CALLBACK_PORT}/signin/callback"
LOGIN_URL = (
    "https://account.samsung.com/mobile/account/check.do"
    f"?serviceID={SERVICE_ID}&actionID=StartOAuth2&accessToken=Y&redirect_uri={CALLBACK_URL}"
)
AUTHOR_URL = "https://svdca.samsungqbe.com/apis/v3/authors"
DISTRIBUTOR_URL = "https://svdca.samsungqbe.com/apis/v3/distributors"
DISTRIBUTOR_URL_V1 = "https://svdca.samsungqbe.com/apis/v1/distributors"
PROFILE_URL = "https://account.samsung.com/membership/getProfileInfo.do"
MAX_DUIDS = 50
PRIVILEGES = ("Public", "Partner")

_CA_DIR = Path(__file__).parent / "ca"
_BOUNDARY = "*****"


class SamsungCertError(DeviceError):
    """Samsung refused to issue a certificate (``kind``: rate_limited | no_email | auth | failed)."""

    def __init__(self, message: str, kind: str = "failed") -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class SamsungSession:
    """Result of the browser sign-in."""

    access_token: str
    user_id: str
    email: str


def parse_callback(body: bytes | str) -> SamsungSession:
    """Parse the form body Samsung POSTs to the localhost callback (``code=<url-encoded JSON>``)."""
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    code = urllib.parse.parse_qs(text.strip(), keep_blank_values=True).get("code", [""])[0]
    if not code:
        raise SamsungCertError("The sign-in result contains no 'code' field", "auth")
    try:
        payload = json.loads(code)
    except json.JSONDecodeError as err:
        raise SamsungCertError("The sign-in result is not valid JSON", "auth") from err
    token, user_id = payload.get("access_token") or "", payload.get("userId") or ""
    if not token or not user_id:
        raise SamsungCertError("The sign-in result has no access token", "auth")
    return SamsungSession(access_token=token, user_id=str(user_id), email=payload.get("inputEmailID") or "")


# ---------------------------------------------------------------------- keys and CSRs


def generate_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _csr_pem(builder: x509.CertificateSigningRequestBuilder, key: rsa.RSAPrivateKey) -> bytes:
    return builder.sign(key, hashes.SHA512()).public_bytes(serialization.Encoding.PEM)


def author_csr(key: rsa.RSAPrivateKey, name: str) -> bytes:
    """Author CSR: only CN is needed."""
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name.strip() or "HA-Brew")])
    return _csr_pem(x509.CertificateSigningRequestBuilder().subject_name(subject), key)


def distributor_csr(key: rsa.RSAPrivateKey, email: str, duids: list[str]) -> bytes:
    """Distributor CSR: CN=TizenSDK + account e-mail, SAN with an empty package id and the TVs' DUIDs."""
    clean = [d.strip() for d in duids if d and d.strip()]
    if not clean:
        raise SamsungCertError("At least one TV (DUID) is needed")
    if len(clean) > MAX_DUIDS:
        raise SamsungCertError(f"Samsung allows at most {MAX_DUIDS} TVs per certificate")
    names = [x509.NameAttribute(NameOID.COMMON_NAME, "TizenSDK")]
    if email:
        names.append(x509.NameAttribute(NameOID.EMAIL_ADDRESS, email))
    san = x509.SubjectAlternativeName(
        [x509.UniformResourceIdentifier("URN:tizen:packageid=")]
        + [x509.UniformResourceIdentifier(f"URN:tizen:deviceid={d}") for d in dict.fromkeys(clean)]
    )
    builder = x509.CertificateSigningRequestBuilder().subject_name(x509.Name(names)).add_extension(san, critical=False)
    return _csr_pem(builder, key)


# ---------------------------------------------------------------------- Samsung API


def multipart_body(fields: list[tuple[str, str]], csr_name: str, csr: bytes) -> bytes:
    """The exact body Samsung's client builds by hand (literal boundary, csr part without Content-Type)."""
    body = b""
    for name, value in fields:
        body += (
            f"--{_BOUNDARY}\r\nContent-Type: text/plain; charset=utf-8\r\n"
            f"Content-Disposition: form-data; name={name}\r\n\r\n{value}\r\n"
        ).encode()
    body += (
        f"--{_BOUNDARY}\r\nContent-Disposition: form-data; name=csr; filename={csr_name}; "
        f"filename*=utf-8''{csr_name}\r\n\r\n"
    ).encode()
    return body + csr + f"\r\n--{_BOUNDARY}--\r\n".encode()


async def _post(
    session: aiohttp.ClientSession, url: str, fields: list[tuple[str, str]], name: str, csr: bytes
) -> bytes:
    try:
        async with session.post(
            url,
            data=multipart_body(fields, name, csr),
            headers={"Content-Type": f'multipart/form-data; boundary="{_BOUNDARY}"'},
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            payload = await resp.read()
            status = resp.status
    except (aiohttp.ClientError, TimeoutError) as err:
        raise SamsungCertError(f"Samsung certificate service not reachable: {err}") from err
    if status == 200:
        return payload
    if status == 403:
        raise SamsungCertError("Samsung: too many requests, try again later", "rate_limited")
    description, code = payload.decode("utf-8", "replace").strip()[:300], ""
    try:
        err = json.loads(payload).get("error") or {}
        description, code = err.get("description") or description, str(err.get("code", ""))
    except (ValueError, AttributeError):
        pass
    if status == 401 and code == "303":
        raise SamsungCertError("The Samsung account has no e-mail address", "no_email")
    if status == 401:
        raise SamsungCertError(f"Samsung rejected the sign-in: {description}", "auth")
    raise SamsungCertError(f"Samsung HTTP {status}: {description} ({code})")


def _first_pem_certificate(data: bytes) -> x509.Certificate:
    try:
        return x509.load_pem_x509_certificate(data)
    except ValueError as err:
        raise SamsungCertError(f"Samsung did not return a certificate: {data[:120]!r}") from err


async def issue_author(http: aiohttp.ClientSession, login: SamsungSession, csr: bytes) -> x509.Certificate:
    fields = [("access_token", login.access_token), ("user_id", login.user_id), ("platform", "VD")]
    return _first_pem_certificate(await _post(http, AUTHOR_URL, fields, "author.csr", csr))


async def issue_distributor(
    http: aiohttp.ClientSession, login: SamsungSession, csr: bytes, privilege: str = "Public"
) -> x509.Certificate:
    if privilege not in PRIVILEGES:
        raise SamsungCertError(f"Unknown privilege level {privilege}")
    fields = [
        ("access_token", login.access_token),
        ("user_id", login.user_id),
        ("privilege_level", privilege),
        ("developer_type", "Individual"),
        ("platform", "VD"),
    ]
    # Samsung's client registers the device profile (v1) before asking for the certificate (v3).
    await _post(http, DISTRIBUTOR_URL_V1, fields, "distributor.csr", csr)
    return _first_pem_certificate(await _post(http, DISTRIBUTOR_URL, fields, "distributor.csr", csr))


# ---------------------------------------------------------------------- PKCS#12


def ca_certificate(kind: str) -> x509.Certificate:
    """``author`` | ``Public`` | ``Partner``."""
    name = {"author": "author_ca.pem", "Public": "distributor_public.pem", "Partner": "distributor_partner.pem"}[kind]
    return x509.load_pem_x509_certificate((_CA_DIR / name).read_bytes())


def new_password() -> str:
    """16 characters with lower, upper and digits (Samsung's tools require all three)."""
    alphabet = string.ascii_letters + string.digits
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(16))
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
        ):
            return password


def to_p12(key: rsa.RSAPrivateKey, cert: x509.Certificate, ca: x509.Certificate, password: str) -> bytes:
    """Legacy PKCS#12 (PBE-SHA1-3DES, SHA-1 MAC), which Tizen tools expect; readable by HA-Brew too."""
    encryption = (
        serialization.PrivateFormat.PKCS12.encryption_builder()
        .kdf_rounds(2048)
        .key_cert_algorithm(pkcs12.PBES.PBESv1SHA1And3KeyTripleDESCBC)
        .hmac_hash(hashes.SHA1())
        .build(password.encode())
    )
    return pkcs12.serialize_key_and_certificates(b"usercertificate", key, cert, [ca], encryption)


def author_key_from_p12(raw: bytes, password: str) -> rsa.RSAPrivateKey:
    """Reuse an existing author key, so every certificate HA-Brew creates shares one author.

    Whether a TV accepts an update signed by a renewed author certificate over the same key is
    not verified yet; reusing the key is what Samsung's own tools do on renewal.
    """
    key, _cert, _extra = pkcs12.load_key_and_certificates(raw, password.encode())
    if not isinstance(key, rsa.RSAPrivateKey):
        raise SamsungCertError("The stored author key is not RSA")
    return key
