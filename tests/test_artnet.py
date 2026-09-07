from __future__ import annotations

from unittest.mock import patch

import numpy as np

from lyte import artnet, dmx


def test_artdmx_packet_contains_universe_and_slots() -> None:
    slots = np.arange(dmx.DMX_CHANNEL_COUNT, dtype=np.uint16).astype(np.uint8)
    frame = dmx.DmxFrame(universe=1, slots=slots)

    packet = artnet.artdmx_packet(frame, sequence=7)

    assert packet[:8] == b'Art-Net\x00'
    assert packet[8:10] == b'\x00P'
    assert packet[10:12] == b'\x00\x0e'
    assert packet[12:14] == b'\x07\x00'
    assert packet[14:16] == b'\x00\x00'
    assert packet[16:18] == b'\x02\x00'
    assert packet[18:] == slots.tobytes()


def test_artnet_driver_sends_frames_and_blackout() -> None:
    output = patch('lyte.artnet.socket.socket').start()
    try:
        driver = artnet.ArtNetDriver(artnet.ArtNetEndpoint(host='192.168.1.50'))
        driver.open()
        driver.send({1: dmx.blackout_frame(1)})
        driver.blackout([1])
        driver.close()
    finally:
        patch.stopall()

    socket_instance = output.return_value
    assert socket_instance.sendto.call_count == 2
    first_packet, address = socket_instance.sendto.call_args_list[0].args
    assert address == ('192.168.1.50', artnet.ARTNET_PORT)
    assert first_packet[12] == 1
    assert socket_instance.sendto.call_args_list[1].args[0][12] == 2
    assert socket_instance.sendto.call_args_list[1].args[0][18:] == bytes(512)
    socket_instance.close.assert_called_once_with()
