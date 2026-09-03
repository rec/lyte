"""Generation 2 realtime UDP frame sender."""

from __future__ import annotations

import base64
import binascii
import socket
from collections.abc import Iterable

import numpy as np
from numpy.typing import NDArray

from ..errors import ProtocolError

REALTIME_PORT = 7777
MAX_FRAGMENT_SIZE = 900


def frame_packets_v3(
    token: str,
    frame: NDArray[np.uint8],
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
    host: str, token: str, frame: NDArray[np.uint8], output: socket.socket | None = None
) -> int:
    if output is not None:
        return _send_frame_v3(output, host, token, frame)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        return _send_frame_v3(sock, host, token, frame)


def _send_frame_v3(
    output: socket.socket, host: str, token: str, frame: NDArray[np.uint8]
) -> int:
    sent = 0
    address = (host, REALTIME_PORT)
    for header, payload in frame_packets_v3(token, frame):
        sent += output.sendmsg([header, payload], [], 0, address)
    return sent


def frame_payload(frame: NDArray[np.uint8]) -> memoryview:
    if frame.dtype != np.uint8:
        raise ValueError('Realtime frames must have dtype uint8')
    if frame.ndim != 2 or frame.shape[1] != 3:
        raise ValueError('Realtime frames must have shape Nx3')
    if not frame.flags.c_contiguous:
        raise ValueError('Realtime frames must be C-contiguous')
    return memoryview(frame).cast('B')
