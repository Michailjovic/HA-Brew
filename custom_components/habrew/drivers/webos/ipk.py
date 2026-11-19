"""Reading metadata from webOS packages (.ipk = ``ar`` archive with control and data tarballs)."""

from __future__ import annotations

import io
import json
import tarfile

from ..base import PackageMetadata

_AR_MAGIC = b"!<arch>\n"
_AR_HEADER = 60


def _ar_members(data: bytes) -> dict[str, bytes]:
    """Members of a (GNU or BSD style, no long names needed) ar archive."""
    if not data.startswith(_AR_MAGIC):
        raise ValueError("Not a webOS package (.ipk): missing ar header")
    members: dict[str, bytes] = {}
    pos = len(_AR_MAGIC)
    while pos + _AR_HEADER <= len(data):
        header = data[pos : pos + _AR_HEADER]
        name = header[:16].decode("ascii", "replace").strip().rstrip("/")
        try:
            size = int(header[48:58].decode("ascii").strip())
        except ValueError as err:
            raise ValueError("Corrupt .ipk archive") from err
        pos += _AR_HEADER
        members[name] = data[pos : pos + size]
        pos += size + (size % 2)
    return members


def _control_fields(control_tar: bytes) -> dict[str, str]:
    with tarfile.open(fileobj=io.BytesIO(control_tar), mode="r:*") as tar:
        for member in tar:
            if member.isfile() and member.name.rsplit("/", 1)[-1] == "control":
                text = tar.extractfile(member).read().decode("utf-8", "replace")
                break
        else:
            raise ValueError(".ipk has no control file")
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def _appinfo(data_tar: bytes, package: str) -> dict:
    """appinfo.json of the package's main app (streamed, stops at the first match)."""
    wanted = f"usr/palm/applications/{package}/appinfo.json"
    fallback: dict | None = None
    with tarfile.open(fileobj=io.BytesIO(data_tar), mode="r|*") as tar:
        for member in tar:
            name = member.name.removeprefix("./")
            if not member.isfile() or not name.startswith("usr/palm/applications/"):
                continue
            if not name.endswith("/appinfo.json") or name.count("/") != 4:
                continue
            info = json.loads(tar.extractfile(member).read())
            if name == wanted:
                return info
            fallback = fallback or info
    if fallback is None:
        raise ValueError(".ipk contains no application")
    return fallback


def read_ipk_metadata(ipk: bytes) -> PackageMetadata:
    """Package id and version from the control file, app id and title from appinfo.json."""
    members = _ar_members(ipk)
    control = next((v for k, v in members.items() if k.startswith("control.tar")), None)
    data = next((v for k, v in members.items() if k.startswith("data.tar")), None)
    if control is None or data is None:
        raise ValueError("Not a webOS package (.ipk): control or data missing")
    try:
        fields = _control_fields(control)
        package = fields.get("Package", "")
        info = _appinfo(data, package)
    except (tarfile.TarError, OSError, json.JSONDecodeError) as err:
        raise ValueError(f"Not a valid webOS package: {err}") from err
    return PackageMetadata(
        version=str(info.get("version") or fields.get("Version", "")),
        package_id=package or info.get("id", ""),
        app_id=info.get("id", "") or package,
        required_version="",
        name=info.get("title", ""),
    )
