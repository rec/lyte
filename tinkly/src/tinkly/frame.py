"""Generation 2 realtime UDP frame sender."""

from __future__ import annotations

import base64
import binascii
import socket
from collections.abc import Buffer, Iterable

from .errors import ProtocolError

REALTIME_PORT = 7777
MAX_FRAGMENT_SIZE = 900


def frame_packets_v3(
    token: str,
    frame: Buffer,
) -> Iterable[tuple[bytes, memoryview]]:
    try:
        raw_token = base64.b64decode(token, validate=True)
    except binascii.Error as err:
        raise ProtocolError('Twinkly realtime token is not valid base64') from err
    if len(raw_token) != 8:
        raise ProtocolError('Twinkly realtime token must decode to 8 bytes')
    payload = frame_payload(frame)
    for index, start in enumerate(range(0, len(payload), MAX_FRAGMENT_SIZE)):
        fragment = payload[start : start + MAX_FRAGMENT_SIZE]
        if index > 255:
            raise ProtocolError(
                'Realtime frame is too large for one-byte fragment numbers'
            )
        yield b'\x03' + raw_token + b'\x00\x00' + bytes((index,)), fragment


def send_frame_v3(
    host: str, token: str, frame: Buffer, output: socket.socket | None = None
) -> int:
    if output is not None:
        return _send_frame_v3(output, host, token, frame)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        return _send_frame_v3(sock, host, token, frame)


def _send_frame_v3(output: socket.socket, host: str, token: str, frame: Buffer) -> int:
    sent = 0
    address = (host, REALTIME_PORT)
    for header, payload in frame_packets_v3(token, frame):
        sent += output.sendto(b''.join((header, payload)), address)
    return sent


def frame_payload(frame: Buffer) -> memoryview:
    """Expose contiguous unsigned RGB bytes without copying the frame."""
    view = memoryview(frame)
    if view.format != 'B':
        raise ValueError('Realtime frames must contain unsigned bytes')
    if not view.c_contiguous:
        raise ValueError('Realtime frames must be C-contiguous')
    payload = view.cast('B')
    if len(payload) % 3:
        raise ValueError('Realtime frames must contain three bytes per LED')
    return payload
