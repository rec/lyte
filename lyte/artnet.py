"""Art-Net transport for DMX universe frames."""

from __future__ import annotations

import socket

from pydantic import BaseModel, Field

from . import dmx

ARTNET_PORT = 6454
ARTNET_PROTOCOL_VERSION = 14


class ArtNetEndpoint(BaseModel, frozen=True):
    host: str = Field(min_length=1)
    port: int = Field(default=ARTNET_PORT, ge=1, le=65535)
    universe_offset: int = -1


class ArtNetDriver:
    def __init__(self, endpoint: ArtNetEndpoint) -> None:
        self.endpoint = endpoint
        self.sequence = 1
        self._socket: socket.socket | None = None

    def open(self) -> None:
        if self._socket is None:
            self._socket = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
            )

    def send(self, frames: dict[int, dmx.DmxFrame]) -> None:
        if self._socket is None:
            raise RuntimeError('Art-Net driver is not open')
        for universe in sorted(frames):
            frame = frames[universe]
            packet = artdmx_packet(
                frame,
                sequence=self.sequence,
                universe_offset=self.endpoint.universe_offset,
            )
            self._socket.sendto(packet, (self.endpoint.host, self.endpoint.port))
            self.sequence = 1 if self.sequence == 255 else self.sequence + 1

    def blackout(self, universes: list[int]) -> None:
        self.send({universe: dmx.blackout_frame(universe) for universe in universes})

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None


def artdmx_packet(
    frame: dmx.DmxFrame,
    sequence: int,
    universe_offset: int = -1,
    physical: int = 0,
) -> bytes:
    if sequence < 0 or sequence > 255:
        raise ValueError('Art-Net sequence must be between 0 and 255')
    if physical < 0 or physical > 255:
        raise ValueError('Art-Net physical port must be between 0 and 255')
    port_address = frame.universe + universe_offset
    if port_address < 0 or port_address > 32767:
        raise ValueError('Art-Net port address must be between 0 and 32767')
    slots = dmx.validate_slots(frame.slots)
    return b''.join(
        [
            b'Art-Net\x00',
            (0x5000).to_bytes(2, 'little'),
            ARTNET_PROTOCOL_VERSION.to_bytes(2),
            bytes([sequence, physical]),
            port_address.to_bytes(2, 'little'),
            len(slots).to_bytes(2),
            slots.tobytes(),
        ]
    )
