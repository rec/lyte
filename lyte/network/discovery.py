"""UDP discovery for Lyte devices."""

from __future__ import annotations

import ipaddress
import socket
import time
from collections.abc import Iterator

from pydantic import BaseModel

from ..errors import DiscoveryError

DISCOVERY_MESSAGE = b"\x01discover"
DISCOVERY_PORT = 5555
DEFAULT_BROADCAST = "255.255.255.255"


class DiscoveredDevice(BaseModel, frozen=True):
    ip_address: str
    device_id: str


def parse_discovery_response(data: bytes) -> DiscoveredDevice:
    if len(data) < 7:
        raise DiscoveryError(f"Discovery response is too short: {len(data)} bytes")
    if data[4:6] != b"OK":
        raise DiscoveryError(f"Discovery response status is not OK: {data[4:6]!r}")
    if data[-1:] != b"\x00":
        raise DiscoveryError("Discovery response is not NUL-terminated")

    ip_address = str(ipaddress.ip_address(data[3::-1]))
    device_id = data[6:-1].decode()
    return DiscoveredDevice(ip_address=ip_address, device_id=device_id)


def discover(
    timeout: float = 5.0,
    destination: str = DEFAULT_BROADCAST,
) -> Iterator[DiscoveredDevice]:
    deadline = time.monotonic() + timeout
    seen: set[str] = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(min(timeout, 0.5))
        sock.bind(("", 0))
        sock.sendto(DISCOVERY_MESSAGE, (destination, DISCOVERY_PORT))
        while time.monotonic() < deadline:
            try:
                data, _address = sock.recvfrom(256)
            except TimeoutError:
                continue
            if data == DISCOVERY_MESSAGE:
                continue
            device = parse_discovery_response(data)
            if device.ip_address in seen:
                continue
            seen.add(device.ip_address)
            yield device
