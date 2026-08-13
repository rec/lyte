from __future__ import annotations

import io
import unittest
from unittest.mock import patch

import numpy as np
from numpy import testing as npt
from numpy.typing import NDArray

from lyte import animation, fps_test
from lyte.retry import RetryConfig
from lyte.twinkly import realtime
from lyte.twinkly.client import TwinklyClient
from lyte.twinkly.discovery import DiscoveredDevice


class FpsTestTests(unittest.TestCase):
    def test_fps_values_include_120_hz(self) -> None:
        self.assertEqual(fps_test.FPS_VALUES, (30.0, 60.0, 120.0, 240, 480, 960, 1920))

    def test_gradient_frame_blends_between_endpoint_colors(self) -> None:
        npt.assert_array_equal(
            fps_test.gradient_frame(3, (0, 0, 0), (100, 50, 200)),
            np.array([[0, 0, 0], [50, 25, 100], [100, 50, 200]], dtype=np.uint8),
        )

    def test_blend_frames_crossfades_two_frames(self) -> None:
        first_frame = np.array([[0, 100, 200]], dtype=np.uint8)
        second_frame = np.array([[100, 200, 0]], dtype=np.uint8)

        npt.assert_array_equal(
            fps_test.blend_frames(first_frame, second_frame, 0.25),
            np.array([[25, 125, 150]], dtype=np.uint8),
        )

    def test_discover_host_retries_until_a_device_replies(self) -> None:
        device = DiscoveredDevice(ip_address='192.168.1.23', device_id='twinkly')

        with (
            patch(
                'lyte.twinkly.realtime.discover',
                side_effect=(iter(()), iter([device])),
            ),
            patch('sys.stdout', new_callable=io.StringIO),
            patch('sys.stderr', new_callable=io.StringIO),
        ):
            host = fps_test.realtime.discover_host(None)

        self.assertEqual(host, '192.168.1.23')

    def test_discover_host_stops_at_timeout(self) -> None:
        with (
            patch('lyte.twinkly.realtime.discover', return_value=iter(())),
            patch('lyte.twinkly.realtime.time.monotonic', side_effect=(0.0, 0.0, 1.0)),
            patch('sys.stdout', new_callable=io.StringIO),
            patch('sys.stderr', new_callable=io.StringIO),
        ):
            host = fps_test.realtime.discover_host(1.0)

        self.assertIsNone(host)

    def test_verify_lists_demos_before_running_them(self) -> None:
        with (
            patch('lyte.fps_test.realtime.discover_host', return_value='192.168.1.23'),
            patch('lyte.fps_test.realtime.read_led_count', return_value=2),
            patch('lyte.fps_test.realtime.prepare_device', return_value=True),
            patch('lyte.fps_test.run_fast_verify', return_value=()),
            patch('lyte.fps_test.realtime.turn_off_device', return_value=True),
            patch('lyte.fps_test.LOGGER.info') as log_info,
        ):
            result = fps_test.run_verify_test(fps_test.VerifyConfig())

        self.assertEqual(result, 0)
        self.assertIn(
            '[verify] Demos: primary-channels, moving-gradient, crossfade, '
            'temporal-dither',
            log_info.call_args.args[0],
        )

    def test_realtime_command_turns_off_device_after_setup_interrupt(self) -> None:
        def interrupt_setup(
            client: TwinklyClient,
            retry: RetryConfig,
            host: str,
        ) -> bool:
            raise KeyboardInterrupt

        with (
            patch('lyte.fps_test.realtime.read_led_count', return_value=2),
            patch('lyte.fps_test.realtime.prepare_device', interrupt_setup),
            patch(
                'lyte.fps_test.realtime.turn_off_device', return_value=True
            ) as turn_off,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            result = fps_test.run_realtime_command(
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
        order = fps_test.dispersed_pixel_order(11)

        self.assertEqual(sorted(order.tolist()), list(range(11)))
        self.assertEqual(order.tolist(), [0, 5, 10, 4, 9, 3, 8, 2, 7, 1, 6])

    def test_temporal_dither_grayscale_frame_spreads_fractional_step(
        self,
    ) -> None:
        device = animation.Device(led_count=4)
        order = np.array([0, 2, 1, 3], dtype=np.int64)

        frame = fps_test.temporal_dither_grayscale_frame(device, 0, 1, 2, 5, order)

        npt.assert_array_equal(
            frame,
            np.array([[1, 1, 1], [0, 0, 0], [1, 1, 1], [0, 0, 0]], dtype=np.uint8),
        )

    def test_solid_grayscale_frame_fills_all_channels(self) -> None:
        npt.assert_array_equal(
            fps_test.solid_grayscale_frame(animation.Device(led_count=2), 7),
            np.array([[7, 7, 7], [7, 7, 7]], dtype=np.uint8),
        )

    def test_solid_rgb_level_frame_fills_all_channels(self) -> None:
        npt.assert_array_equal(
            fps_test.solid_rgb_level_frame(animation.Device(led_count=2), (1, 2, 3)),
            np.array([[1, 2, 3], [1, 2, 3]], dtype=np.uint8),
        )

    def test_adjust_black_floor_level_changes_one_channel(self) -> None:
        self.assertEqual(fps_test.adjust_black_floor_level((0, 0, 0), 'r'), (1, 0, 0))
        self.assertEqual(fps_test.adjust_black_floor_level((0, 0, 0), 'g'), (0, 1, 0))
        self.assertEqual(fps_test.adjust_black_floor_level((0, 0, 0), 'b'), (0, 0, 1))
        self.assertEqual(fps_test.adjust_black_floor_level((1, 1, 1), 'R'), (0, 1, 1))
        self.assertEqual(fps_test.adjust_black_floor_level((1, 1, 1), 'G'), (1, 0, 1))
        self.assertEqual(fps_test.adjust_black_floor_level((1, 1, 1), 'B'), (1, 1, 0))
        self.assertEqual(fps_test.adjust_black_floor_level((0, 0, 0), 'R'), (0, 0, 0))
        self.assertEqual(
            fps_test.adjust_black_floor_level((255, 255, 255), 'r'), (255, 255, 255)
        )
        self.assertEqual(
            fps_test.adjust_black_floor_level((1, 2, 3), fps_test.UP_KEY), (2, 3, 4)
        )
        self.assertEqual(
            fps_test.adjust_black_floor_level((1, 2, 3), fps_test.DOWN_KEY), (0, 1, 2)
        )
        self.assertEqual(
            fps_test.adjust_black_floor_level((255, 255, 255), fps_test.UP_KEY),
            (255, 255, 255),
        )

    def test_black_floor_keys_show_initial_black_and_each_valid_key(self) -> None:
        sent_frames = []
        keys = iter(['r', 'g', 'b', 'R', 'x', 'B', fps_test.UP_KEY, fps_test.DOWN_KEY])

        def record_frame(
            client: TwinklyClient,
            retry: RetryConfig,
            host: str,
            frame: NDArray[np.uint8],
        ) -> realtime.FrameSendResult:
            sent_frames.append(frame.copy())
            return realtime.FrameSendResult(
                status=realtime.FrameSendStatus.SENT,
                byte_count=frame.nbytes,
            )

        def read_key() -> str:
            try:
                return next(keys)
            except StopIteration:
                raise KeyboardInterrupt from None

        with (
            patch('lyte.fps_test.realtime.send_realtime_frame', record_frame),
            self.assertRaises(KeyboardInterrupt),
        ):
            fps_test.run_black_floor_keys(
                TwinklyClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                '192.168.1.23',
                animation.Device(led_count=1),
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
            key = fps_test.read_single_key(7)

        self.assertEqual(key, 'r')
        read.assert_called_once_with(7, 1)

    def test_read_single_key_reads_arrow_escape_sequence(self) -> None:
        with patch('lyte.fps_test.os.read', side_effect=[b'\x1b', b'[A']) as read:
            key = fps_test.read_single_key(7)

        self.assertEqual(key, fps_test.UP_KEY)
        self.assertEqual(read.call_args_list[0].args, (7, 1))
        self.assertEqual(read.call_args_list[1].args, (7, 2))

    def test_temporal_dither_comparison_runs_direct_then_dithered(self) -> None:
        device = animation.Device(led_count=2)
        phases = []

        def record_fade(
            client: TwinklyClient,
            retry: RetryConfig,
            host: str,
            device: animation.Device,
            fps: float,
            duration: float,
            phase: str,
            frame_at: object,
        ) -> fps_test.FadeReport:
            phases.append((phase, fps, duration))
            return fps_test.FadeReport(
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
            fps_test.run_temporal_dither_comparison(
                TwinklyClient(host='192.168.1.23'),
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
        device = animation.Device(led_count=2)

        frames = [
            fps_test.verify_primary_channels_frame(device, i, 4) for i in range(4)
        ]

        npt.assert_array_equal(frames[0], np.full((2, 3), (255, 0, 0), dtype=np.uint8))
        npt.assert_array_equal(frames[1], np.full((2, 3), (0, 255, 0), dtype=np.uint8))
        npt.assert_array_equal(frames[2], np.full((2, 3), (0, 0, 255), dtype=np.uint8))
        npt.assert_array_equal(
            frames[3], np.full((2, 3), (255, 255, 255), dtype=np.uint8)
        )

    def test_verify_answer_accepts_only_yes_and_no(self) -> None:
        self.assertIs(fps_test.verify_answer('y'), True)
        self.assertIs(fps_test.verify_answer('n'), False)
        self.assertIsNone(fps_test.verify_answer('x'))
        self.assertIsNone(fps_test.verify_answer(None))

    def test_fast_verify_shows_black_demo_black_for_each_demo(self) -> None:
        device = animation.Device(led_count=2)
        phases = []

        def record_frames(
            client: TwinklyClient,
            retry: RetryConfig,
            host: str,
            device: animation.Device,
            fps: float,
            duration: float,
            phase: str,
            frame_at: object,
        ) -> fps_test.FadeReport:
            phases.append((phase, fps, duration))
            return fps_test.FadeReport(
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
            patch(
                'lyte.fps_test.VERIFY_DEMOS',
                (fps_test.VERIFY_DEMOS[0], fps_test.VERIFY_DEMOS[1]),
            ),
            patch('lyte.fps_test.stream_frames', record_frames),
            patch('lyte.fps_test.report_fades'),
        ):
            results = fps_test.run_fast_verify(
                TwinklyClient(host='192.168.1.23'),
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
                fps_test.VerifyResult('primary-channels', None),
                fps_test.VerifyResult('moving-gradient', None),
            ),
        )

    def test_report_verify_results_lists_status_groups(self) -> None:
        with (
            patch('lyte.fps_test.LOGGER.info') as log_info,
            patch('lyte.fps_test.LOGGER.error') as log_error,
        ):
            fps_test.report_verify_results(
                (
                    fps_test.VerifyResult('good', True),
                    fps_test.VerifyResult('bad', False),
                    fps_test.VerifyResult('shown', None),
                )
            )

        log_info.assert_has_calls(
            [
                unittest.mock.call('[verify] Worked: good'),
                unittest.mock.call('[verify] Shown without pass/fail: shown'),
            ]
        )
        log_error.assert_called_once_with('[verify] Did not work: bad')

    def test_run_fades_separates_each_test_with_black(self) -> None:
        device = animation.Device(led_count=2)
        fades = []

        def record_fade(
            client: TwinklyClient,
            retry: RetryConfig,
            host: str,
            device: animation.Device,
            first_frame: NDArray[np.uint8],
            second_frame: NDArray[np.uint8],
            fps: float,
            duration: float,
            phase: str,
        ) -> fps_test.FadeReport:
            fades.append((first_frame.copy(), second_frame.copy(), fps, duration))
            return fps_test.FadeReport(
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
            fps_test.run_fades(
                TwinklyClient(host='192.168.1.23'),
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
        device = animation.Device(led_count=1)

        with (
            patch(
                'lyte.fps_test.realtime.send_realtime_frame',
                return_value=realtime.FrameSendResult(
                    status=realtime.FrameSendStatus.SENT, byte_count=3
                ),
            ),
            patch('lyte.fps_test.time.sleep'),
        ):
            report = fps_test.stream_fade(
                TwinklyClient(host='192.168.1.23'),
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
        with (
            patch('lyte.fps_test.LOGGER.info') as log_info,
            patch('lyte.fps_test.LOGGER.error') as log_error,
        ):
            fps_test.report_fades(
                (
                    fps_test.FadeReport(
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

        self.assertIn('4/10 unique frames', log_info.call_args.args[0])
        self.assertIn('2/10 times', log_error.call_args_list[0].args[0])
        self.assertIn('1 short UDP sends', log_error.call_args_list[1].args[0])
