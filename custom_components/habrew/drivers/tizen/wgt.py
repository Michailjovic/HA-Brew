"""Reading metadata from Tizen web widget (.wgt) packages."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree as ET

TIZEN_NS = "{http://tizen.org/ns/widgets}"


@dataclass(frozen=True)
class WgtMetadata:
    """Identifiers and version declared in a widget's config.xml."""

    version: str
    package_id: str
    app_id: str
    required_version: str
    name: str


def read_wgt_metadata(wgt: bytes) -> WgtMetadata:
    """Parse config.xml of a .wgt package."""
    try:
        with zipfile.ZipFile(io.BytesIO(wgt)) as zf:
            root = ET.fromstring(zf.read("config.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as err:
        raise ValueError(f"Not a valid Tizen widget package: {err}") from err
    app = root.find(f"{TIZEN_NS}application")
    if app is None:
        raise ValueError("config.xml does not contain tizen:application")
    name_el = root.find("{http://www.w3.org/ns/widgets}name")
    return WgtMetadata(
        version=root.get("version", ""),
        package_id=app.get("package", ""),
        app_id=app.get("id", ""),
        required_version=app.get("required_version", ""),
        name=(name_el.text or "").strip() if name_el is not None else "",
    )
