"""Generation 2 realtime UDP frame sender."""

from __future__ import annotations

import base64
import binascii
import socket
from typing import Iterable

from .errors import ProtocolError


REALTIME_PORT = 7777
MAX_FRAGMENT_SIZE = 900


def solid_rgb_frame(led_count: int, red: int, green: int, blue: int) -> bytes:
    if led_count <= 0:
        raise ValueError("led_count must be greater than zero")
    for value in (red, green, blue):
        if value < 0 or value > 255:
            raise ValueError("RGB values must be between 0 and 255")
    return bytes((red, green, blue)) * led_count


def frame_packets_v3(token: str, frame: bytes) -> Iterable[bytes]:
    try:
        raw_token = base64.b64decode(token, validate=True)
    except binascii.Error as err:
        raise ProtocolError("Twinkly realtime token is not valid base64") from err
    if len(raw_token) != 8:
        raise ProtocolError("Twinkly realtime token must decode to 8 bytes")
    for index, start in enumerate(range(0, len(frame), MAX_FRAGMENT_SIZE)):
        fragment = frame[start : start + MAX_FRAGMENT_SIZE]
        if index > 255:
            raise ProtocolError(
                "Realtime frame is too large for one-byte fragment numbers"
            )
        yield b"\x03" + raw_token + b"\x00\x00" + bytes((index,)) + fragment


def send_frame_v3(host: str, token: str, frame: bytes) -> int:
    sent = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        for packet in frame_packets_v3(token, frame):
            sent += sock.sendto(packet, (host, REALTIME_PORT))
    return sent
