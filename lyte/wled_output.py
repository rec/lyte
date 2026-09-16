"""WLED DDP packet encoding and realtime output."""

from __future__ import annotations

import socket

import numpy as np
from numpy.typing import NDArray
from reccy.runtime import logging

from . import animation

_DDP_DATA_TYPE_RGB = 1
_DDP_VERSION = 0x40
_DDP_PUSH = 0x01
_DEFAULT_DDP_PAYLOAD_SIZE = 1440
LOGGER = logging.get_logger(__name__)


def encode_ddp_frame(
    frame: NDArray[np.uint8],
    *,
    sequence: int = 0,
    maximum_payload_size: int = _DEFAULT_DDP_PAYLOAD_SIZE,
) -> list[bytes]:
    animation.validate_byte_rgb_frame(animation.Device(led_count=len(frame)), frame)
    if not 0 <= sequence <= 255:
        raise ValueError('DDP sequence must be between 0 and 255')
    payload_size = maximum_payload_size - maximum_payload_size % 3
    if payload_size < 3:
        raise ValueError('DDP maximum payload size must contain at least one RGB LED')
    payload = frame.tobytes()
    packets = []
    for offset in range(0, len(payload), payload_size):
        chunk = payload[offset : offset + payload_size]
        flags = _DDP_VERSION | (_DDP_PUSH if offset + len(chunk) == len(payload) else 0)
        header = (
            bytes([flags, sequence, _DDP_DATA_TYPE_RGB, 0])
            + offset.to_bytes(4, 'big')
            + len(chunk).to_bytes(2, 'big')
        )
        packets.append(header + chunk)
    return packets


class WledDdpOutput:
    """A transient realtime WLED output. Its host is never persisted."""

    def __init__(
        self,
        host: str,
        led_count: int,
        socket_factory: type[socket.socket] = socket.socket,
    ) -> None:
        if not host:
            raise ValueError('WLED host must not be empty')
        self.host = host
        self.led_count = animation.Device(led_count=led_count).led_count
        self.socket = socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        self.frame_count = 0

    def send(self, frame: NDArray[np.uint8]) -> int:
        scaled = animation.scale_byte_rgb_frame(frame, self.led_count)
        packets = encode_ddp_frame(scaled, sequence=self.frame_count % 256)
        try:
            for packet in packets:
                self.socket.sendto(packet, (self.host, 4048))
        except OSError as error:
            LOGGER.error(f'[wled] DDP send to {self.host} failed: {error}')
            raise
        self.frame_count += 1
        LOGGER.debug(f'[wled] sent frame={self.frame_count} packets={len(packets)}')
        return len(packets)

    def close(self) -> None:
        self.socket.close()
