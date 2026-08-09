from __future__ import annotations

# ruff: noqa: I001

import importlib
import io
import json
import tempfile
import unittest
from collections.abc import Sized
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import numpy as np
from numpy import testing as npt

from lyte import animation, cli
from lyte.animations.colors import solid_rgb_frame
from lyte.errors import DiscoveryError, ProtocolError, UnsupportedEndpointError
from lyte.retry import RetryConfig
from lyte.twinkly import diagnostic
from lyte.twinkly import inputs
from lyte.twinkly import layout
from lyte.twinkly import media
from lyte.twinkly import mode
from lyte.twinkly import networking
from lyte.twinkly import output
from lyte.twinkly import session
from lyte.twinkly import timer
from lyte.twinkly.authentication import CHALLENGE_KEY, derive_key, mac_bytes, rc4
from lyte.twinkly.client import TWINKLY_API_PREFIX, TwinklyClient, TwinklyResponse
from lyte.twinkly.discovery import DiscoveredDevice, parse_discovery_response
from lyte.twinkly.frame import frame_packets_v3, frame_payload, send_frame_v3

COMMAND = 'lyte.twinkly.command'
OUTPUT = 'lyte.twinkly.output'
DIAGNOSTIC = 'lyte.twinkly.diagnostic'


class DiscoveryTests(unittest.TestCase):
    def test_parse_discovery_response(self) -> None:
        device = parse_discovery_response(b'\xab\x01\xa8\xc0OKTwinkly_A1234B\x00')

        self.assertEqual(device.ip_address, '192.168.1.171')
        self.assertEqual(device.device_id, 'Twinkly_A1234B')

    def test_rejects_bad_discovery_response(self) -> None:
        with self.assertRaises(DiscoveryError):
            parse_discovery_response(b'\xab\x01\xa8\xc0NOTwinkly_A1234B\x00')


class CryptoTests(unittest.TestCase):
    def test_mac_bytes_accepts_common_formats(self) -> None:
        expected = b'\x5c\xcf\x7f\x33\xaa\xff'

        self.assertEqual(mac_bytes('5C:CF:7F:33:AA:FF'), expected)
        self.assertEqual(mac_bytes('5c-cf-7f-33-aa-ff'), expected)
        self.assertEqual(mac_bytes('5ccf7f33aaff'), expected)

    def test_derive_key_matches_original_driver(self) -> None:
        key = derive_key(CHALLENGE_KEY, '5C:CF:7F:33:AA:FF')

        self.assertEqual(key, b'9\xb9\x1a]\xc7\x90.\xaa\x0cV\xc9\x8d9\xbb^\x12')

    def test_rc4_known_vector(self) -> None:
        self.assertEqual(rc4(b'Plaintext', b'Key').hex(), 'bbf316e8d940af0ad3')


class RealtimeTests(unittest.TestCase):
    def test_solid_rgb_frame(self) -> None:
        npt.assert_array_equal(
            solid_rgb_frame(3, 230, 85, 0),
            np.array([[230, 85, 0], [230, 85, 0], [230, 85, 0]], dtype=np.uint8),
        )

    def test_solid_float_light_frame(self) -> None:
        npt.assert_array_equal(
            animation.solid_float_light_frame(2, (1.0, 0.5, 0.0, 0.25)),
            np.array(
                [[1.0, 0.5, 0.0, 0.25], [1.0, 0.5, 0.0, 0.25]],
                dtype=np.float32,
            ),
        )

    def test_validate_float_light_frame_checks_shape_dtype_and_finiteness(
        self,
    ) -> None:
        frame = np.zeros((2, 3), dtype=np.float32)

        self.assertIs(animation.validate_float_light_frame(2, 3, frame), frame)
        with self.assertRaisesRegex(ValueError, 'dtype float32'):
            animation.validate_float_light_frame(2, 3, frame.astype(np.float64))
        with self.assertRaisesRegex(ValueError, 'shape light_count x light channels'):
            animation.validate_float_light_frame(2, 4, frame)
        with self.assertRaisesRegex(ValueError, 'finite'):
            animation.validate_float_light_frame(
                1,
                3,
                np.array([[np.nan, 0.0, 0.0]], dtype=np.float32),
            )
        with self.assertRaisesRegex(ValueError, 'C-contiguous'):
            animation.validate_float_light_frame(
                2, 3, np.zeros((3, 2), dtype=np.float32).T
            )

    def test_byte_light_frame_from_float_clips_rounds_and_contiguates(self) -> None:
        frame = np.array(
            [
                [-0.25, 0.0, 0.5],
                [1.0, 1.25, 128 / 255],
            ],
            dtype=np.float32,
        ).T

        encoded = animation.byte_light_frame_from_float(frame)

        npt.assert_array_equal(
            encoded,
            np.array([[0, 255], [0, 255], [128, 128]], dtype=np.uint8),
        )
        self.assertTrue(encoded.flags.c_contiguous)

    def test_float_rgb_helpers_convert_at_byte_boundary(self) -> None:
        self.assertEqual(
            animation.float_color_from_rgb((255, 128, 0)), (1.0, 128 / 255, 0.0)
        )
        self.assertEqual(
            animation.rgb_from_float_color((1.25, 0.5, -0.25)), (255, 128, 0)
        )

    def test_generation_2_v3_packet(self) -> None:
        frame = solid_rgb_frame(250, 230, 85, 0)

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
        frame = np.frombuffer(b'a' * 903, dtype=np.uint8).reshape((301, 3))

        packets = list(frame_packets_v3('MCIGBF1qJlg=', frame))

        self.assertEqual(len(packets), 2)
        self.assertEqual(packets[0][0], b'\x030"\x06\x04]j&X\x00\x00\x00')
        self.assertEqual(packets[1][0], b'\x030"\x06\x04]j&X\x00\x00\x01')
        self.assertEqual(len(packets[0][1]), 900)
        self.assertEqual(bytes(packets[1][1]), b'aaa')

    def test_rejects_bad_frame_shape(self) -> None:
        with self.assertRaises(ValueError):
            frame_payload(np.zeros((9,), dtype=np.uint8))

    def test_send_frame_uses_array_payload_buffer(self) -> None:
        frame = solid_rgb_frame(1, 1, 2, 3)
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

        with patch('lyte.twinkly.frame.socket.socket', return_value=Socket()):
            sent = send_frame_v3('192.168.1.23', 'MCIGBF1qJlg=', frame)

        self.assertEqual(sent, 15)
        buffers, flags, mode, address = sent_buffers[0]
        self.assertEqual(flags, [])
        self.assertEqual(mode, 0)
        self.assertEqual(address, ('192.168.1.23', 7777))
        self.assertEqual(buffers[0], b'\x030"\x06\x04]j&X\x00\x00\x00')
        self.assertIs(buffers[1].obj, frame)

    def test_rejects_bad_realtime_token(self) -> None:
        with self.assertRaises(ProtocolError):
            list(frame_packets_v3('bad', solid_rgb_frame(1, 0, 0, 0)))


class FpsTestTests(unittest.TestCase):
    def test_cli_animate_command_dispatches_animation(self) -> None:
        with patch.object(cli, 'run_animate', return_value=0) as run_animate:
            result = cli.main(
                [
                    'animate',
                    'rainbow',
                    '--duration',
                    '1.5',
                    '--fps',
                    '30',
                ]
            )

        self.assertEqual(result, 0)
        config = run_animate.call_args.args[0]
        self.assertEqual(config.animation, 'rainbow')
        self.assertEqual(config.duration, 1.5)
        self.assertEqual(config.fps, 30)

    def test_cli_preview_command_dispatches_preview(self) -> None:
        with patch.object(cli, 'run_preview', return_value=0) as run_preview:
            result = cli.main(
                [
                    'preview',
                    'rainbow',
                    'preview.html',
                    '--width',
                    '24',
                    '--duration',
                    '1.5',
                ]
            )

        self.assertEqual(result, 0)
        config = run_preview.call_args.args[0]
        self.assertEqual(config.animation, 'rainbow')
        self.assertEqual(config.output, Path('preview.html'))
        self.assertEqual(config.width, 24)
        self.assertEqual(config.duration, 1.5)

    def test_cli_preview_command_lists_patterns_without_arguments(self) -> None:
        output = io.StringIO()

        with patch('sys.stdout', output):
            result = cli.main(['preview'])

        self.assertEqual(result, 0)
        self.assertIn('color_fill\n', output.getvalue())
        self.assertIn('rainbow\n', output.getvalue())
        self.assertNotIn('off\n', output.getvalue())

    def test_cli_test_command_dispatches_fps_test(self) -> None:
        with patch.object(cli.fps_test, 'run_fps_test', return_value=0) as run_fps_test:
            result = cli.main(
                [
                    'test',
                    '--host',
                    '192.168.1.23',
                    '--led-count',
                    '10',
                    '--duration',
                    '1.5',
                ]
            )

        self.assertEqual(result, 0)
        config = run_fps_test.call_args.args[0]
        self.assertEqual(config.host, '192.168.1.23')
        self.assertEqual(config.led_count, 10)
        self.assertEqual(config.duration, 1.5)

    def test_cli_test2_command_dispatches_temporal_dither_test(self) -> None:
        with patch.object(
            cli.fps_test, 'run_temporal_dither_test', return_value=0
        ) as run_temporal_dither_test:
            result = cli.main(
                [
                    'test2',
                    '--host',
                    '192.168.1.23',
                    '--led-count',
                    '10',
                    '--time',
                    '4.5',
                ]
            )

        self.assertEqual(result, 0)
        config = run_temporal_dither_test.call_args.args[0]
        self.assertEqual(config.host, '192.168.1.23')
        self.assertEqual(config.led_count, 10)
        self.assertEqual(config.time, 4.5)

    def test_cli_show_command_dispatches_show_validation(self) -> None:
        with patch.object(cli.show, 'run_show', return_value=0) as run_show:
            result = cli.main(['show', 'first.toml', 'second.toml'])

        self.assertEqual(result, 0)
        config = run_show.call_args.args[0]
        self.assertEqual(config.files, [Path('first.toml'), Path('second.toml')])

    def test_cli_black_floor_command_dispatches_black_floor_test(self) -> None:
        with patch.object(
            cli.fps_test, 'run_black_floor_test', return_value=0
        ) as run_black_floor_test:
            result = cli.main(
                [
                    'black-floor',
                    '--host',
                    '192.168.1.23',
                    '--led-count',
                    '10',
                ]
            )

        self.assertEqual(result, 0)
        config = run_black_floor_test.call_args.args[0]
        self.assertEqual(config.host, '192.168.1.23')
        self.assertEqual(config.led_count, 10)

    def test_cli_verify_command_dispatches_verify_test(self) -> None:
        with patch.object(
            cli.fps_test, 'run_verify_test', return_value=0
        ) as run_verify_test:
            result = cli.main(
                [
                    'verify',
                    '--host',
                    '192.168.1.23',
                    '--led-count',
                    '10',
                    '--mode',
                    'slow',
                ]
            )

        self.assertEqual(result, 0)
        config = run_verify_test.call_args.args[0]
        self.assertEqual(config.host, '192.168.1.23')
        self.assertEqual(config.led_count, 10)
        self.assertEqual(config.mode, 'slow')

    def test_cli_diagnostic_command_dispatches_diagnostic(self) -> None:
        with patch.object(
            cli.diagnostic, 'run_diagnostic_command', return_value=0
        ) as run_diagnostic_command:
            result = cli.main(
                [
                    'diagnostic',
                    '--host',
                    '192.168.1.23',
                    '--attempts',
                    '2',
                ]
            )

        self.assertEqual(result, 0)
        config = run_diagnostic_command.call_args.args[0]
        self.assertEqual(config.host, '192.168.1.23')
        self.assertEqual(config.attempts, 2)

    def test_cli_diagnostic_realtime_flag_dispatches_diagnostic(self) -> None:
        with patch.object(
            cli.diagnostic, 'run_diagnostic_command', return_value=0
        ) as run_diagnostic_command:
            result = cli.main(
                [
                    'diagnostic',
                    '--realtime',
                    '--led-count',
                    '10',
                    '--pause',
                    '0.1',
                ]
            )

        self.assertEqual(result, 0)
        config = run_diagnostic_command.call_args.args[0]
        self.assertTrue(config.realtime)
        self.assertEqual(config.led_count, 10)
        self.assertEqual(config.pause, 0.1)

    def test_cli_brightness_command_dispatches_output_control(self) -> None:
        with patch.object(
            cli.output, 'run_output_control', return_value=0
        ) as run_output_control:
            result = cli.main(
                [
                    'brightness',
                    'set',
                    '75',
                    '--host',
                    '192.168.1.23',
                ]
            )

        self.assertEqual(result, 0)
        config, kind, action, value = run_output_control.call_args.args
        self.assertEqual(config.host, '192.168.1.23')
        self.assertEqual(kind, 'brightness')
        self.assertEqual(action, 'set')
        self.assertEqual(value, 75)

    def test_cli_saturation_command_dispatches_output_control(self) -> None:
        with patch.object(
            cli.output, 'run_output_control', return_value=0
        ) as run_output_control:
            result = cli.main(
                [
                    'saturation',
                    'get',
                    '--host',
                    '192.168.1.23',
                ]
            )

        self.assertEqual(result, 0)
        config, kind, action, value = run_output_control.call_args.args
        self.assertEqual(config.host, '192.168.1.23')
        self.assertEqual(kind, 'saturation')
        self.assertEqual(action, 'get')
        self.assertIsNone(value)

    def test_cli_mode_command_dispatches_mode_control(self) -> None:
        with patch.object(
            cli.mode, 'run_mode_control', return_value=0
        ) as run_mode_control:
            result = cli.main(['mode', 'set', 'demo'])

        self.assertEqual(result, 0)
        config, action, mode = run_mode_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'set')
        self.assertEqual(mode, 'demo')

    def test_cli_color_command_dispatches_color_control(self) -> None:
        with patch.object(
            cli.mode, 'run_color_control', return_value=0
        ) as run_color_control:
            result = cli.main(['color', 'set', '1', '2', '3'])

        self.assertEqual(result, 0)
        config, action, red, green, blue = run_color_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'set')
        self.assertEqual((red, green, blue), (1, 2, 3))

    def test_cli_effects_command_dispatches_effect_control(self) -> None:
        with patch.object(
            cli.mode, 'run_effect_control', return_value=0
        ) as run_effect_control:
            result = cli.main(['effects', 'set-current', '4'])

        self.assertEqual(result, 0)
        config, action, effect_id = run_effect_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'set-current')
        self.assertEqual(effect_id, 4)

    def test_cli_layout_command_dispatches_layout_control(self) -> None:
        with patch.object(
            cli.layout, 'run_layout_control', return_value=0
        ) as run_layout_control:
            result = cli.main(['layout', 'export', 'layout.json'])

        self.assertEqual(result, 0)
        config, action, path = run_layout_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'export')
        self.assertEqual(path, Path('layout.json'))

    def test_cli_led_config_command_dispatches_led_config_control(self) -> None:
        with patch.object(
            cli.layout, 'run_led_config_control', return_value=0
        ) as run_led_config_control:
            result = cli.main(['led-config', 'set', 'config.json'])

        self.assertEqual(result, 0)
        config, action, path = run_led_config_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'set')
        self.assertEqual(path, Path('config.json'))

    def test_cli_timer_command_dispatches_timer_control(self) -> None:
        with patch.object(
            cli.timer, 'run_timer_control', return_value=0
        ) as run_timer_control:
            result = cli.main(['timer', 'set', '3600', '7200', '--time-now', '1800'])

        self.assertEqual(result, 0)
        config, action, time_on, time_off, time_now = run_timer_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'set')
        self.assertEqual(time_on, 3600)
        self.assertEqual(time_off, 7200)
        self.assertEqual(time_now, 1800)

    def test_cli_movie_command_dispatches_movie_control(self) -> None:
        with patch.object(
            cli.media, 'run_movie_control', return_value=0
        ) as run_movie_control:
            result = cli.main(['movie', 'current'])

        self.assertEqual(result, 0)
        config, action = run_movie_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'current')

    def test_cli_playlist_command_dispatches_playlist_control(self) -> None:
        with patch.object(
            cli.media, 'run_playlist_control', return_value=0
        ) as run_playlist_control:
            result = cli.main(['playlist', 'current'])

        self.assertEqual(result, 0)
        config, action = run_playlist_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'current')

    def test_cli_network_command_dispatches_network_control(self) -> None:
        with patch.object(
            cli.networking, 'run_network_control', return_value=0
        ) as run_network_control:
            result = cli.main(['network', 'scan-results'])

        self.assertEqual(result, 0)
        config, action = run_network_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'scan-results')

    def test_cli_mqtt_command_dispatches_mqtt_control(self) -> None:
        with patch.object(
            cli.inputs, 'run_mqtt_control', return_value=0
        ) as run_mqtt_control:
            result = cli.main(['mqtt', 'config'])

        self.assertEqual(result, 0)
        config, action = run_mqtt_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'config')

    def test_cli_mic_command_dispatches_mic_control(self) -> None:
        with patch.object(
            cli.inputs, 'run_mic_control', return_value=0
        ) as run_mic_control:
            result = cli.main(['mic', 'sample'])

        self.assertEqual(result, 0)
        config, action = run_mic_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'sample')

    def test_cli_music_command_dispatches_music_control(self) -> None:
        with patch.object(
            cli.inputs, 'run_music_control', return_value=0
        ) as run_music_control:
            result = cli.main(['music', 'current-driver-set'])

        self.assertEqual(result, 0)
        config, action = run_music_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'current-driver-set')


class FakeHttpResponse:
    def __init__(self, status: int, raw: bytes) -> None:
        self.status = status
        self.raw = raw

    def read(self) -> bytes:
        return self.raw


class FakeHttpConnection:
    response = FakeHttpResponse(200, b'{}')
    requests: list[
        tuple[str, int, float, str, str, bytes | None, dict[str, str] | None]
    ] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def request(
        self,
        method: str,
        url: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.requests.append(
            (self.host, self.port, self.timeout, method, url, body, headers)
        )

    def getresponse(self) -> FakeHttpResponse:
        return self.response

    def close(self) -> None:
        return None


class ClientTests(unittest.TestCase):
    def test_constructs_with_keyword_arguments(self) -> None:
        client = TwinklyClient(host='192.168.1.23', timeout=1.5)

        self.assertEqual(client.host, '192.168.1.23')
        self.assertEqual(client.timeout, 1.5)

    def test_delete_uses_delete_request(self) -> None:
        FakeHttpConnection.response = FakeHttpResponse(200, b'{"code":1000}')
        FakeHttpConnection.requests = []

        with patch('lyte.twinkly.client.client.HTTPConnection', FakeHttpConnection):
            response = TwinklyClient(host='192.168.1.23').delete(
                'movies', authenticated=False
            )

        self.assertEqual(response.data, {'code': 1000})
        self.assertEqual(
            FakeHttpConnection.requests,
            [
                (
                    '192.168.1.23',
                    80,
                    5.0,
                    'DELETE',
                    f'{TWINKLY_API_PREFIX}/movies',
                    None,
                    {'Content-Type': 'application/json'},
                )
            ],
        )

    def test_post_bytes_sends_binary_payload(self) -> None:
        FakeHttpConnection.response = FakeHttpResponse(200, b'{"code":1000}')
        FakeHttpConnection.requests = []

        with patch('lyte.twinkly.client.client.HTTPConnection', FakeHttpConnection):
            response = TwinklyClient(host='192.168.1.23').post_bytes(
                'movies/full',
                b'\x01\x02\x03',
                'application/octet-stream',
                authenticated=False,
            )

        self.assertEqual(response.data, {'code': 1000})
        self.assertEqual(
            FakeHttpConnection.requests,
            [
                (
                    '192.168.1.23',
                    80,
                    5.0,
                    'POST',
                    f'{TWINKLY_API_PREFIX}/movies/full',
                    b'\x01\x02\x03',
                    {
                        'Content-Type': 'application/octet-stream',
                        'Content-Length': '3',
                    },
                )
            ],
        )

    def test_request_rejects_json_body_and_binary_payload(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with self.assertRaisesRegex(ValueError, 'both JSON body and binary payload'):
            client.request(
                'POST',
                'movies/full',
                body={'code': 1000},
                payload=b'\x00',
                authenticated=False,
            )

    def test_404_raises_unsupported_endpoint_error(self) -> None:
        FakeHttpConnection.response = FakeHttpResponse(404, b'{"code":1101}')
        FakeHttpConnection.requests = []

        with (
            patch('lyte.twinkly.client.client.HTTPConnection', FakeHttpConnection),
            self.assertRaises(UnsupportedEndpointError) as raised,
        ):
            TwinklyClient(host='192.168.1.23').get('missing', authenticated=False)

        self.assertEqual(raised.exception.path, 'missing')
        self.assertEqual(raised.exception.text, '{"code":1101}')

    def test_firmware_version_and_status_default_to_unauthenticated_gets(self) -> None:
        calls = []

        def get(
            self: TwinklyClient,
            path: str,
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append((self.host, path, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        client = TwinklyClient(host='192.168.1.23')

        with patch.object(TwinklyClient, 'get', get):
            client.get_firmware_version()
            client.get_status()

        self.assertEqual(
            calls,
            [
                ('192.168.1.23', 'fw/version', False),
                ('192.168.1.23', 'status', False),
            ],
        )

    def test_device_name_summary_and_echo_use_documented_paths(self) -> None:
        calls = []

        def get(
            self: TwinklyClient,
            path: str,
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append(('GET', self.host, path, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        def post(
            self: TwinklyClient,
            path: str,
            body: dict[str, object],
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append(('POST', self.host, path, body, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        client = TwinklyClient(host='192.168.1.23')

        with (
            patch.object(TwinklyClient, 'get', get),
            patch.object(TwinklyClient, 'post', post),
        ):
            client.get_device_name()
            client.get_summary()
            client.echo({'message': 'hello'})

        self.assertEqual(
            calls,
            [
                ('GET', '192.168.1.23', 'device_name', True),
                ('GET', '192.168.1.23', 'summary', True),
                ('POST', '192.168.1.23', 'echo', {'message': 'hello'}, True),
            ],
        )

    def test_brightness_and_saturation_use_documented_paths(self) -> None:
        calls = []

        def get(
            self: TwinklyClient,
            path: str,
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append(('GET', self.host, path, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'value': 100})

        def post(
            self: TwinklyClient,
            path: str,
            body: dict[str, object],
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append(('POST', self.host, path, body, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        client = TwinklyClient(host='192.168.1.23')

        with (
            patch.object(TwinklyClient, 'get', get),
            patch.object(TwinklyClient, 'post', post),
        ):
            client.get_brightness()
            client.set_brightness({'mode': 'enabled', 'type': 'A', 'value': 75})
            client.get_saturation()
            client.set_saturation({'mode': 'enabled', 'type': 'A', 'value': 80})

        self.assertEqual(
            calls,
            [
                ('GET', '192.168.1.23', 'led/out/brightness', True),
                (
                    'POST',
                    '192.168.1.23',
                    'led/out/brightness',
                    {'mode': 'enabled', 'type': 'A', 'value': 75},
                    True,
                ),
                ('GET', '192.168.1.23', 'led/out/saturation', True),
                (
                    'POST',
                    '192.168.1.23',
                    'led/out/saturation',
                    {'mode': 'enabled', 'type': 'A', 'value': 80},
                    True,
                ),
            ],
        )

    def test_mode_color_and_effects_use_documented_paths(self) -> None:
        calls = []

        def get(
            self: TwinklyClient,
            path: str,
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append(('GET', self.host, path, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        def post(
            self: TwinklyClient,
            path: str,
            body: dict[str, object],
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append(('POST', self.host, path, body, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        client = TwinklyClient(host='192.168.1.23')

        with (
            patch.object(TwinklyClient, 'get', get),
            patch.object(TwinklyClient, 'post', post),
        ):
            client.get_led_mode()
            client.set_led_mode({'mode': 'demo'})
            client.get_led_color()
            client.set_led_color({'mode': 'rgb', 'red': 1, 'green': 2, 'blue': 3})
            client.get_effects()
            client.get_current_effect()
            client.set_current_effect({'effect_id': 4})

        self.assertEqual(
            calls,
            [
                ('GET', '192.168.1.23', 'led/mode', True),
                ('POST', '192.168.1.23', 'led/mode', {'mode': 'demo'}, True),
                ('GET', '192.168.1.23', 'led/color', True),
                (
                    'POST',
                    '192.168.1.23',
                    'led/color',
                    {'mode': 'rgb', 'red': 1, 'green': 2, 'blue': 3},
                    True,
                ),
                ('GET', '192.168.1.23', 'led/effects', True),
                ('GET', '192.168.1.23', 'led/effects/current', True),
                (
                    'POST',
                    '192.168.1.23',
                    'led/effects/current',
                    {'effect_id': 4},
                    True,
                ),
            ],
        )

    def test_layout_and_led_config_use_documented_paths(self) -> None:
        calls = []

        def get(
            self: TwinklyClient,
            path: str,
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append(('GET', self.host, path, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        def post(
            self: TwinklyClient,
            path: str,
            body: dict[str, object],
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append(('POST', self.host, path, body, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        def delete(
            self: TwinklyClient,
            path: str,
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append(('DELETE', self.host, path, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        client = TwinklyClient(host='192.168.1.23')

        with (
            patch.object(TwinklyClient, 'get', get),
            patch.object(TwinklyClient, 'post', post),
            patch.object(TwinklyClient, 'delete', delete),
        ):
            client.get_layout_full()
            client.set_layout_full({'source': '3d'})
            client.delete_layout_full()
            client.get_led_config()
            client.set_led_config({'strings': []})
            client.get_timer()
            client.set_timer({'time_now': 1800, 'time_on': 3600, 'time_off': 7200})
            client.get_movie_config()
            client.get_movies()
            client.get_current_movie()
            client.get_playlist()
            client.get_current_playlist_entry()
            client.get_network_scan()
            client.get_network_scan_results()
            client.get_network_status()
            client.get_mqtt_config()
            client.get_mic_config()
            client.get_mic_sample()
            client.get_music_drivers()
            client.get_music_driver_sets()
            client.get_current_music_driver_set()

        self.assertEqual(
            calls,
            [
                ('GET', '192.168.1.23', 'led/layout/full', True),
                ('POST', '192.168.1.23', 'led/layout/full', {'source': '3d'}, True),
                ('DELETE', '192.168.1.23', 'led/layout/full', True),
                ('GET', '192.168.1.23', 'led/config', True),
                ('POST', '192.168.1.23', 'led/config', {'strings': []}, True),
                ('GET', '192.168.1.23', 'timer', True),
                (
                    'POST',
                    '192.168.1.23',
                    'timer',
                    {'time_now': 1800, 'time_on': 3600, 'time_off': 7200},
                    True,
                ),
                ('GET', '192.168.1.23', 'led/movie/config', True),
                ('GET', '192.168.1.23', 'movies', True),
                ('GET', '192.168.1.23', 'led/movies/current', True),
                ('GET', '192.168.1.23', 'playlist', True),
                ('GET', '192.168.1.23', 'playlist/current', True),
                ('GET', '192.168.1.23', 'network/scan', True),
                ('GET', '192.168.1.23', 'network/scan_results', True),
                ('GET', '192.168.1.23', 'network/status', True),
                ('GET', '192.168.1.23', 'mqtt/config', True),
                ('GET', '192.168.1.23', 'mic/config', True),
                ('GET', '192.168.1.23', 'mic/sample', True),
                ('GET', '192.168.1.23', 'music/drivers', True),
                ('GET', '192.168.1.23', 'music/drivers/sets', True),
                ('GET', '192.168.1.23', 'music/drivers/sets/current', True),
            ],
        )

    def test_set_off_mode_uses_led_mode_off(self) -> None:
        calls = []

        def post(
            self: TwinklyClient,
            path: str,
            body: dict[str, object],
            authenticated: bool = True,
        ) -> TwinklyResponse:
            calls.append((self.host, path, body, authenticated))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        client = TwinklyClient(host='192.168.1.23')

        with patch.object(TwinklyClient, 'post', post):
            response = client.set_off_mode()

        self.assertEqual(response.data, {'code': 1000})
        self.assertEqual(
            calls,
            [('192.168.1.23', 'led/mode', {'mode': 'off'}, True)],
        )


class SessionTests(unittest.TestCase):
    def test_twinkly_request_label_includes_method_path_and_host(self) -> None:
        self.assertEqual(
            session.twinkly_request_label('get', 'fw/version', '192.168.1.23'),
            f'GET {TWINKLY_API_PREFIX}/fw/version on 192.168.1.23',
        )

    def test_set_mac_from_gestalt_updates_client(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        result = session.set_mac_from_gestalt(client, {'mac': 'AA:BB:CC:DD:EE:FF'})

        self.assertTrue(result)
        self.assertEqual(client.mac, 'AA:BB:CC:DD:EE:FF')

    def test_led_count_from_gestalt_returns_positive_ints(self) -> None:
        self.assertEqual(session.led_count_from_gestalt({'number_of_led': 250}), 250)
        self.assertIsNone(session.led_count_from_gestalt({'number_of_led': 0}))
        self.assertIsNone(session.led_count_from_gestalt({'number_of_led': '250'}))

    def test_turn_off_with_retry_uses_twinkly_label(self) -> None:
        labels = []

        def set_off_mode(
            client: TwinklyClient,
            retry: RetryConfig,
            label: str,
        ) -> TwinklyResponse:
            labels.append(label)
            return TwinklyResponse(http_status=200, data={'code': 1000})

        with patch('lyte.twinkly.session.set_off_mode_with_retry', set_off_mode):
            result = session.turn_off_with_retry(
                TwinklyClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                '192.168.1.23',
            )

        self.assertTrue(result)
        self.assertEqual(
            labels, [f'POST {TWINKLY_API_PREFIX}/led/mode on 192.168.1.23']
        )


class PackageDiagnosticTests(unittest.TestCase):
    def test_device_info_preserves_raw_gestalt_and_extracts_fields(self) -> None:
        raw = {
            'device_name': 'Twinkly',
            'product_name': 'Twinkly',
            'product_code': 'TWI190SPP',
            'hw_id': '1cc190',
            'fw_family': 'G',
            'mac': 'AA',
            'uuid': 'UUID',
            'led_profile': 'RGBW',
            'number_of_led': 190,
            'bytes_per_led': 4,
            'frame_rate': 28.57,
            'movie_capacity': 992,
            'max_supported_led': 1200,
            'unknown': 'preserved',
        }

        device = diagnostic.TwinklyDeviceInfo.from_gestalt(raw)

        self.assertEqual(device.raw, raw)
        self.assertEqual(device.device_name, 'Twinkly')
        self.assertEqual(device.product_code, 'TWI190SPP')
        self.assertEqual(device.hardware_id, '1cc190')
        self.assertEqual(device.firmware_family, 'G')
        self.assertEqual(device.led_count, 190)
        self.assertEqual(device.bytes_per_led, 4)
        self.assertEqual(device.frame_rate, 28.57)

    def test_read_endpoint_reports_unsupported_endpoint(self) -> None:
        def request() -> dict[str, object]:
            raise UnsupportedEndpointError('summary', 'Resource not found.')

        report = diagnostic.read_endpoint(
            TwinklyClient(host='192.168.1.23'),
            RetryConfig(attempts=1, delay=0, backoff=1),
            'summary',
            'GET',
            'summary',
            request,
        )

        self.assertEqual(
            report,
            diagnostic.TwinklyEndpointReport(
                name='summary',
                path='summary',
                supported=False,
                error='Resource not found.',
            ),
        )

    def test_authenticated_reports_probe_device_name_summary_and_echo(self) -> None:
        calls = []

        def get_layout_full(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'layout'))
            return TwinklyResponse(
                http_status=200, data={'code': 1000, 'coordinates': []}
            )

        def get_led_config(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'led-config'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'strings': []})

        def get_led_mode(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'mode'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'mode': 'off'})

        def get_timer(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'timer'))
            return TwinklyResponse(
                http_status=200,
                data={'code': 1000, 'time_now': 1800, 'time_on': -1, 'time_off': -1},
            )

        def get_movie_config(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'movie-config'))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        def get_movies(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'movies'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'entries': []})

        def get_current_movie(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'current-movie'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'id': 0})

        def get_playlist(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'playlist'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'entries': []})

        def get_current_playlist_entry(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'current-playlist-entry'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'id': 0})

        def get_network_status(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'network-status'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'mode': 1})

        def get_network_scan(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'network-scan'))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        def get_network_scan_results(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'network-scan-results'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'networks': []})

        def get_mqtt_config(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'mqtt-config'))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        def get_mic_config(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'mic-config'))
            return TwinklyResponse(http_status=200, data={'code': 1000})

        def get_mic_sample(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'mic-sample'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'sample': 0})

        def get_music_drivers(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'music-drivers'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'drivers': []})

        def get_music_driver_sets(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'music-driver-sets'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'sets': []})

        def get_current_music_driver_set(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'current-music-driver-set'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'id': 0})

        def get_led_color(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'color'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'red': 1})

        def get_effects(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'effects'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'effects': []})

        def get_current_effect(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'current-effect'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'effect_id': 0})

        def get_brightness(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'brightness'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'value': 75})

        def get_saturation(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'saturation'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'value': 80})

        def get_device_name(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'device_name'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'name': 'Tree'})

        def get_summary(self: TwinklyClient) -> TwinklyResponse:
            calls.append(('GET', 'summary'))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'leds': 250})

        def echo(self: TwinklyClient, body: dict[str, object]) -> TwinklyResponse:
            calls.append(('POST', 'echo', body))
            return TwinklyResponse(http_status=200, data={'code': 1000, 'json': body})

        methods = {
            'get_layout_full': get_layout_full,
            'get_led_config': get_led_config,
            'get_led_mode': get_led_mode,
            'get_timer': get_timer,
            'get_movie_config': get_movie_config,
            'get_movies': get_movies,
            'get_current_movie': get_current_movie,
            'get_playlist': get_playlist,
            'get_current_playlist_entry': get_current_playlist_entry,
            'get_network_status': get_network_status,
            'get_network_scan': get_network_scan,
            'get_network_scan_results': get_network_scan_results,
            'get_mqtt_config': get_mqtt_config,
            'get_mic_config': get_mic_config,
            'get_mic_sample': get_mic_sample,
            'get_music_drivers': get_music_drivers,
            'get_music_driver_sets': get_music_driver_sets,
            'get_current_music_driver_set': get_current_music_driver_set,
            'get_led_color': get_led_color,
            'get_effects': get_effects,
            'get_current_effect': get_current_effect,
            'get_brightness': get_brightness,
            'get_saturation': get_saturation,
            'get_device_name': get_device_name,
            'get_summary': get_summary,
            'echo': echo,
        }
        with ExitStack() as stack:
            for name, method in methods.items():
                stack.enter_context(patch.object(TwinklyClient, name, method))
            reports = diagnostic.authenticated_reports(
                TwinklyClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
            )

        self.assertEqual(
            [i.name for i in reports],
            [
                'layout',
                'led-config',
                'mode',
                'timer',
                'movie-config',
                'movies',
                'current-movie',
                'playlist',
                'current-playlist-entry',
                'network-status',
                'network-scan',
                'network-scan-results',
                'mqtt-config',
                'mic-config',
                'mic-sample',
                'music-drivers',
                'music-driver-sets',
                'current-music-driver-set',
                'color',
                'effects',
                'current-effect',
                'brightness',
                'saturation',
                'device-name',
                'summary',
                'echo',
            ],
        )
        self.assertEqual(
            calls,
            [
                ('GET', 'layout'),
                ('GET', 'led-config'),
                ('GET', 'mode'),
                ('GET', 'timer'),
                ('GET', 'movie-config'),
                ('GET', 'movies'),
                ('GET', 'current-movie'),
                ('GET', 'playlist'),
                ('GET', 'current-playlist-entry'),
                ('GET', 'network-status'),
                ('GET', 'network-scan'),
                ('GET', 'network-scan-results'),
                ('GET', 'mqtt-config'),
                ('GET', 'mic-config'),
                ('GET', 'mic-sample'),
                ('GET', 'music-drivers'),
                ('GET', 'music-driver-sets'),
                ('GET', 'current-music-driver-set'),
                ('GET', 'color'),
                ('GET', 'effects'),
                ('GET', 'current-effect'),
                ('GET', 'brightness'),
                ('GET', 'saturation'),
                ('GET', 'device_name'),
                ('GET', 'summary'),
                ('POST', 'echo', {'message': 'lyte diagnostic'}),
            ],
        )

    def test_run_diagnostic_reports_read_only_device_state(self) -> None:
        output = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{DIAGNOSTIC}.discover_host', return_value='192.168.1.23'),
            patch(f'{DIAGNOSTIC}.TwinklyClient', return_value=client),
            patch(
                f'{DIAGNOSTIC}.read_endpoint',
                side_effect=(
                    diagnostic.TwinklyEndpointReport(
                        name='gestalt',
                        path='gestalt',
                        supported=True,
                        data={'device_name': 'Tree', 'mac': 'AA', 'number_of_led': 250},
                    ),
                    diagnostic.TwinklyEndpointReport(
                        name='firmware',
                        path='fw/version',
                        supported=True,
                        data={'version': '1.0'},
                    ),
                    diagnostic.TwinklyEndpointReport(
                        name='status',
                        path='status',
                        supported=True,
                        data={'mode': 'rt'},
                    ),
                ),
            ),
            patch(f'{DIAGNOSTIC}.session.authenticate_device', return_value=object()),
            patch(f'{DIAGNOSTIC}.authenticated_reports', return_value=()),
            patch(
                f'{DIAGNOSTIC}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', output),
        ):
            result = diagnostic.run_diagnostic(diagnostic.DiagnosticConfig())

        self.assertEqual(result, 0)
        self.assertEqual(client.mac, 'AA')
        turn_off.assert_called_once()
        self.assertIn('Device name: Tree', output.getvalue())
        self.assertIn("firmware: {'version': '1.0'}", output.getvalue())

    def test_diagnostic_command_runs_twinkly_diagnostic_by_default(self) -> None:
        with patch(f'{DIAGNOSTIC}.run_diagnostic', return_value=0) as run_diagnostic:
            result = diagnostic.run_diagnostic_command(
                diagnostic.DiagnosticCommandConfig(host='192.168.1.23', attempts=2)
            )

        self.assertEqual(result, 0)
        config = run_diagnostic.call_args.args[0]
        self.assertEqual(config.host, '192.168.1.23')
        self.assertEqual(config.attempts, 2)

    def test_diagnostic_command_runs_realtime_diagnostic_when_requested(self) -> None:
        with patch(f'{DIAGNOSTIC}.run_realtime_diagnostic', return_value=0) as realtime:
            result = diagnostic.run_diagnostic_command(
                diagnostic.DiagnosticCommandConfig(
                    realtime=True,
                    led_count=10,
                    pause=0.1,
                )
            )

        self.assertEqual(result, 0)
        config = realtime.call_args.args[0]
        self.assertEqual(config.led_count, 10)
        self.assertEqual(config.pause, 0.1)
        self.assertEqual(config.discovery_timeout, 0.1)


class TwinklyControlTests(unittest.TestCase):
    def test_output_control_accepts_string_values_from_device(self) -> None:
        control = output.OutputControl.from_response({'mode': 'enabled', 'value': '75'})

        self.assertEqual(control.mode, 'enabled')
        self.assertEqual(control.type, 'A')
        self.assertEqual(control.value, 75)

    def test_output_control_request_body_uses_documented_shape(self) -> None:
        self.assertEqual(
            output.OutputControl(value=80).request_body(),
            {'mode': 'enabled', 'type': 'A', 'value': 80},
        )

    def test_layout_model_accepts_documented_shape(self) -> None:
        twinkly_layout = layout.TwinklyLayout.from_response(
            {
                'aspectXY': 1,
                'aspectXZ': 2,
                'coordinates': [{'x': 1.0, 'y': 2.0, 'z': 3.0}],
                'source': '3d',
                'synthesized': False,
                'uuid': '00000000-0000-0000-0000-000000000000',
            }
        )

        self.assertEqual(
            twinkly_layout.request_body(),
            {
                'aspectXY': 1,
                'aspectXZ': 2,
                'coordinates': [{'x': 1.0, 'y': 2.0, 'z': 3.0}],
                'source': '3d',
                'synthesized': False,
                'uuid': '00000000-0000-0000-0000-000000000000',
            },
        )

    def test_timer_model_uses_seconds_after_midnight(self) -> None:
        twinkly_timer = timer.TwinklyTimer.from_response(
            {'time_now': 1800, 'time_on': -1, 'time_off': 7200, 'code': 1000}
        )

        self.assertEqual(twinkly_timer.time_now, 1800)
        self.assertEqual(twinkly_timer.time_on, -1)
        self.assertEqual(twinkly_timer.time_off, 7200)
        self.assertEqual(
            twinkly_timer.request_body(),
            {'time_on': -1, 'time_off': 7200, 'time_now': 1800},
        )

    def test_timer_request_can_omit_current_time(self) -> None:
        self.assertEqual(
            timer.TwinklyTimer(time_on=3600, time_off=7200).request_body(),
            {'time_on': 3600, 'time_off': 7200},
        )

    def test_read_output_control_dispatches_by_kind(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch.object(
                TwinklyClient,
                'get_brightness',
                return_value=TwinklyResponse(
                    http_status=200,
                    data={'mode': 'enabled', 'value': 75},
                ),
            ) as get_brightness,
            patch.object(
                TwinklyClient,
                'get_saturation',
                return_value=TwinklyResponse(
                    http_status=200,
                    data={'mode': 'enabled', 'value': 80},
                ),
            ) as get_saturation,
        ):
            brightness = output.read_output_control(client, 'brightness')
            saturation = output.read_output_control(client, 'saturation')

        self.assertEqual(brightness.value, 75)
        self.assertEqual(saturation.value, 80)
        get_brightness.assert_called_once()
        get_saturation.assert_called_once()

    def test_write_output_control_dispatches_by_kind(self) -> None:
        client = TwinklyClient(host='192.168.1.23')
        control = output.OutputControl(value=90)

        with (
            patch.object(TwinklyClient, 'set_brightness') as set_brightness,
            patch.object(TwinklyClient, 'set_saturation') as set_saturation,
        ):
            output.write_output_control(client, 'brightness', control)
            output.write_output_control(client, 'saturation', control)

        set_brightness.assert_called_once_with(
            {'mode': 'enabled', 'type': 'A', 'value': 90}
        )
        set_saturation.assert_called_once_with(
            {'mode': 'enabled', 'type': 'A', 'value': 90}
        )

    def test_run_output_control_get_reports_current_value(self) -> None:
        stream = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch(
                f'{OUTPUT}.read_output_control',
                return_value=output.OutputControl(value=75),
            ),
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', stream),
        ):
            result = output.run_output_control(
                diagnostic.DiagnosticConfig(),
                'brightness',
                'get',
                None,
            )

        self.assertEqual(result, 0)
        turn_off.assert_called_once()
        self.assertIn('[brightness] mode=enabled type=A value=75', stream.getvalue())

    def test_run_output_control_set_writes_value(self) -> None:
        stream = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch(f'{OUTPUT}.write_output_control') as write_output_control,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', stream),
        ):
            result = output.run_output_control(
                diagnostic.DiagnosticConfig(),
                'saturation',
                'set',
                80,
            )

        self.assertEqual(result, 0)
        turn_off.assert_called_once()
        write_output_control.assert_called_once_with(
            client,
            'saturation',
            output.OutputControl(value=80),
        )
        self.assertIn(
            '[saturation] set mode=enabled type=A value=80',
            stream.getvalue(),
        )

    def test_run_mode_control_sets_mode_then_turns_off(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(TwinklyClient, 'set_led_mode') as set_led_mode,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            result = mode.run_mode_control(diagnostic.DiagnosticConfig(), 'set', 'demo')

        self.assertEqual(result, 0)
        set_led_mode.assert_called_once_with({'mode': 'demo'})
        turn_off.assert_called_once()

    def test_run_color_control_sets_rgb_then_turns_off(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(TwinklyClient, 'set_led_color') as set_led_color,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            result = mode.run_color_control(
                diagnostic.DiagnosticConfig(), 'set', 1, 2, 3
            )

        self.assertEqual(result, 0)
        set_led_color.assert_called_once_with(
            {'mode': 'rgb', 'red': 1, 'green': 2, 'blue': 3}
        )
        turn_off.assert_called_once()

    def test_run_effect_control_sets_current_effect_then_turns_off(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(TwinklyClient, 'set_current_effect') as set_current_effect,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            result = mode.run_effect_control(
                diagnostic.DiagnosticConfig(), 'set-current', 4
            )

        self.assertEqual(result, 0)
        set_current_effect.assert_called_once_with({'effect_id': 4})
        turn_off.assert_called_once()

    def test_run_layout_control_exports_layout_then_turns_off(self) -> None:
        output = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'layout.json'
            with (
                patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
                patch(f'{COMMAND}.TwinklyClient', return_value=client),
                patch(f'{COMMAND}.prepare_authenticated_client'),
                patch.object(
                    TwinklyClient,
                    'get_layout_full',
                    return_value=TwinklyResponse(
                        http_status=200,
                        data={'source': '3d', 'coordinates': []},
                    ),
                ),
                patch(
                    f'{COMMAND}.session.turn_off_with_retry', return_value=True
                ) as turn_off,
                patch('sys.stdout', output),
            ):
                result = layout.run_layout_control(
                    diagnostic.DiagnosticConfig(), 'export', path
                )

            self.assertEqual(result, 0)
            self.assertEqual(
                json.loads(path.read_text()),
                {'coordinates': [], 'source': '3d'},
            )
            turn_off.assert_called_once()
            self.assertIn('[layout] exported', output.getvalue())

    def test_run_layout_control_uploads_layout_then_turns_off(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'layout.json'
            path.write_text(
                json.dumps(
                    {
                        'aspectXY': 0,
                        'aspectXZ': 0,
                        'coordinates': [{'x': 1, 'y': 2, 'z': 3}],
                        'source': '3d',
                        'synthesized': False,
                    }
                )
            )
            with (
                patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
                patch(f'{COMMAND}.TwinklyClient', return_value=client),
                patch(f'{COMMAND}.prepare_authenticated_client'),
                patch.object(TwinklyClient, 'set_layout_full') as set_layout_full,
                patch(
                    f'{COMMAND}.session.turn_off_with_retry', return_value=True
                ) as turn_off,
                patch('sys.stdout', new_callable=io.StringIO),
            ):
                result = layout.run_layout_control(
                    diagnostic.DiagnosticConfig(), 'upload', path
                )

        self.assertEqual(result, 0)
        set_layout_full.assert_called_once_with(
            {
                'aspectXY': 0,
                'aspectXZ': 0,
                'coordinates': [{'x': 1.0, 'y': 2.0, 'z': 3.0}],
                'source': '3d',
                'synthesized': False,
            }
        )
        turn_off.assert_called_once()

    def test_run_led_config_control_sets_json_config_then_turns_off(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({'strings': [{'first_led_id': 0}]}))
            with (
                patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
                patch(f'{COMMAND}.TwinklyClient', return_value=client),
                patch(f'{COMMAND}.prepare_authenticated_client'),
                patch.object(TwinklyClient, 'set_led_config') as set_led_config,
                patch(
                    f'{COMMAND}.session.turn_off_with_retry', return_value=True
                ) as turn_off,
                patch('sys.stdout', new_callable=io.StringIO),
            ):
                result = layout.run_led_config_control(
                    diagnostic.DiagnosticConfig(), 'set', path
                )

        self.assertEqual(result, 0)
        set_led_config.assert_called_once_with({'strings': [{'first_led_id': 0}]})
        turn_off.assert_called_once()

    def test_run_timer_control_reads_timer_then_turns_off(self) -> None:
        output = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(
                TwinklyClient,
                'get_timer',
                return_value=TwinklyResponse(
                    http_status=200,
                    data={'time_now': 1800, 'time_on': -1, 'time_off': 7200},
                ),
            ),
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', output),
        ):
            result = timer.run_timer_control(
                diagnostic.DiagnosticConfig(), 'get', None, None, None
            )

        self.assertEqual(result, 0)
        self.assertIn(
            '[timer] time_now=1800 time_on=-1 time_off=7200',
            output.getvalue(),
        )
        turn_off.assert_called_once()

    def test_run_timer_control_sets_timer_then_turns_off(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(TwinklyClient, 'set_timer') as set_timer,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            result = timer.run_timer_control(
                diagnostic.DiagnosticConfig(), 'set', 3600, 7200, 1800
            )

        self.assertEqual(result, 0)
        set_timer.assert_called_once_with(
            {'time_on': 3600, 'time_off': 7200, 'time_now': 1800}
        )
        turn_off.assert_called_once()

    def test_run_movie_control_reads_current_movie_then_turns_off(self) -> None:
        output = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(
                TwinklyClient,
                'get_current_movie',
                return_value=TwinklyResponse(http_status=200, data={'id': 0}),
            ) as get_current_movie,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', output),
        ):
            result = media.run_movie_control(diagnostic.DiagnosticConfig(), 'current')

        self.assertEqual(result, 0)
        get_current_movie.assert_called_once()
        turn_off.assert_called_once()
        self.assertIn("[movie] current {'id': 0}", output.getvalue())

    def test_run_playlist_control_reads_playlist_then_turns_off(self) -> None:
        output = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(
                TwinklyClient,
                'get_playlist',
                return_value=TwinklyResponse(http_status=200, data={'entries': []}),
            ) as get_playlist,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', output),
        ):
            result = media.run_playlist_control(diagnostic.DiagnosticConfig(), 'list')

        self.assertEqual(result, 0)
        get_playlist.assert_called_once()
        turn_off.assert_called_once()
        self.assertIn("[playlist] list {'entries': []}", output.getvalue())

    def test_run_network_control_reads_status_then_turns_off(self) -> None:
        output = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(
                TwinklyClient,
                'get_network_status',
                return_value=TwinklyResponse(http_status=200, data={'mode': 1}),
            ) as get_network_status,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', output),
        ):
            result = networking.run_network_control(
                diagnostic.DiagnosticConfig(), 'status'
            )

        self.assertEqual(result, 0)
        get_network_status.assert_called_once()
        turn_off.assert_called_once()
        self.assertIn("[network] status {'mode': 1}", output.getvalue())

    def test_run_mqtt_control_reads_config_then_turns_off(self) -> None:
        output = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(
                TwinklyClient,
                'get_mqtt_config',
                return_value=TwinklyResponse(http_status=200, data={'enabled': False}),
            ) as get_mqtt_config,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', output),
        ):
            result = inputs.run_mqtt_control(diagnostic.DiagnosticConfig(), 'config')

        self.assertEqual(result, 0)
        get_mqtt_config.assert_called_once()
        turn_off.assert_called_once()
        self.assertIn("[mqtt] config {'enabled': False}", output.getvalue())

    def test_run_mic_control_reads_sample_then_turns_off(self) -> None:
        output = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(
                TwinklyClient,
                'get_mic_sample',
                return_value=TwinklyResponse(http_status=200, data={'sample': 3}),
            ) as get_mic_sample,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', output),
        ):
            result = inputs.run_mic_control(diagnostic.DiagnosticConfig(), 'sample')

        self.assertEqual(result, 0)
        get_mic_sample.assert_called_once()
        turn_off.assert_called_once()
        self.assertIn("[mic] sample {'sample': 3}", output.getvalue())

    def test_run_music_control_reads_current_driver_set_then_turns_off(self) -> None:
        output = io.StringIO()
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch.object(
                TwinklyClient,
                'get_current_music_driver_set',
                return_value=TwinklyResponse(http_status=200, data={'id': 1}),
            ) as get_current_music_driver_set,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('sys.stdout', output),
        ):
            result = inputs.run_music_control(
                diagnostic.DiagnosticConfig(), 'current-driver-set'
            )

        self.assertEqual(result, 0)
        get_current_music_driver_set.assert_called_once()
        turn_off.assert_called_once()
        self.assertIn("[music] current-driver-set {'id': 1}", output.getvalue())


class RuntimeTests(unittest.TestCase):
    def test_read_device_led_count_uses_configured_count_after_reading_gestalt(
        self,
    ) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with patch(
            'lyte.twinkly.session.read_gestalt',
            return_value={'mac': 'AA', 'number_of_led': 250},
        ):
            led_count, gestalt = session.read_device_led_count(
                client,
                RetryConfig(attempts=1, delay=0, backoff=1),
                100,
                'read',
            )

        self.assertEqual(led_count, 100)
        self.assertEqual(gestalt, {'mac': 'AA', 'number_of_led': 250})
        self.assertEqual(client.mac, 'AA')

    def test_read_device_led_count_detects_count_from_gestalt(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with patch(
            'lyte.twinkly.session.read_gestalt',
            return_value={'mac': 'AA', 'number_of_led': 250},
        ):
            led_count, _gestalt = session.read_device_led_count(
                client,
                RetryConfig(attempts=1, delay=0, backoff=1),
                None,
                'read',
            )

        self.assertEqual(led_count, 250)

    def test_send_authenticated_frame_returns_none_without_token(self) -> None:
        frame = solid_rgb_frame(1, 255, 0, 0)

        sent = session.send_authenticated_frame(
            TwinklyClient(host='192.168.1.23'),
            '192.168.1.23',
            frame,
            RetryConfig(attempts=1, delay=0, backoff=1),
            'send',
        )

        self.assertIsNone(sent)


class DiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.diagnostic = importlib.import_module('lyte.twinkly.realtime_diagnostic')

    def test_discover_one_retries_empty_discovery_attempts(self) -> None:
        calls = 0
        timeouts = []
        reported = []

        def discovery_attempt(
            sock,
            timeout: float,
            attempt: int,
            attempts: int,
            report_failure: bool,
        ):
            nonlocal calls
            calls += 1
            timeouts.append(timeout)
            reported.append(report_failure)
            if calls == 1:
                return None
            return DiscoveredDevice(ip_address='192.168.1.23', device_id='Twinkly')

        retry = RetryConfig(
            attempts=2,
            delay=0,
            backoff=1,
            backoff_after=1,
        )

        with (
            patch.object(
                self.diagnostic,
                'discovery_attempt',
                discovery_attempt,
            ),
            patch('sys.stdout', new_callable=io.StringIO),
            patch(
                'sys.stderr',
                new_callable=io.StringIO,
            ),
        ):
            host = self.diagnostic.discover_one(0.01, retry)

        self.assertEqual(host, '192.168.1.23')
        self.assertEqual(calls, 2)
        self.assertEqual(timeouts, [0.01, 0.01])
        self.assertEqual(reported, [False, True])

    def test_config_uses_slower_network_retry_defaults(self) -> None:
        config = self.diagnostic.RealtimeDiagnosticConfig()

        self.assertEqual(config.retry.attempts, 10)
        self.assertEqual(config.retry.delay, 0.5)
        self.assertEqual(config.discovery_retry.delay, 0.05)


if __name__ == '__main__':
    unittest.main()
