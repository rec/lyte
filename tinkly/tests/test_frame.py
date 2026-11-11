from __future__ import annotations

import unittest
from array import array
from collections.abc import Sized
from unittest.mock import patch

from tinkly.errors import ProtocolError
from tinkly.frame import frame_packets_v3, frame_payload, send_frame_v3


class RealtimeFrameTests(unittest.TestCase):
    def test_generation_2_v3_packet(self) -> None:
        frame = bytes((230, 85, 0)) * 250

        packets = list(frame_packets_v3('MCIGBF1qJlg=', frame))

        self.assertEqual(len(packets), 1)
        header, payload = packets[0]
        self.assertIs(payload.obj, frame)
        self.assertEqual(header, b'\x030"\x06\x04]j&X\x00\x00\x00')
        self.assertEqual(
            bytes(payload),
            b'\xe6U\x00' * 250,
        )

    def test_generation_2_v3_fragments_large_frames(self) -> None:
        frame = b'a' * 903

        packets = list(frame_packets_v3('MCIGBF1qJlg=', frame))

        self.assertEqual(len(packets), 2)
        self.assertEqual(packets[0][0], b'\x030"\x06\x04]j&X\x00\x00\x00')
        self.assertEqual(packets[1][0], b'\x030"\x06\x04]j&X\x00\x00\x01')
        self.assertEqual(len(packets[0][1]), 900)
        self.assertEqual(bytes(packets[1][1]), b'aaa')

    def test_rejects_incomplete_rgb_pixel(self) -> None:
        with self.assertRaises(ValueError):
            frame_payload(b'\x00\x01')

    def test_accepts_unsigned_byte_buffers_without_copying(self) -> None:
        for frame in (b'\x01\x02\x03', bytearray((1, 2, 3)), array('B', (1, 2, 3))):
            with self.subTest(buffer_type=type(frame)):
                payload = frame_payload(frame)
                self.assertIs(payload.obj, frame)
                self.assertEqual(bytes(payload), b'\x01\x02\x03')

    def test_accepts_multidimensional_memoryview(self) -> None:
        frame = memoryview(b'\x01\x02\x03' * 2).cast('B', shape=(2, 3))
        self.assertEqual(bytes(frame_payload(frame)), b'\x01\x02\x03' * 2)

    def test_rejects_non_byte_elements(self) -> None:
        with self.assertRaises(ValueError):
            frame_payload(array('H', (1, 2, 3)))

    def test_rejects_noncontiguous_buffers(self) -> None:
        with self.assertRaises(ValueError):
            frame_payload(memoryview(b'123456')[::2])

    def test_send_frame_uses_array_payload_buffer(self) -> None:
        frame = array('B', (1, 2, 3))
        sent_buffers = []

        class Socket:
            def __enter__(self) -> Socket:
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def sendmsg(
                self,
                buffers: list[Sized],
                flags: list[object],
                mode: int,
                address: tuple[str, int],
            ) -> int:
                sent_buffers.append((buffers, flags, mode, address))
                return sum(len(buffer) for buffer in buffers)

        with patch('tinkly.frame.socket.socket', return_value=Socket()):
            sent = send_frame_v3('192.168.1.23', 'MCIGBF1qJlg=', frame)

        self.assertEqual(sent, 15)
        buffers, flags, mode, address = sent_buffers[0]
        self.assertEqual(flags, [])
        self.assertEqual(mode, 0)
        self.assertEqual(address, ('192.168.1.23', 7777))
        self.assertEqual(buffers[0], b'\x030"\x06\x04]j&X\x00\x00\x00')
        self.assertIs(buffers[1].obj, frame)

    def test_send_frame_uses_given_output(self) -> None:
        frame = b'\x01\x02\x03'
        sent_buffers = []

        class Socket:
            def sendmsg(
                self,
                buffers: list[Sized],
                flags: list[object],
                mode: int,
                address: tuple[str, int],
            ) -> int:
                sent_buffers.append((buffers, flags, mode, address))
                return sum(len(buffer) for buffer in buffers)

        output = Socket()
        with patch('tinkly.frame.socket.socket') as create_socket:
            sent = send_frame_v3('192.168.1.23', 'MCIGBF1qJlg=', frame, output)

        self.assertEqual(sent, 15)
        create_socket.assert_not_called()
        self.assertEqual(len(sent_buffers), 1)

    def test_rejects_bad_realtime_token(self) -> None:
        with self.assertRaises(ProtocolError):
            list(frame_packets_v3('bad', b'\x00\x00\x00'))
