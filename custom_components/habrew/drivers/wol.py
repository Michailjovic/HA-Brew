"""Wake-on-LAN magic packet (no Home Assistant dependency)."""

from __future__ import annotations

import re
import socket


def normalize_mac(mac: str) -> str:
    """Return AA:BB:CC:DD:EE:FF or raise ValueError."""
    hexdigits = re.sub(r"[^0-9a-fA-F]", "", mac or "")
    if len(hexdigits) != 12:
        raise ValueError(f"Invalid MAC address: {mac!r}")
    return ":".join(hexdigits[i : i + 2] for i in range(0, 12, 2)).upper()


def send_magic_packet(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    """Send a WoL packet (blocking, run in an executor)."""
    payload = b"\xff" * 6 + bytes.fromhex(normalize_mac(mac).replace(":", "")) * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(payload, (broadcast, port))
