from __future__ import annotations

import argparse
import base64
import importlib.util
import io
import json
import random
import tempfile
import unittest
from collections.abc import Sized
from pathlib import Path
from unittest.mock import patch

import numpy as np
from numpy import testing as npt
from numpy.typing import NDArray

from lyte import cli
from lyte.animation import Animation, Device, State
from lyte.animations.bibliopixel import (
    Alternates,
    ColorChase,
    ColorFade,
    ColorFill,
    ColorPattern,
    ColorWipe,
    FireFlies,
    HalvesRainbow,
    LarsonScanner,
    LinearRainbow,
    PartyMode,
    PixelPingPong,
    Pulse,
    Rainbow,
    RainbowCycle,
    SaberBlade,
    Searchlights,
    Twinkle,
    Wave,
    WhiteTwinkle,
)
from lyte.animations.colors import solid_rgb_frame
from lyte.animations.hamiltonian import (
    Hamiltonian,
    HamiltonianCounter,
    hamiltonian_colors,
    next_hamiltonian,
    parse_order,
)
from lyte.animations.random_walk import RandomWalk, perturb
from lyte.diagnostic import (
    DiagnosticConfig,
    TwinklyDeviceInfo,
    XledEndpointReport,
    authenticated_reports,
    read_endpoint,
    run_diagnostic,
)
from lyte.errors import DiscoveryError, ProtocolError, UnsupportedEndpointError
from lyte.fps_test import (
    DOWN_KEY,
    FPS_VALUES,
    UP_KEY,
    VERIFY_DEMOS,
    FadeReport,
    VerifyConfig,
    VerifyResult,
    adjust_black_floor_level,
    blend_frames,
    discover_host,
    dispersed_pixel_order,
    gradient_frame,
    read_single_key,
    report_fades,
    report_verify_results,
    run_black_floor_keys,
    run_fades,
    run_fast_verify,
    run_realtime_command,
    run_temporal_dither_comparison,
    run_verify_test,
    solid_grayscale_frame,
    solid_rgb_level_frame,
    stream_fade,
    temporal_dither_grayscale_frame,
    verify_answer,
    verify_primary_channels_frame,
)
from lyte.logging import LOGGING, log, log_error, log_status
from lyte.network.authentication import CHALLENGE_KEY, derive_key, mac_bytes, rc4
from lyte.network.client import LyteClient, LyteResponse
from lyte.network.discovery import DiscoveredDevice, parse_discovery_response
from lyte.network.frame import (
    frame_packets_v3,
    frame_payload,
    send_frame_v3,
)
from lyte.network.session import (
    led_count_from_gestalt,
    set_mac_from_gestalt,
    turn_off_with_retry,
    xled_request_label,
)
from lyte.preview import Layout, animation_document, render_animation_html
from lyte.retry import RetryConfig, retry_call
from lyte.runtime import read_device_led_count, send_authenticated_frame
from lyte.xled import (
    OutputControl,
    XledLayout,
    read_output_control,
    run_color_control,
    run_effect_control,
    run_layout_control,
    run_led_config_control,
    run_mode_control,
    run_output_control,
    write_output_control,
)


def render(
    animation: Animation,
    device: Device,
    state: State,
) -> NDArray[np.uint8]:
    return animation.render(device, state)


def initial_state(animation: Animation, led_count: int) -> tuple[Device, State]:
    device = Device(led_count=led_count)
    return device, animation.initial_state(device)


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

        with patch('lyte.network.frame.socket.socket', return_value=Socket()):
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
    def test_fps_values_include_120_hz(self) -> None:
        self.assertEqual(FPS_VALUES, (30.0, 60.0, 120.0, 240, 480, 960, 1920))

    def test_gradient_frame_blends_between_endpoint_colors(self) -> None:
        npt.assert_array_equal(
            gradient_frame(3, (0, 0, 0), (100, 50, 200)),
            np.array([[0, 0, 0], [50, 25, 100], [100, 50, 200]], dtype=np.uint8),
        )

    def test_blend_frames_crossfades_two_frames(self) -> None:
        first_frame = np.array([[0, 100, 200]], dtype=np.uint8)
        second_frame = np.array([[100, 200, 0]], dtype=np.uint8)

        npt.assert_array_equal(
            blend_frames(first_frame, second_frame, 0.25),
            np.array([[25, 125, 150]], dtype=np.uint8),
        )

    def test_cli_test_command_dispatches_fps_test(self) -> None:
        with patch.object(cli, 'run_fps_test', return_value=0) as run_fps_test:
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
            cli, 'run_temporal_dither_test', return_value=0
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

    def test_cli_black_floor_command_dispatches_black_floor_test(self) -> None:
        with patch.object(
            cli, 'run_black_floor_test', return_value=0
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
        with patch.object(cli, 'run_verify_test', return_value=0) as run_verify_test:
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
        with patch.object(cli, 'run_diagnostic', return_value=0) as run_diagnostic:
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
        config = run_diagnostic.call_args.args[0]
        self.assertEqual(config.host, '192.168.1.23')
        self.assertEqual(config.attempts, 2)

    def test_cli_brightness_command_dispatches_output_control(self) -> None:
        with patch.object(
            cli, 'run_output_control', return_value=0
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
            cli, 'run_output_control', return_value=0
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
        with patch.object(cli, 'run_mode_control', return_value=0) as run_mode_control:
            result = cli.main(['mode', 'set', 'demo'])

        self.assertEqual(result, 0)
        config, action, mode = run_mode_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'set')
        self.assertEqual(mode, 'demo')

    def test_cli_color_command_dispatches_color_control(self) -> None:
        with patch.object(
            cli, 'run_color_control', return_value=0
        ) as run_color_control:
            result = cli.main(['color', 'set', '1', '2', '3'])

        self.assertEqual(result, 0)
        config, action, red, green, blue = run_color_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'set')
        self.assertEqual((red, green, blue), (1, 2, 3))

    def test_cli_effects_command_dispatches_effect_control(self) -> None:
        with patch.object(
            cli, 'run_effect_control', return_value=0
        ) as run_effect_control:
            result = cli.main(['effects', 'set-current', '4'])

        self.assertEqual(result, 0)
        config, action, effect_id = run_effect_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'set-current')
        self.assertEqual(effect_id, 4)

    def test_cli_layout_command_dispatches_layout_control(self) -> None:
        with patch.object(
            cli, 'run_layout_control', return_value=0
        ) as run_layout_control:
            result = cli.main(['layout', 'export', 'layout.json'])

        self.assertEqual(result, 0)
        config, action, path = run_layout_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'export')
        self.assertEqual(path, Path('layout.json'))

    def test_cli_led_config_command_dispatches_led_config_control(self) -> None:
        with patch.object(
            cli, 'run_led_config_control', return_value=0
        ) as run_led_config_control:
            result = cli.main(['led-config', 'set', 'config.json'])

        self.assertEqual(result, 0)
        config, action, path = run_led_config_control.call_args.args
        self.assertIsNone(config.host)
        self.assertEqual(action, 'set')
        self.assertEqual(path, Path('config.json'))

    def test_discover_host_retries_until_a_device_replies(self) -> None:
        device = DiscoveredDevice(ip_address='192.168.1.23', device_id='twinkly')

        with (
            patch('lyte.fps_test.discover', side_effect=(iter(()), iter([device]))),
            patch('sys.stdout', new_callable=io.StringIO),
            patch('sys.stderr', new_callable=io.StringIO),
        ):
            host = discover_host(None)

        self.assertEqual(host, '192.168.1.23')

    def test_discover_host_stops_at_timeout(self) -> None:
        with (
            patch('lyte.fps_test.discover', return_value=iter(())),
            patch('lyte.fps_test.time.monotonic', side_effect=(0.0, 0.0, 1.0)),
            patch('sys.stdout', new_callable=io.StringIO),
            patch('sys.stderr', new_callable=io.StringIO),
        ):
            host = discover_host(1.0)

        self.assertIsNone(host)

    def test_verify_lists_demos_before_running_them(self) -> None:
        output = io.StringIO()

        with (
            patch('lyte.fps_test.discover_host', return_value='192.168.1.23'),
            patch('lyte.fps_test.read_led_count', return_value=2),
            patch('lyte.fps_test.prepare_device', return_value=True),
            patch('lyte.fps_test.run_fast_verify', return_value=()),
            patch('lyte.fps_test.turn_off_device', return_value=True),
            patch('sys.stdout', output),
        ):
            result = run_verify_test(VerifyConfig())

        self.assertEqual(result, 0)
        self.assertIn(
            '[verify] Demos: primary-channels, moving-gradient, crossfade, '
            'temporal-dither',
            output.getvalue(),
        )

    def test_realtime_command_turns_off_device_after_setup_interrupt(self) -> None:
        def interrupt_setup(
            client: LyteClient,
            retry: RetryConfig,
            host: str,
        ) -> bool:
            raise KeyboardInterrupt

        with (
            patch('lyte.fps_test.read_led_count', return_value=2),
            patch('lyte.fps_test.prepare_device', interrupt_setup),
            patch('lyte.fps_test.turn_off_device', return_value=True) as turn_off,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            result = run_realtime_command(
                '192.168.1.23',
                5.0,
                None,
                1,
                0,
                1,
                None,
                lambda _client, _retry, _host, _device: None,
            )

        self.assertEqual(result, 0)
        turn_off.assert_called_once()

    def test_dispersed_pixel_order_visits_each_led_once(self) -> None:
        order = dispersed_pixel_order(11)

        self.assertEqual(sorted(order.tolist()), list(range(11)))
        self.assertEqual(order.tolist(), [0, 5, 10, 4, 9, 3, 8, 2, 7, 1, 6])

    def test_temporal_dither_grayscale_frame_spreads_fractional_step(
        self,
    ) -> None:
        device = Device(led_count=4)
        order = np.array([0, 2, 1, 3], dtype=np.int64)

        frame = temporal_dither_grayscale_frame(device, 0, 1, 2, 5, order)

        npt.assert_array_equal(
            frame,
            np.array([[1, 1, 1], [0, 0, 0], [1, 1, 1], [0, 0, 0]], dtype=np.uint8),
        )

    def test_solid_grayscale_frame_fills_all_channels(self) -> None:
        npt.assert_array_equal(
            solid_grayscale_frame(Device(led_count=2), 7),
            np.array([[7, 7, 7], [7, 7, 7]], dtype=np.uint8),
        )

    def test_solid_rgb_level_frame_fills_all_channels(self) -> None:
        npt.assert_array_equal(
            solid_rgb_level_frame(Device(led_count=2), (1, 2, 3)),
            np.array([[1, 2, 3], [1, 2, 3]], dtype=np.uint8),
        )

    def test_adjust_black_floor_level_changes_one_channel(self) -> None:
        self.assertEqual(adjust_black_floor_level((0, 0, 0), 'r'), (1, 0, 0))
        self.assertEqual(adjust_black_floor_level((0, 0, 0), 'g'), (0, 1, 0))
        self.assertEqual(adjust_black_floor_level((0, 0, 0), 'b'), (0, 0, 1))
        self.assertEqual(adjust_black_floor_level((1, 1, 1), 'R'), (0, 1, 1))
        self.assertEqual(adjust_black_floor_level((1, 1, 1), 'G'), (1, 0, 1))
        self.assertEqual(adjust_black_floor_level((1, 1, 1), 'B'), (1, 1, 0))
        self.assertEqual(adjust_black_floor_level((0, 0, 0), 'R'), (0, 0, 0))
        self.assertEqual(
            adjust_black_floor_level((255, 255, 255), 'r'), (255, 255, 255)
        )
        self.assertEqual(adjust_black_floor_level((1, 2, 3), UP_KEY), (2, 3, 4))
        self.assertEqual(adjust_black_floor_level((1, 2, 3), DOWN_KEY), (0, 1, 2))
        self.assertEqual(
            adjust_black_floor_level((255, 255, 255), UP_KEY), (255, 255, 255)
        )

    def test_black_floor_keys_show_initial_black_and_each_valid_key(self) -> None:
        sent_frames = []
        keys = iter(['r', 'g', 'b', 'R', 'x', 'B', UP_KEY, DOWN_KEY])

        def record_frame(
            client: LyteClient,
            retry: RetryConfig,
            host: str,
            frame: NDArray[np.uint8],
        ) -> int:
            sent_frames.append(frame.copy())
            return frame.nbytes

        def read_key() -> str:
            try:
                return next(keys)
            except StopIteration:
                raise KeyboardInterrupt from None

        with (
            patch('lyte.fps_test.send_realtime_frame', record_frame),
            self.assertRaises(KeyboardInterrupt),
        ):
            run_black_floor_keys(
                LyteClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                '192.168.1.23',
                Device(led_count=1),
                read_key,
            )

        self.assertEqual(
            [tuple(int(i) for i in f[0]) for f in sent_frames],
            [
                (0, 0, 0),
                (1, 0, 0),
                (1, 1, 0),
                (1, 1, 1),
                (0, 1, 1),
                (0, 1, 0),
                (1, 2, 1),
                (0, 1, 0),
            ],
        )

    def test_read_single_key_uses_unbuffered_file_descriptor(self) -> None:
        with patch('lyte.fps_test.os.read', return_value=b'r') as read:
            key = read_single_key(7)

        self.assertEqual(key, 'r')
        read.assert_called_once_with(7, 1)

    def test_read_single_key_reads_arrow_escape_sequence(self) -> None:
        with patch('lyte.fps_test.os.read', side_effect=[b'\x1b', b'[A']) as read:
            key = read_single_key(7)

        self.assertEqual(key, UP_KEY)
        self.assertEqual(read.call_args_list[0].args, (7, 1))
        self.assertEqual(read.call_args_list[1].args, (7, 2))

    def test_temporal_dither_comparison_runs_direct_then_dithered(self) -> None:
        device = Device(led_count=2)
        phases = []

        def record_fade(
            client: LyteClient,
            retry: RetryConfig,
            host: str,
            device: Device,
            fps: float,
            duration: float,
            phase: str,
            frame_at: object,
        ) -> FadeReport:
            phases.append((phase, fps, duration))
            return FadeReport(
                fps=fps,
                phase=phase,
                total_frames=1,
                unique_frames=1,
                late_frames=0,
                short_sends=0,
                max_late_ms=0,
                elapsed_ms=0,
            )

        with (
            patch('lyte.fps_test.stream_frames', record_fade),
            patch('lyte.fps_test.report_fades'),
        ):
            run_temporal_dither_comparison(
                LyteClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                '192.168.1.23',
                device,
                5,
            )

        self.assertEqual(
            phases,
            [
                ('normal-black-to-white', 240.0, 5),
                ('normal-white-to-black', 240.0, 5),
                ('normal-black-hold', 240.0, 1.0),
                ('dithered-black-to-white', 240.0, 5),
                ('dithered-white-to-black', 240.0, 5),
                ('dithered-black-hold', 240.0, 1.0),
            ],
        )

    def test_verify_primary_channels_cycles_rgb_and_white(self) -> None:
        device = Device(led_count=2)

        frames = [verify_primary_channels_frame(device, i, 4) for i in range(4)]

        npt.assert_array_equal(frames[0], np.full((2, 3), (255, 0, 0), dtype=np.uint8))
        npt.assert_array_equal(frames[1], np.full((2, 3), (0, 255, 0), dtype=np.uint8))
        npt.assert_array_equal(frames[2], np.full((2, 3), (0, 0, 255), dtype=np.uint8))
        npt.assert_array_equal(
            frames[3], np.full((2, 3), (255, 255, 255), dtype=np.uint8)
        )

    def test_verify_answer_accepts_only_yes_and_no(self) -> None:
        self.assertIs(verify_answer('y'), True)
        self.assertIs(verify_answer('n'), False)
        self.assertIsNone(verify_answer('x'))
        self.assertIsNone(verify_answer(None))

    def test_fast_verify_shows_black_demo_black_for_each_demo(self) -> None:
        device = Device(led_count=2)
        phases = []

        def record_frames(
            client: LyteClient,
            retry: RetryConfig,
            host: str,
            device: Device,
            fps: float,
            duration: float,
            phase: str,
            frame_at: object,
        ) -> FadeReport:
            phases.append((phase, fps, duration))
            return FadeReport(
                fps=fps,
                phase=phase,
                total_frames=1,
                unique_frames=1,
                late_frames=0,
                short_sends=0,
                max_late_ms=0,
                elapsed_ms=0,
            )

        with (
            patch('lyte.fps_test.VERIFY_DEMOS', (VERIFY_DEMOS[0], VERIFY_DEMOS[1])),
            patch('lyte.fps_test.stream_frames', record_frames),
            patch('lyte.fps_test.report_fades'),
        ):
            results = run_fast_verify(
                LyteClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                '192.168.1.23',
                device,
            )

        self.assertEqual(
            phases,
            [
                ('primary-channels-black-before', 60.0, 1.0),
                ('primary-channels', 60.0, 3.0),
                ('primary-channels-black-after', 60.0, 1.0),
                ('moving-gradient-black-before', 60.0, 1.0),
                ('moving-gradient', 60.0, 3.0),
                ('moving-gradient-black-after', 60.0, 1.0),
            ],
        )
        self.assertEqual(
            results,
            (
                VerifyResult('primary-channels', None),
                VerifyResult('moving-gradient', None),
            ),
        )

    def test_report_verify_results_lists_status_groups(self) -> None:
        output = io.StringIO()
        errors = io.StringIO()

        with (
            patch('sys.stdout', output),
            patch('sys.stderr', errors),
        ):
            report_verify_results(
                (
                    VerifyResult('good', True),
                    VerifyResult('bad', False),
                    VerifyResult('shown', None),
                )
            )

        self.assertIn('Worked: good', output.getvalue())
        self.assertIn('Shown without pass/fail: shown', output.getvalue())
        self.assertIn('Did not work: bad', errors.getvalue())

    def test_run_fades_separates_each_test_with_black(self) -> None:
        device = Device(led_count=2)
        fades = []

        def record_fade(
            client: LyteClient,
            retry: RetryConfig,
            host: str,
            device: Device,
            first_frame: NDArray[np.uint8],
            second_frame: NDArray[np.uint8],
            fps: float,
            duration: float,
            phase: str,
        ) -> FadeReport:
            fades.append((first_frame.copy(), second_frame.copy(), fps, duration))
            return FadeReport(
                fps=fps,
                phase=phase,
                total_frames=1,
                unique_frames=1,
                late_frames=0,
                short_sends=0,
                max_late_ms=0,
                elapsed_ms=0,
            )

        with (
            patch('lyte.fps_test.FPS_VALUES', (20.0,)),
            patch('lyte.fps_test.stream_fade', record_fade),
            patch('lyte.fps_test.report_fades'),
        ):
            run_fades(
                LyteClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                '192.168.1.23',
                device,
                1.5,
                0,
            )

        self.assertEqual(len(fades), 3)
        npt.assert_array_equal(fades[0][0], np.zeros((2, 3), dtype=np.uint8))
        npt.assert_array_equal(fades[0][1], fades[1][0])
        npt.assert_array_equal(fades[1][1], fades[2][0])
        npt.assert_array_equal(fades[2][1], np.zeros((2, 3), dtype=np.uint8))
        self.assertEqual([f[2] for f in fades], [20.0, 20.0, 20.0])
        self.assertEqual([f[3] for f in fades], [1.5, 1.5, 1.5])

    def test_stream_fade_reports_unique_frames(self) -> None:
        device = Device(led_count=1)

        with (
            patch('lyte.fps_test.send_realtime_frame', return_value=3),
            patch('lyte.fps_test.time.sleep'),
        ):
            report = stream_fade(
                LyteClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                '192.168.1.23',
                device,
                np.array([[0, 0, 0]], dtype=np.uint8),
                np.array([[1, 0, 0]], dtype=np.uint8),
                2,
                2,
                'test',
            )

        self.assertEqual(report.total_frames, 4)
        self.assertEqual(report.unique_frames, 2)
        self.assertEqual(report.duplicate_frames, 2)
        self.assertEqual(report.short_sends, 0)

    def test_report_fades_reports_unexpected_events(self) -> None:
        output = io.StringIO()
        errors = io.StringIO()

        with (
            patch('sys.stdout', output),
            patch('sys.stderr', errors),
        ):
            report_fades(
                (
                    FadeReport(
                        fps=120,
                        phase='test',
                        total_frames=10,
                        unique_frames=4,
                        late_frames=2,
                        short_sends=1,
                        max_late_ms=1.5,
                        elapsed_ms=100,
                    ),
                )
            )

        self.assertIn('4/10 unique frames', output.getvalue())
        self.assertIn('2/10 times', errors.getvalue())
        self.assertIn('1 short UDP sends', errors.getvalue())


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
        client = LyteClient(host='192.168.1.23', timeout=1.5)

        self.assertEqual(client.host, '192.168.1.23')
        self.assertEqual(client.timeout, 1.5)

    def test_delete_uses_delete_request(self) -> None:
        FakeHttpConnection.response = FakeHttpResponse(200, b'{"code":1000}')
        FakeHttpConnection.requests = []

        with patch(
            'lyte.network.client.http.client.HTTPConnection', FakeHttpConnection
        ):
            response = LyteClient(host='192.168.1.23').delete(
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
                    '/xled/v1/movies',
                    None,
                    {'Content-Type': 'application/json'},
                )
            ],
        )

    def test_post_bytes_sends_binary_payload(self) -> None:
        FakeHttpConnection.response = FakeHttpResponse(200, b'{"code":1000}')
        FakeHttpConnection.requests = []

        with patch(
            'lyte.network.client.http.client.HTTPConnection', FakeHttpConnection
        ):
            response = LyteClient(host='192.168.1.23').post_bytes(
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
                    '/xled/v1/movies/full',
                    b'\x01\x02\x03',
                    {
                        'Content-Type': 'application/octet-stream',
                        'Content-Length': '3',
                    },
                )
            ],
        )

    def test_request_rejects_json_body_and_binary_payload(self) -> None:
        client = LyteClient(host='192.168.1.23')

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
            patch('lyte.network.client.http.client.HTTPConnection', FakeHttpConnection),
            self.assertRaises(UnsupportedEndpointError) as raised,
        ):
            LyteClient(host='192.168.1.23').get('missing', authenticated=False)

        self.assertEqual(raised.exception.path, 'missing')
        self.assertEqual(raised.exception.text, '{"code":1101}')

    def test_firmware_version_and_status_default_to_unauthenticated_gets(self) -> None:
        calls = []

        def get(
            self: LyteClient,
            path: str,
            authenticated: bool = True,
        ) -> LyteResponse:
            calls.append((self.host, path, authenticated))
            return LyteResponse(http_status=200, data={'code': 1000})

        client = LyteClient(host='192.168.1.23')

        with patch.object(LyteClient, 'get', get):
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
            self: LyteClient,
            path: str,
            authenticated: bool = True,
        ) -> LyteResponse:
            calls.append(('GET', self.host, path, authenticated))
            return LyteResponse(http_status=200, data={'code': 1000})

        def post(
            self: LyteClient,
            path: str,
            body: dict[str, object],
            authenticated: bool = True,
        ) -> LyteResponse:
            calls.append(('POST', self.host, path, body, authenticated))
            return LyteResponse(http_status=200, data={'code': 1000})

        client = LyteClient(host='192.168.1.23')

        with (
            patch.object(LyteClient, 'get', get),
            patch.object(LyteClient, 'post', post),
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
            self: LyteClient,
            path: str,
            authenticated: bool = True,
        ) -> LyteResponse:
            calls.append(('GET', self.host, path, authenticated))
            return LyteResponse(http_status=200, data={'code': 1000, 'value': 100})

        def post(
            self: LyteClient,
            path: str,
            body: dict[str, object],
            authenticated: bool = True,
        ) -> LyteResponse:
            calls.append(('POST', self.host, path, body, authenticated))
            return LyteResponse(http_status=200, data={'code': 1000})

        client = LyteClient(host='192.168.1.23')

        with (
            patch.object(LyteClient, 'get', get),
            patch.object(LyteClient, 'post', post),
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
            self: LyteClient,
            path: str,
            authenticated: bool = True,
        ) -> LyteResponse:
            calls.append(('GET', self.host, path, authenticated))
            return LyteResponse(http_status=200, data={'code': 1000})

        def post(
            self: LyteClient,
            path: str,
            body: dict[str, object],
            authenticated: bool = True,
        ) -> LyteResponse:
            calls.append(('POST', self.host, path, body, authenticated))
            return LyteResponse(http_status=200, data={'code': 1000})

        client = LyteClient(host='192.168.1.23')

        with (
            patch.object(LyteClient, 'get', get),
            patch.object(LyteClient, 'post', post),
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
            self: LyteClient,
            path: str,
            authenticated: bool = True,
        ) -> LyteResponse:
            calls.append(('GET', self.host, path, authenticated))
            return LyteResponse(http_status=200, data={'code': 1000})

        def post(
            self: LyteClient,
            path: str,
            body: dict[str, object],
            authenticated: bool = True,
        ) -> LyteResponse:
            calls.append(('POST', self.host, path, body, authenticated))
            return LyteResponse(http_status=200, data={'code': 1000})

        def delete(
            self: LyteClient,
            path: str,
            authenticated: bool = True,
        ) -> LyteResponse:
            calls.append(('DELETE', self.host, path, authenticated))
            return LyteResponse(http_status=200, data={'code': 1000})

        client = LyteClient(host='192.168.1.23')

        with (
            patch.object(LyteClient, 'get', get),
            patch.object(LyteClient, 'post', post),
            patch.object(LyteClient, 'delete', delete),
        ):
            client.get_layout_full()
            client.set_layout_full({'source': '3d'})
            client.delete_layout_full()
            client.get_led_config()
            client.set_led_config({'strings': []})

        self.assertEqual(
            calls,
            [
                ('GET', '192.168.1.23', 'led/layout/full', True),
                ('POST', '192.168.1.23', 'led/layout/full', {'source': '3d'}, True),
                ('DELETE', '192.168.1.23', 'led/layout/full', True),
                ('GET', '192.168.1.23', 'led/config', True),
                ('POST', '192.168.1.23', 'led/config', {'strings': []}, True),
            ],
        )

    def test_set_off_mode_uses_led_mode_off(self) -> None:
        calls = []

        def post(
            self: LyteClient,
            path: str,
            body: dict[str, object],
            authenticated: bool = True,
        ) -> LyteResponse:
            calls.append((self.host, path, body, authenticated))
            return LyteResponse(http_status=200, data={'code': 1000})

        client = LyteClient(host='192.168.1.23')

        with patch.object(LyteClient, 'post', post):
            response = client.set_off_mode()

        self.assertEqual(response.data, {'code': 1000})
        self.assertEqual(
            calls,
            [('192.168.1.23', 'led/mode', {'mode': 'off'}, True)],
        )


class SessionTests(unittest.TestCase):
    def test_xled_request_label_includes_method_path_and_host(self) -> None:
        self.assertEqual(
            xled_request_label('get', 'fw/version', '192.168.1.23'),
            'GET /xled/v1/fw/version on 192.168.1.23',
        )

    def test_set_mac_from_gestalt_updates_client(self) -> None:
        client = LyteClient(host='192.168.1.23')

        result = set_mac_from_gestalt(client, {'mac': 'AA:BB:CC:DD:EE:FF'})

        self.assertTrue(result)
        self.assertEqual(client.mac, 'AA:BB:CC:DD:EE:FF')

    def test_led_count_from_gestalt_returns_positive_ints(self) -> None:
        self.assertEqual(led_count_from_gestalt({'number_of_led': 250}), 250)
        self.assertIsNone(led_count_from_gestalt({'number_of_led': 0}))
        self.assertIsNone(led_count_from_gestalt({'number_of_led': '250'}))

    def test_turn_off_with_retry_uses_xled_label(self) -> None:
        labels = []

        def set_off_mode(
            client: LyteClient,
            retry: RetryConfig,
            label: str,
        ) -> LyteResponse:
            labels.append(label)
            return LyteResponse(http_status=200, data={'code': 1000})

        with patch('lyte.network.session.set_off_mode_with_retry', set_off_mode):
            result = turn_off_with_retry(
                LyteClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                '192.168.1.23',
            )

        self.assertTrue(result)
        self.assertEqual(labels, ['POST /xled/v1/led/mode on 192.168.1.23'])


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

        device = TwinklyDeviceInfo.from_gestalt(raw)

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

        report = read_endpoint(
            LyteClient(host='192.168.1.23'),
            RetryConfig(attempts=1, delay=0, backoff=1),
            'summary',
            'GET',
            'summary',
            request,
        )

        self.assertEqual(
            report,
            XledEndpointReport(
                name='summary',
                path='summary',
                supported=False,
                error='Resource not found.',
            ),
        )

    def test_authenticated_reports_probe_device_name_summary_and_echo(self) -> None:
        calls = []

        def get_layout_full(self: LyteClient) -> LyteResponse:
            calls.append(('GET', 'layout'))
            return LyteResponse(http_status=200, data={'code': 1000, 'coordinates': []})

        def get_led_config(self: LyteClient) -> LyteResponse:
            calls.append(('GET', 'led-config'))
            return LyteResponse(http_status=200, data={'code': 1000, 'strings': []})

        def get_led_mode(self: LyteClient) -> LyteResponse:
            calls.append(('GET', 'mode'))
            return LyteResponse(http_status=200, data={'code': 1000, 'mode': 'off'})

        def get_led_color(self: LyteClient) -> LyteResponse:
            calls.append(('GET', 'color'))
            return LyteResponse(http_status=200, data={'code': 1000, 'red': 1})

        def get_effects(self: LyteClient) -> LyteResponse:
            calls.append(('GET', 'effects'))
            return LyteResponse(http_status=200, data={'code': 1000, 'effects': []})

        def get_current_effect(self: LyteClient) -> LyteResponse:
            calls.append(('GET', 'current-effect'))
            return LyteResponse(http_status=200, data={'code': 1000, 'effect_id': 0})

        def get_brightness(self: LyteClient) -> LyteResponse:
            calls.append(('GET', 'brightness'))
            return LyteResponse(http_status=200, data={'code': 1000, 'value': 75})

        def get_saturation(self: LyteClient) -> LyteResponse:
            calls.append(('GET', 'saturation'))
            return LyteResponse(http_status=200, data={'code': 1000, 'value': 80})

        def get_device_name(self: LyteClient) -> LyteResponse:
            calls.append(('GET', 'device_name'))
            return LyteResponse(http_status=200, data={'code': 1000, 'name': 'Tree'})

        def get_summary(self: LyteClient) -> LyteResponse:
            calls.append(('GET', 'summary'))
            return LyteResponse(http_status=200, data={'code': 1000, 'leds': 250})

        def echo(self: LyteClient, body: dict[str, object]) -> LyteResponse:
            calls.append(('POST', 'echo', body))
            return LyteResponse(http_status=200, data={'code': 1000, 'json': body})

        with (
            patch.object(LyteClient, 'get_layout_full', get_layout_full),
            patch.object(LyteClient, 'get_led_config', get_led_config),
            patch.object(LyteClient, 'get_led_mode', get_led_mode),
            patch.object(LyteClient, 'get_led_color', get_led_color),
            patch.object(LyteClient, 'get_effects', get_effects),
            patch.object(LyteClient, 'get_current_effect', get_current_effect),
            patch.object(LyteClient, 'get_brightness', get_brightness),
            patch.object(LyteClient, 'get_saturation', get_saturation),
            patch.object(LyteClient, 'get_device_name', get_device_name),
            patch.object(LyteClient, 'get_summary', get_summary),
            patch.object(LyteClient, 'echo', echo),
        ):
            reports = authenticated_reports(
                LyteClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
            )

        self.assertEqual(
            [i.name for i in reports],
            [
                'layout',
                'led-config',
                'mode',
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
        client = LyteClient(host='192.168.1.23')

        with (
            patch('lyte.diagnostic.discover_host', return_value='192.168.1.23'),
            patch('lyte.diagnostic.LyteClient', return_value=client),
            patch(
                'lyte.diagnostic.read_endpoint',
                side_effect=(
                    XledEndpointReport(
                        name='gestalt',
                        path='gestalt',
                        supported=True,
                        data={'device_name': 'Tree', 'mac': 'AA', 'number_of_led': 250},
                    ),
                    XledEndpointReport(
                        name='firmware',
                        path='fw/version',
                        supported=True,
                        data={'version': '1.0'},
                    ),
                    XledEndpointReport(
                        name='status',
                        path='status',
                        supported=True,
                        data={'mode': 'rt'},
                    ),
                ),
            ),
            patch('lyte.diagnostic.authenticate_device', return_value=object()),
            patch('lyte.diagnostic.authenticated_reports', return_value=()),
            patch('lyte.diagnostic.turn_off_with_retry', return_value=True) as turn_off,
            patch('sys.stdout', output),
        ):
            result = run_diagnostic(DiagnosticConfig())

        self.assertEqual(result, 0)
        self.assertEqual(client.mac, 'AA')
        turn_off.assert_called_once()
        self.assertIn('Device name: Tree', output.getvalue())
        self.assertIn("firmware: {'version': '1.0'}", output.getvalue())


class XledControlTests(unittest.TestCase):
    def test_output_control_accepts_string_values_from_device(self) -> None:
        control = OutputControl.from_response({'mode': 'enabled', 'value': '75'})

        self.assertEqual(control.mode, 'enabled')
        self.assertEqual(control.type, 'A')
        self.assertEqual(control.value, 75)

    def test_output_control_request_body_uses_documented_shape(self) -> None:
        self.assertEqual(
            OutputControl(value=80).request_body(),
            {'mode': 'enabled', 'type': 'A', 'value': 80},
        )

    def test_layout_model_accepts_documented_shape(self) -> None:
        layout = XledLayout.from_response(
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
            layout.request_body(),
            {
                'aspectXY': 1,
                'aspectXZ': 2,
                'coordinates': [{'x': 1.0, 'y': 2.0, 'z': 3.0}],
                'source': '3d',
                'synthesized': False,
                'uuid': '00000000-0000-0000-0000-000000000000',
            },
        )

    def test_read_output_control_dispatches_by_kind(self) -> None:
        client = LyteClient(host='192.168.1.23')

        with (
            patch.object(
                LyteClient,
                'get_brightness',
                return_value=LyteResponse(
                    http_status=200,
                    data={'mode': 'enabled', 'value': 75},
                ),
            ) as get_brightness,
            patch.object(
                LyteClient,
                'get_saturation',
                return_value=LyteResponse(
                    http_status=200,
                    data={'mode': 'enabled', 'value': 80},
                ),
            ) as get_saturation,
        ):
            brightness = read_output_control(client, 'brightness')
            saturation = read_output_control(client, 'saturation')

        self.assertEqual(brightness.value, 75)
        self.assertEqual(saturation.value, 80)
        get_brightness.assert_called_once()
        get_saturation.assert_called_once()

    def test_write_output_control_dispatches_by_kind(self) -> None:
        client = LyteClient(host='192.168.1.23')
        control = OutputControl(value=90)

        with (
            patch.object(LyteClient, 'set_brightness') as set_brightness,
            patch.object(LyteClient, 'set_saturation') as set_saturation,
        ):
            write_output_control(client, 'brightness', control)
            write_output_control(client, 'saturation', control)

        set_brightness.assert_called_once_with(
            {'mode': 'enabled', 'type': 'A', 'value': 90}
        )
        set_saturation.assert_called_once_with(
            {'mode': 'enabled', 'type': 'A', 'value': 90}
        )

    def test_run_output_control_get_reports_current_value(self) -> None:
        output = io.StringIO()
        client = LyteClient(host='192.168.1.23')

        with (
            patch('lyte.xled.discover_host', return_value='192.168.1.23'),
            patch('lyte.xled.LyteClient', return_value=client),
            patch('lyte.xled.prepare_authenticated_client'),
            patch(
                'lyte.xled.read_output_control',
                return_value=OutputControl(value=75),
            ),
            patch('lyte.xled.turn_off_with_retry', return_value=True) as turn_off,
            patch('sys.stdout', output),
        ):
            result = run_output_control(
                DiagnosticConfig(),
                'brightness',
                'get',
                None,
            )

        self.assertEqual(result, 0)
        turn_off.assert_called_once()
        self.assertIn('[brightness] mode=enabled type=A value=75', output.getvalue())

    def test_run_output_control_set_writes_value(self) -> None:
        output = io.StringIO()
        client = LyteClient(host='192.168.1.23')

        with (
            patch('lyte.xled.discover_host', return_value='192.168.1.23'),
            patch('lyte.xled.LyteClient', return_value=client),
            patch('lyte.xled.prepare_authenticated_client'),
            patch('lyte.xled.write_output_control') as write_output_control,
            patch('lyte.xled.turn_off_with_retry', return_value=True) as turn_off,
            patch('sys.stdout', output),
        ):
            result = run_output_control(
                DiagnosticConfig(),
                'saturation',
                'set',
                80,
            )

        self.assertEqual(result, 0)
        turn_off.assert_called_once()
        write_output_control.assert_called_once_with(
            client,
            'saturation',
            OutputControl(value=80),
        )
        self.assertIn(
            '[saturation] set mode=enabled type=A value=80',
            output.getvalue(),
        )

    def test_run_mode_control_sets_mode_then_turns_off(self) -> None:
        client = LyteClient(host='192.168.1.23')

        with (
            patch('lyte.xled.discover_host', return_value='192.168.1.23'),
            patch('lyte.xled.LyteClient', return_value=client),
            patch('lyte.xled.prepare_authenticated_client'),
            patch.object(LyteClient, 'set_led_mode') as set_led_mode,
            patch('lyte.xled.turn_off_with_retry', return_value=True) as turn_off,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            result = run_mode_control(DiagnosticConfig(), 'set', 'demo')

        self.assertEqual(result, 0)
        set_led_mode.assert_called_once_with({'mode': 'demo'})
        turn_off.assert_called_once()

    def test_run_color_control_sets_rgb_then_turns_off(self) -> None:
        client = LyteClient(host='192.168.1.23')

        with (
            patch('lyte.xled.discover_host', return_value='192.168.1.23'),
            patch('lyte.xled.LyteClient', return_value=client),
            patch('lyte.xled.prepare_authenticated_client'),
            patch.object(LyteClient, 'set_led_color') as set_led_color,
            patch('lyte.xled.turn_off_with_retry', return_value=True) as turn_off,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            result = run_color_control(DiagnosticConfig(), 'set', 1, 2, 3)

        self.assertEqual(result, 0)
        set_led_color.assert_called_once_with(
            {'mode': 'rgb', 'red': 1, 'green': 2, 'blue': 3}
        )
        turn_off.assert_called_once()

    def test_run_effect_control_sets_current_effect_then_turns_off(self) -> None:
        client = LyteClient(host='192.168.1.23')

        with (
            patch('lyte.xled.discover_host', return_value='192.168.1.23'),
            patch('lyte.xled.LyteClient', return_value=client),
            patch('lyte.xled.prepare_authenticated_client'),
            patch.object(LyteClient, 'set_current_effect') as set_current_effect,
            patch('lyte.xled.turn_off_with_retry', return_value=True) as turn_off,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            result = run_effect_control(DiagnosticConfig(), 'set-current', 4)

        self.assertEqual(result, 0)
        set_current_effect.assert_called_once_with({'effect_id': 4})
        turn_off.assert_called_once()

    def test_run_layout_control_exports_layout_then_turns_off(self) -> None:
        output = io.StringIO()
        client = LyteClient(host='192.168.1.23')

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'layout.json'
            with (
                patch('lyte.xled.discover_host', return_value='192.168.1.23'),
                patch('lyte.xled.LyteClient', return_value=client),
                patch('lyte.xled.prepare_authenticated_client'),
                patch.object(
                    LyteClient,
                    'get_layout_full',
                    return_value=LyteResponse(
                        http_status=200,
                        data={'source': '3d', 'coordinates': []},
                    ),
                ),
                patch('lyte.xled.turn_off_with_retry', return_value=True) as turn_off,
                patch('sys.stdout', output),
            ):
                result = run_layout_control(DiagnosticConfig(), 'export', path)

            self.assertEqual(result, 0)
            self.assertEqual(
                json.loads(path.read_text()),
                {'coordinates': [], 'source': '3d'},
            )
            turn_off.assert_called_once()
            self.assertIn('[layout] exported', output.getvalue())

    def test_run_layout_control_uploads_layout_then_turns_off(self) -> None:
        client = LyteClient(host='192.168.1.23')

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
                patch('lyte.xled.discover_host', return_value='192.168.1.23'),
                patch('lyte.xled.LyteClient', return_value=client),
                patch('lyte.xled.prepare_authenticated_client'),
                patch.object(LyteClient, 'set_layout_full') as set_layout_full,
                patch('lyte.xled.turn_off_with_retry', return_value=True) as turn_off,
                patch('sys.stdout', new_callable=io.StringIO),
            ):
                result = run_layout_control(DiagnosticConfig(), 'upload', path)

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
        client = LyteClient(host='192.168.1.23')

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({'strings': [{'first_led_id': 0}]}))
            with (
                patch('lyte.xled.discover_host', return_value='192.168.1.23'),
                patch('lyte.xled.LyteClient', return_value=client),
                patch('lyte.xled.prepare_authenticated_client'),
                patch.object(LyteClient, 'set_led_config') as set_led_config,
                patch('lyte.xled.turn_off_with_retry', return_value=True) as turn_off,
                patch('sys.stdout', new_callable=io.StringIO),
            ):
                result = run_led_config_control(DiagnosticConfig(), 'set', path)

        self.assertEqual(result, 0)
        set_led_config.assert_called_once_with({'strings': [{'first_led_id': 0}]})
        turn_off.assert_called_once()


class RuntimeTests(unittest.TestCase):
    def test_read_device_led_count_uses_configured_count_after_reading_gestalt(
        self,
    ) -> None:
        client = LyteClient(host='192.168.1.23')

        with patch(
            'lyte.runtime.read_gestalt',
            return_value={'mac': 'AA', 'number_of_led': 250},
        ):
            led_count, gestalt = read_device_led_count(
                client,
                RetryConfig(attempts=1, delay=0, backoff=1),
                100,
                'read',
            )

        self.assertEqual(led_count, 100)
        self.assertEqual(gestalt, {'mac': 'AA', 'number_of_led': 250})
        self.assertEqual(client.mac, 'AA')

    def test_read_device_led_count_detects_count_from_gestalt(self) -> None:
        client = LyteClient(host='192.168.1.23')

        with patch(
            'lyte.runtime.read_gestalt',
            return_value={'mac': 'AA', 'number_of_led': 250},
        ):
            led_count, _gestalt = read_device_led_count(
                client,
                RetryConfig(attempts=1, delay=0, backoff=1),
                None,
                'read',
            )

        self.assertEqual(led_count, 250)

    def test_send_authenticated_frame_returns_none_without_token(self) -> None:
        frame = solid_rgb_frame(1, 255, 0, 0)

        sent = send_authenticated_frame(
            LyteClient(host='192.168.1.23'),
            '192.168.1.23',
            frame,
            RetryConfig(attempts=1, delay=0, backoff=1),
            'send',
        )

        self.assertIsNone(sent)


class LoggingTests(unittest.TestCase):
    def test_logging_is_disabled_by_default(self) -> None:
        self.assertFalse(LOGGING)

    def test_error_logging_is_always_displayed(self) -> None:
        output = io.StringIO()

        with patch('sys.stderr', output):
            log_error('failure')

        self.assertEqual(output.getvalue(), 'failure\n')

    def test_regular_logging_is_hidden_by_default(self) -> None:
        output = io.StringIO()

        with patch('sys.stdout', output):
            log('hidden')

        self.assertEqual(output.getvalue(), '')

    def test_status_logging_is_always_displayed(self) -> None:
        output = io.StringIO()

        with patch('sys.stdout', output):
            log_status('visible')

        self.assertEqual(output.getvalue(), 'visible\n')


class HamiltonianTests(unittest.TestCase):
    def test_next_hamiltonian_matches_loop_special_case(self) -> None:
        self.assertEqual(next_hamiltonian(4, 1, 0, 0), (0, 0, 0))
        self.assertEqual(next_hamiltonian(4, 1, 0, 1), (2, 0, 1))

    def test_counter_produces_scaled_rgb_values(self) -> None:
        counter = HamiltonianCounter(n=4)

        self.assertEqual(counter.next_color(), (0, 0, 0))
        self.assertEqual(counter.next_color(), (0, 0, 64))
        self.assertEqual(counter.next_color(), (0, 0, 128))

    def test_hamiltonian_colors_generates_one_full_cycle(self) -> None:
        colors = list(hamiltonian_colors(n=4))

        self.assertEqual(len(colors), 64)
        self.assertEqual(colors[:3], [(0, 0, 0), (0, 0, 64), (0, 0, 128)])

    def test_counter_supports_order_and_inversion(self) -> None:
        counter = HamiltonianCounter(n=4, order='bgr', inverted='r')

        self.assertEqual(counter.next_color(), (192, 0, 0))
        self.assertEqual(counter.next_color(), (128, 0, 0))

    def test_parse_order_rejects_invalid_orders(self) -> None:
        with self.assertRaises(ValueError):
            parse_order('rrg')

    def test_hamiltonian_returns_one_rgb_triplet_per_led(self) -> None:
        animation = Hamiltonian(n=4, speed=4)
        device, state = initial_state(animation, 3)
        state.fps = 4

        npt.assert_array_equal(
            render(animation, device, state),
            np.zeros((3, 3), dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(animation, device, state),
            np.zeros((3, 3), dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(animation, device, state),
            np.array([[0, 0, 0], [0, 0, 0], [0, 0, 64]], dtype=np.uint8),
        )


class RandomWalkTests(unittest.TestCase):
    def test_perturb_matches_original_random_step(self) -> None:
        generator = random.Random(1)

        self.assertAlmostEqual(perturb(0, 5, (0, 10), generator), -3.656357558875988)
        self.assertAlmostEqual(perturb(9, 5, (0, 10), generator), 5.525662630627673)

    def test_next_color_returns_current_color_before_advancing(self) -> None:
        walk = RandomWalk(color=(10.0, 20.0, 30.0), variance=0)
        device = Device(led_count=1)
        state = walk.initial_state(device)

        self.assertEqual(walk.next_color(state, 0), (10.0, 20.0, 30.0))
        self.assertEqual(walk.next_color(state, 1), (10.0, 20.0, 30.0))

    def test_render_streams_walk_through_leds(self) -> None:
        walk = RandomWalk(speed=1, color=(10.0, 20.0, 30.0), variance=0)
        device, state = initial_state(walk, 2)
        state.fps = 1

        npt.assert_array_equal(
            render(walk, device, state),
            np.zeros((2, 3), dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(walk, device, state),
            np.array([[0, 0, 0], [10, 20, 30]], dtype=np.uint8),
        )


class BiblioPixelTests(unittest.TestCase):
    def test_color_fill_fills_all_leds(self) -> None:
        animation = ColorFill(color=(1, 2, 3))
        device, state = initial_state(animation, 3)

        npt.assert_array_equal(
            render(animation, device, state),
            np.array([[1, 2, 3], [1, 2, 3], [1, 2, 3]], dtype=np.uint8),
        )

    def test_color_chase_moves_lit_window(self) -> None:
        chase = ColorChase(color=(9, 8, 7), width=2)
        device, state = initial_state(chase, 5)

        npt.assert_array_equal(
            render(chase, device, state),
            np.array(
                [[9, 8, 7], [9, 8, 7], [0, 0, 0], [0, 0, 0], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )
        npt.assert_array_equal(
            render(chase, device, state),
            np.array(
                [[0, 0, 0], [9, 8, 7], [9, 8, 7], [0, 0, 0], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )

    def test_color_wipe_preserves_previous_lit_leds(self) -> None:
        wipe = ColorWipe(color=(1, 2, 3))
        device, state = initial_state(wipe, 4)

        npt.assert_array_equal(
            render(wipe, device, state),
            np.array(
                [[1, 2, 3], [0, 0, 0], [0, 0, 0], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )
        npt.assert_array_equal(
            render(wipe, device, state),
            np.array(
                [[1, 2, 3], [1, 2, 3], [0, 0, 0], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )

    def test_alternates_flips_each_frame(self) -> None:
        alternates = Alternates(color1=(1, 1, 1), color2=(2, 2, 2))
        device, state = initial_state(alternates, 4)

        npt.assert_array_equal(
            render(alternates, device, state),
            np.array(
                [[2, 2, 2], [1, 1, 1], [2, 2, 2], [1, 1, 1]],
                dtype=np.uint8,
            ),
        )
        npt.assert_array_equal(
            render(alternates, device, state),
            np.array(
                [[1, 1, 1], [2, 2, 2], [1, 1, 1], [2, 2, 2]],
                dtype=np.uint8,
            ),
        )

    def test_color_pattern_repeats_color_widths(self) -> None:
        pattern = ColorPattern(
            colors=((1, 0, 0), (0, 2, 0), (0, 0, 3)),
            width=2,
        )
        device, state = initial_state(pattern, 6)

        npt.assert_array_equal(
            render(pattern, device, state),
            np.array(
                [[1, 0, 0], [1, 0, 0], [0, 2, 0], [0, 2, 0], [0, 0, 3], [0, 0, 3]],
                dtype=np.uint8,
            ),
        )
        npt.assert_array_equal(
            render(pattern, device, state),
            np.array(
                [[1, 0, 0], [0, 2, 0], [0, 2, 0], [0, 0, 3], [0, 0, 3], [1, 0, 0]],
                dtype=np.uint8,
            ),
        )

    def test_color_fade_scales_color_across_span(self) -> None:
        fade = ColorFade(
            colors=((10, 20, 30),),
            level_step=225,
            start=1,
            end=2,
        )
        device, state = initial_state(fade, 4)

        npt.assert_array_equal(
            render(fade, device, state),
            np.array(
                [[0, 0, 0], [1, 2, 4], [1, 2, 4], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )

    def test_party_mode_alternates_color_and_blank_frames(self) -> None:
        party = PartyMode(colors=((1, 2, 3), (4, 5, 6)))
        device, state = initial_state(party, 2)

        npt.assert_array_equal(
            render(party, device, state),
            np.array([[1, 2, 3], [1, 2, 3]], dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(party, device, state),
            np.zeros((2, 3), dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(party, device, state),
            np.array([[4, 5, 6], [4, 5, 6]], dtype=np.uint8),
        )

    def test_fire_flies_lights_seeded_random_pixels(self) -> None:
        fire_flies = FireFlies(
            colors=((1, 2, 3),),
            width=2,
            count=1,
            seed=1,
        )
        device, state = initial_state(fire_flies, 5)

        frame = render(fire_flies, device, state)

        self.assertEqual(frame.shape, (5, 3))
        self.assertGreaterEqual(np.count_nonzero(frame[:, 0]), 1)
        self.assertLessEqual(np.count_nonzero(frame[:, 0]), 2)

    def test_saber_blade_extends_then_retracts(self) -> None:
        saber = SaberBlade(colors=((1, 2, 3),), speed=1)
        device, state = initial_state(saber, 3)

        npt.assert_array_equal(
            render(saber, device, state),
            np.zeros((3, 3), dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(saber, device, state),
            np.array([[1, 2, 3], [0, 0, 0], [0, 0, 0]], dtype=np.uint8),
        )

    def test_rainbows_generate_wheel_frames(self) -> None:
        rainbow = Rainbow()
        rainbow_cycle = RainbowCycle()
        device, state = initial_state(rainbow, 3)
        cycle_device, cycle_state = initial_state(rainbow_cycle, 3)

        npt.assert_array_equal(
            render(rainbow, device, state),
            np.array([[255, 0, 0], [252, 3, 0], [249, 6, 0]], dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(rainbow_cycle, cycle_device, cycle_state),
            np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], dtype=np.uint8),
        )

    def test_linear_rainbow_fills_progressively(self) -> None:
        rainbow = LinearRainbow()
        device, state = initial_state(rainbow, 3)

        npt.assert_array_equal(
            render(rainbow, device, state),
            np.array([[255, 0, 0], [0, 0, 0], [0, 0, 0]], dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(rainbow, device, state),
            np.array([[252, 3, 0], [252, 3, 0], [0, 0, 0]], dtype=np.uint8),
        )

    def test_halves_rainbow_expands_from_center(self) -> None:
        rainbow = HalvesRainbow()
        device, state = initial_state(rainbow, 5)

        npt.assert_array_equal(
            render(rainbow, device, state),
            np.array(
                [[0, 0, 0], [0, 0, 0], [255, 0, 0], [0, 0, 0], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )
        npt.assert_array_equal(
            render(rainbow, device, state),
            np.array(
                [[0, 0, 0], [240, 15, 0], [255, 0, 0], [240, 15, 0], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )

    def test_larson_scanner_bounces_lit_pixel(self) -> None:
        scanner = LarsonScanner(color=(1, 2, 3), tail=0)
        device, state = initial_state(scanner, 3)

        npt.assert_array_equal(
            render(scanner, device, state),
            np.array([[1, 2, 3], [0, 0, 0], [0, 0, 0]], dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(scanner, device, state),
            np.array([[0, 0, 0], [1, 2, 3], [0, 0, 0]], dtype=np.uint8),
        )

    def test_pulse_starts_when_chance_always_hits(self) -> None:
        pulse = Pulse(
            colors=((10, 20, 30),),
            tail=0,
            chance=100,
            min_speed=1,
            max_speed=2,
            seed=1,
        )
        device, state = initial_state(pulse, 4)

        frame = render(pulse, device, state)

        self.assertGreater(np.count_nonzero(frame), 0)

    def test_pixel_ping_pong_fades_previous_pixels(self) -> None:
        ping_pong = PixelPingPong(color=(10, 0, 0), fade_delay=1)
        device, state = initial_state(ping_pong, 3)

        npt.assert_array_equal(
            render(ping_pong, device, state),
            np.array([[10, 0, 0], [0, 0, 0], [0, 0, 0]], dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(ping_pong, device, state),
            np.array([[0, 0, 0], [10, 0, 0], [0, 0, 0]], dtype=np.uint8),
        )

    def test_searchlights_blend_moving_beams(self) -> None:
        searchlights = Searchlights(
            colors=((10, 0, 0), (0, 20, 0), (0, 0, 30)),
            tail=0,
            seed=1,
        )
        device, state = initial_state(searchlights, 8)

        frame = render(searchlights, device, state)

        self.assertEqual(frame.shape, (8, 3))
        self.assertGreater(np.count_nonzero(frame), 0)

    def test_wave_generates_sine_colored_frame(self) -> None:
        wave = Wave(color=(10, 20, 30), cycles=1)
        device, state = initial_state(wave, 3)

        npt.assert_array_equal(
            render(wave, device, state),
            np.array([[10, 20, 30], [10, 20, 30], [10, 20, 30]], dtype=np.uint8),
        )

    def test_twinkle_lights_seeded_random_pixel(self) -> None:
        twinkle = Twinkle(
            colors=((10, 20, 30),),
            density=100,
            speed=10,
            seed=1,
        )
        device, state = initial_state(twinkle, 4)

        frame = render(twinkle, device, state)

        self.assertGreater(np.count_nonzero(frame), 0)

    def test_white_twinkle_uses_white_pixels(self) -> None:
        twinkle = WhiteTwinkle(density=100, speed=10, seed=1)
        device, state = initial_state(twinkle, 4)

        frame = render(twinkle, device, state)

        self.assertGreater(np.count_nonzero(frame), 0)
        self.assertTrue(np.all(frame[frame > 0] == int(np.max(frame))))


class PreviewTests(unittest.TestCase):
    def test_layout_accepts_explicit_coords(self) -> None:
        layout = Layout(coords=[[0.0, 0.0], [1.0, 0.5]])

        self.assertEqual(layout.points(), [[0.0, 0.0], [1.0, 0.5]])

    def test_layout_generates_grid_from_dims_and_spacing(self) -> None:
        layout = Layout(dims=[2, 3], spacing=[2.0, 3.0])

        self.assertEqual(
            layout.points(),
            [
                [0.0, 0.0],
                [2.0, 0.0],
                [4.0, 0.0],
                [0.0, 3.0],
                [2.0, 3.0],
                [4.0, 3.0],
            ],
        )

    def test_layout_requires_exactly_one_coordinate_source(self) -> None:
        with self.assertRaises(ValueError):
            Layout()
        with self.assertRaises(ValueError):
            Layout(coords=[[0.0, 0.0]], dims=[1, 1])

    def test_animation_document_embeds_base64_frames(self) -> None:
        document = animation_document(
            ColorFill(color=(1, 2, 3)),
            Layout(name='preview', dims=[1, 2]),
            fps=2,
            duration=1,
            led_size=2.5,
        )

        data = preview_data(document)

        self.assertEqual(data['name'], 'preview')
        self.assertEqual(data['coords'], [[0.0, 0.0], [1.0, 0.0]])
        self.assertEqual(data['ledSize'], 2.5)
        frames = data['frames']
        if not isinstance(frames, list):
            self.fail('frames must be a list')
        first_frame = frames[0]
        if not isinstance(first_frame, str):
            self.fail('frames must contain strings')
        self.assertEqual(len(frames), 2)
        self.assertEqual(
            base64.b64decode(first_frame),
            bytes([1, 2, 3, 1, 2, 3]),
        )

    def test_render_animation_html_writes_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'preview.html'

            render_animation_html(
                ColorFill(color=(1, 2, 3)),
                Layout(coords=[[0.0, 0.0]]),
                path,
                fps=1,
                duration=1,
                led_size=3,
            )

            self.assertIn('<canvas', path.read_text())


def preview_data(document: str) -> dict[str, object]:
    start = document.index('const data = ') + len('const data = ')
    end = document.index(';\nconst canvas', start)
    return json.loads(document[start:end])


class RetryTests(unittest.TestCase):
    def test_retry_call_retries_retryable_result_failures(self) -> None:
        calls = 0

        def operation() -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RetryableTestError('empty reply')
            return 'ok'

        retry = RetryConfig(
            attempts=2,
            delay=0,
            backoff=1,
            backoff_after=1,
        )

        with (
            patch('sys.stdout', new_callable=io.StringIO),
            patch(
                'sys.stderr',
                new_callable=io.StringIO,
            ),
        ):
            result = retry_call(
                'operation',
                retry,
                operation,
                (RetryableTestError,),
            )

        self.assertEqual(result, 'ok')
        self.assertEqual(calls, 2)

    def test_retry_call_delays_backoff_until_configured_attempt(self) -> None:
        calls = 0
        sleeps = []

        def operation() -> str:
            nonlocal calls
            calls += 1
            if calls < 4:
                raise RetryableTestError('empty reply')
            return 'ok'

        retry = RetryConfig(
            attempts=4,
            delay=0.01,
            backoff=2,
            backoff_after=10,
        )

        with (
            patch('sys.stdout', new_callable=io.StringIO),
            patch(
                'sys.stderr',
                new_callable=io.StringIO,
            ),
            patch('lyte.retry.time.sleep', sleeps.append),
        ):
            result = retry_call(
                'operation',
                retry,
                operation,
                (RetryableTestError,),
            )

        self.assertEqual(result, 'ok')
        self.assertEqual(sleeps, [0.01, 0.01, 0.01])

    def test_retry_call_prints_only_final_failure(self) -> None:
        def operation() -> str:
            raise RetryableTestError('empty reply')

        retry = RetryConfig(
            attempts=3,
            delay=0,
            backoff=1,
            backoff_after=1,
        )
        error_output = io.StringIO()

        with (
            patch('sys.stdout', new_callable=io.StringIO),
            patch('sys.stderr', error_output),
            patch('lyte.retry.time.sleep'),
        ):
            result = retry_call(
                'operation',
                retry,
                operation,
                (RetryableTestError,),
            )

        self.assertIsNone(result)
        self.assertNotIn('attempt 1/3', error_output.getvalue())
        self.assertNotIn('attempt 2/3', error_output.getvalue())
        self.assertIn('attempt 3/3', error_output.getvalue())


class RetryableTestError(Exception):
    pass


class DiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        path = Path(__file__).parents[1] / 'scripts' / 'lyte_diagnostic.py'
        spec = importlib.util.spec_from_file_location('lyte_diagnostic', path)
        assert spec is not None
        assert spec.loader is not None
        cls.diagnostic = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.diagnostic)

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

    def test_parse_args_uses_slower_network_retry_defaults(self) -> None:
        with patch('sys.argv', ['lyte_diagnostic.py']):
            config = self.diagnostic.parse_args()

        self.assertEqual(config.retry.attempts, 10)
        self.assertEqual(config.retry.delay, 0.5)
        self.assertEqual(config.discovery_retry.delay, 0.05)


class HamiltonianAnimationTests(unittest.TestCase):
    def test_hamiltonian_renders_rgb_frame(self) -> None:
        animation = Hamiltonian(speed=64, n=4)
        device, state = initial_state(animation, 3)
        state.fps = 1

        frame = render(animation, device, state)

        self.assertEqual(frame.shape, (3, 3))
        self.assertEqual(frame.dtype, np.uint8)


class AnimateScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        path = Path(__file__).parents[1] / 'scripts' / 'lyte_animate.py'
        spec = importlib.util.spec_from_file_location('lyte_animate', path)
        assert spec is not None
        assert spec.loader is not None
        cls.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.script)

    def test_build_animation_creates_hamiltonian(self) -> None:
        with patch('sys.argv', ['lyte_animate.py', 'hamiltonian']):
            args = self.script.parse_args()

        animation = self.script.build_animation(args)

        self.assertIsInstance(animation, Hamiltonian)

    def test_parse_args_defaults_to_random_animation(self) -> None:
        with patch('sys.argv', ['lyte_animate.py']):
            args = self.script.parse_args()

        self.assertEqual(args.animation, 'random')

    def test_random_mode_uses_hamiltonian_settings(self) -> None:
        with patch('sys.argv', ['lyte_animate.py']):
            args = self.script.parse_args()

        with patch.object(self.script, 'RANDOM_ANIMATIONS', ('hamiltonian',)):
            segment_args = self.script.random_animation_args(
                args, random.Random(1), None
            )

        self.assertEqual(segment_args.animation, 'hamiltonian')
        self.assertEqual(segment_args.n, 256)
        self.assertEqual(segment_args.speed, 100)

    def test_random_mode_uses_exciting_random_walk_settings(self) -> None:
        with patch('sys.argv', ['lyte_animate.py']):
            args = self.script.parse_args()

        with patch.object(self.script, 'RANDOM_ANIMATIONS', ('random_walk',)):
            segment_args = self.script.random_animation_args(
                args, random.Random(1), None
            )

        self.assertEqual(segment_args.animation, 'random_walk')
        self.assertEqual(segment_args.speed, self.script.RANDOM_WALK_SPEED)
        self.assertEqual(segment_args.variance, self.script.RANDOM_WALK_VARIANCE)
        self.assertEqual(segment_args.bounds, self.script.RANDOM_WALK_BOUNDS)
        self.assertEqual(segment_args.period, self.script.RANDOM_WALK_PERIOD)
        self.assertTrue(segment_args.pre_fill)

    def test_random_mode_prints_selected_pattern(self) -> None:
        with patch('sys.argv', ['lyte_animate.py', '--duration', '1']):
            args = self.script.parse_args()

        output = io.StringIO()

        with (
            patch.object(self.script, 'RANDOM_ANIMATIONS', ('hamiltonian',)),
            patch.object(self.script, 'build_animation', return_value=ColorFill()),
            patch.object(self.script, 'run_animation_state') as run_animation_state,
            patch.object(self.script.time, 'monotonic', side_effect=[0, 0, 0, 2]),
            patch('sys.stdout', output),
        ):
            self.script.run_random_animations(
                args,
                LyteClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                '192.168.1.23',
                Device(led_count=3),
            )

        self.assertIn('[pattern] hamiltonian', output.getvalue())
        run_animation_state.assert_called_once()

    def test_random_overlap_is_half_the_pattern_duration(self) -> None:
        self.assertEqual(self.script.random_overlap_duration(10), 5)
        self.assertEqual(self.script.random_overlap_duration(30), 15)

    def test_blend_frames_crossfades_rgb_values(self) -> None:
        current_frame = np.array([[0, 100, 200]], dtype=np.uint8)
        next_frame = np.array([[100, 200, 0]], dtype=np.uint8)

        npt.assert_array_equal(
            self.script.blend_frames(current_frame, next_frame, 0.25),
            np.array([[25, 125, 150]], dtype=np.uint8),
        )

    def test_crossfade_advances_both_streamers(self) -> None:
        class ConstantAnimation(Animation):
            color: tuple[int, int, int]
            calls: int = 0

            def render(self, device: Device, state: State) -> NDArray[np.uint8]:
                state.frame += 1
                object.__setattr__(self, 'calls', self.calls + 1)
                return np.array([self.color], dtype=np.uint8)

        current_animation = ConstantAnimation(color=(0, 0, 0))
        next_animation = ConstantAnimation(color=(100, 200, 250))
        device = Device(led_count=1)
        current_state = State()
        next_state = State()
        args = argparse.Namespace(fps=1, animation='next')
        sent_frames = []

        with (
            patch.object(
                self.script.time,
                'monotonic',
                side_effect=[0.0, 0.5, 0.5, 0.5, 2.0],
            ),
            patch.object(self.script.time, 'sleep'),
            patch.object(
                self.script, 'send_realtime_frame', lambda *a: sent_frames.append(a[-1])
            ),
        ):
            self.script.run_crossfade(
                current_animation,
                current_state,
                next_animation,
                next_state,
                args,
                LyteClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                '192.168.1.23',
                device,
                1.0,
            )

        self.assertEqual(current_animation.calls, 1)
        self.assertEqual(next_animation.calls, 1)
        npt.assert_array_equal(
            sent_frames[0],
            np.array([[50, 100, 125]], dtype=np.uint8),
        )

    def test_build_animation_creates_random_walk(self) -> None:
        with patch(
            'sys.argv',
            [
                'lyte_animate.py',
                'random_walk',
                '--color',
                '10',
                '20',
                '30',
                '--seed',
                '1',
            ],
        ):
            args = self.script.parse_args()

        animation = self.script.build_animation(args)
        device, state = initial_state(animation, 2)

        self.assertIsInstance(animation, RandomWalk)
        npt.assert_array_equal(
            render(animation, device, state),
            np.array([[0, 0, 0], [2, 5, 8]], dtype=np.uint8),
        )

    def test_build_animation_creates_color_chase(self) -> None:
        with patch(
            'sys.argv',
            [
                'lyte_animate.py',
                'color_chase',
                '--color',
                '1',
                '2',
                '3',
                '--width',
                '2',
            ],
        ):
            args = self.script.parse_args()

        animation = self.script.build_animation(args)
        device, state = initial_state(animation, 3)

        self.assertIsInstance(animation, ColorChase)
        npt.assert_array_equal(
            render(animation, device, state),
            np.array([[1, 2, 3], [1, 2, 3], [0, 0, 0]], dtype=np.uint8),
        )

    def test_build_animation_creates_ported_strip_animation(self) -> None:
        with patch('sys.argv', ['lyte_animate.py', 'rainbow']):
            args = self.script.parse_args()

        animation = self.script.build_animation(args)
        device, state = initial_state(animation, 3)

        self.assertIsInstance(animation, Rainbow)
        npt.assert_array_equal(
            render(animation, device, state),
            np.array([[255, 0, 0], [252, 3, 0], [249, 6, 0]], dtype=np.uint8),
        )

    def test_off_mode_skips_realtime_streaming(self) -> None:
        with (
            patch('sys.argv', ['lyte_animate.py', 'off', '--host', '192.168.1.23']),
            patch.object(self.script, 'read_gestalt', return_value={'mac': 'AA'}),
            patch.object(self.script, 'authenticate_device', return_value=object()),
            patch.object(
                self.script,
                'set_off_mode_with_retry',
                return_value=LyteResponse(http_status=200, data={'code': 1000}),
            ) as set_off_mode,
            patch.object(self.script, 'read_led_count') as read_led_count,
            patch.object(self.script, 'prepare_device') as prepare_device,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            result = self.script.main()

        self.assertEqual(result, 0)
        set_off_mode.assert_called_once()
        read_led_count.assert_not_called()
        prepare_device.assert_not_called()

    def test_read_led_count_prints_device_info(self) -> None:
        output = io.StringIO()

        with (
            patch.object(
                self.script,
                'read_device_led_count',
                return_value=(250, {'mac': 'AA', 'number_of_led': 250}),
            ),
            patch('sys.stdout', output),
        ):
            led_count = self.script.read_led_count(
                LyteClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                None,
                '192.168.1.23',
            )

        self.assertEqual(led_count, 250)
        self.assertEqual(output.getvalue(), '[connected] 192.168.1.23: 250 LEDs\n')

    def test_animation_turns_off_device_after_exception(self) -> None:
        class BrokenAnimation(Animation):
            def render(self, device: Device, state: State) -> NDArray[np.uint8]:
                raise RuntimeError('boom')

        with (
            patch(
                'sys.argv',
                [
                    'lyte_animate.py',
                    'color_fill',
                    '--host',
                    '192.168.1.23',
                ],
            ),
            patch.object(self.script, 'read_led_count', return_value=1),
            patch.object(self.script, 'prepare_device', return_value=True),
            patch.object(
                self.script,
                'build_animation',
                return_value=BrokenAnimation(),
            ),
            patch.object(
                self.script,
                'set_off_mode_with_retry',
                return_value=LyteResponse(http_status=200, data={'code': 1000}),
            ) as set_off_mode,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            with self.assertRaisesRegex(RuntimeError, 'boom'):
                self.script.main()

        set_off_mode.assert_called_once()


class PreviewScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        path = Path(__file__).parents[1] / 'scripts' / 'lyte_preview.py'
        spec = importlib.util.spec_from_file_location('lyte_preview', path)
        assert spec is not None
        assert spec.loader is not None
        cls.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.script)

    def test_parse_args_builds_preview_animation(self) -> None:
        with patch(
            'sys.argv',
            [
                'lyte_preview.py',
                'color_fill',
                'preview.html',
                '--color',
                '1',
                '2',
                '3',
            ],
        ):
            args = self.script.parse_args()

        animation = self.script.build_animation(args.animation_config)

        self.assertIsInstance(animation, ColorFill)
        self.assertEqual(args.output, Path('preview.html'))
        self.assertEqual(args.width, 16)
        self.assertEqual(args.height, 16)
        self.assertEqual(args.spacing, 1.0)
        self.assertEqual(args.led_size, 1.0)

    def test_main_without_arguments_prints_patterns(self) -> None:
        output = io.StringIO()

        with (
            patch('sys.argv', ['lyte_preview.py']),
            patch('sys.stdout', output),
            patch.object(self.script, 'render_animation_html') as render_animation_html,
        ):
            result = self.script.main()

        self.assertEqual(result, 0)
        self.assertIn('color_fill\n', output.getvalue())
        self.assertIn('rainbow\n', output.getvalue())
        self.assertNotIn('off\n', output.getvalue())
        self.assertNotIn('random\n', output.getvalue())
        render_animation_html.assert_not_called()

    def test_animation_config_keeps_layout_width_out_of_animation(self) -> None:
        with patch(
            'sys.argv',
            ['lyte_preview.py', 'color_chase', 'preview.html', '--width', '24'],
        ):
            args = self.script.parse_args()

        self.assertEqual(args.width, 24)
        self.assertEqual(args.animation_config.width, 1)

    def test_main_writes_preview_without_layout_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'preview.html'
            with patch(
                'sys.argv',
                [
                    'lyte_preview.py',
                    'color_fill',
                    str(output),
                    '--width',
                    '2',
                    '--height',
                    '1',
                    '--duration',
                    '1',
                    '--fps',
                    '1',
                    '--name',
                    'Preview',
                    '--led-size',
                    '2.5',
                    '--open',
                ],
            ):
                with patch.object(self.script.webbrowser, 'open') as open_browser:
                    result = self.script.main()

            data = preview_data(output.read_text())

        self.assertEqual(result, 0)
        self.assertEqual(data['name'], 'Preview')
        self.assertEqual(data['coords'], [[0.0, 0.0], [1.0, 0.0]])
        self.assertEqual(data['ledSize'], 2.5)
        open_browser.assert_called_once_with(output.resolve().as_uri())


class CheckHamiltonianScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        path = Path(__file__).parents[1] / 'scripts' / 'check_hamiltonian.py'
        spec = importlib.util.spec_from_file_location('check_hamiltonian', path)
        assert spec is not None
        assert spec.loader is not None
        cls.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.script)

    def test_find_problems_accepts_valid_sequence(self) -> None:
        colors = list(hamiltonian_colors(n=4))

        self.assertEqual(self.script.find_problems(colors, expected_step=64), [])

    def test_find_problems_reports_bad_transition(self) -> None:
        colors = [(0, 0, 0), (64, 64, 0)]

        problems = self.script.find_problems(colors, expected_step=64)

        self.assertEqual(len(problems), 2)
        self.assertIn('changed 2 components', problems[0])


if __name__ == '__main__':
    unittest.main()
