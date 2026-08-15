from __future__ import annotations

import importlib
import io
import random
import unittest
from unittest.mock import patch

import numpy as np
from numpy import testing as npt
from numpy.typing import NDArray

from lyte import animation
from lyte.animate import config, random_show
from lyte.animations import bibliopixel
from lyte.animations.christmas import hamiltonian
from lyte.animations.christmas.random_walk import RandomWalk
from lyte.retry import RetryConfig
from lyte.twinkly import track
from lyte.twinkly.client import TwinklyClient, TwinklyResponse


def render(
    source: animation.Animation,
    device: animation.Device,
    state: animation.State,
) -> NDArray[np.uint8]:
    return animation.byte_light_frame_from_float(source.render(device, state))


def initial_state(
    source: animation.Animation, led_count: int
) -> tuple[animation.Device, animation.State]:
    device = animation.Device(led_count=led_count)
    return device, source.initial_state(device)


def make_track(led_count: int = 1) -> track.TwinklyTrack:
    return track.TwinklyTrack(
        client=TwinklyClient(host='192.168.1.23'),
        retry=RetryConfig(attempts=1, delay=0, backoff=1),
        host='192.168.1.23',
        configured_host=None,
        discovery_timeout=None,
        device=animation.Device(led_count=led_count),
    )


class AnimateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = importlib.import_module('lyte.animate.playback')

    def test_build_animation_creates_hamiltonian(self) -> None:
        with patch('sys.argv', ['lyte', 'hamiltonian']):
            args = self.script.parse_args()

        animation = self.script.build_animation(args)

        self.assertIsInstance(animation, hamiltonian.Hamiltonian)

    def test_parse_args_defaults_to_random_animation(self) -> None:
        with patch('sys.argv', ['lyte']):
            args = self.script.parse_args()

        self.assertEqual(args.animation, 'random')

    def test_random_mode_uses_hamiltonian_settings(self) -> None:
        with patch('sys.argv', ['lyte']):
            args = self.script.parse_args()

        with patch(
            'lyte.animate.random_show.config.RANDOM_ANIMATIONS', ('hamiltonian',)
        ):
            segment_args = random_show.random_animation_args(
                args, random.Random(1), None
            )

        self.assertEqual(segment_args.animation, 'hamiltonian')
        self.assertEqual(segment_args.n, 256)
        self.assertEqual(segment_args.speed, 100)

    def test_random_mode_uses_exciting_random_walk_settings(self) -> None:
        with patch('sys.argv', ['lyte']):
            args = self.script.parse_args()

        with patch(
            'lyte.animate.random_show.config.RANDOM_ANIMATIONS', ('random_walk',)
        ):
            segment_args = random_show.random_animation_args(
                args, random.Random(1), None
            )

        self.assertEqual(segment_args.animation, 'random_walk')
        self.assertEqual(segment_args.speed, config.RANDOM_WALK_SPEED)
        self.assertEqual(segment_args.variance, config.RANDOM_WALK_VARIANCE)
        self.assertEqual(segment_args.bounds, config.RANDOM_WALK_BOUNDS)
        self.assertEqual(segment_args.period, config.RANDOM_WALK_PERIOD)
        self.assertTrue(segment_args.pre_fill)

    def test_random_mode_prints_selected_pattern(self) -> None:
        with patch('sys.argv', ['lyte', '--duration', '1']):
            args = self.script.parse_args()

        with (
            patch(
                'lyte.animate.random_show.config.RANDOM_ANIMATIONS', ('hamiltonian',)
            ),
            patch(
                'lyte.animate.playback.build_animation',
                return_value=bibliopixel.ColorFill(),
            ),
            patch('lyte.animate.playback.run_animation_state') as run_animation_state,
            patch('lyte.animate.playback.time.monotonic', side_effect=[0, 0, 0, 2]),
            patch('lyte.animate.random_show.LOGGER.info') as log_info,
        ):
            self.script.run_random_animations(args, make_track(3))

        self.assertIn('[pattern] hamiltonian', log_info.call_args.args[0])
        run_animation_state.assert_called_once()

    def test_random_overlap_is_half_the_pattern_duration(self) -> None:
        self.assertEqual(random_show.random_overlap_duration(10), 5)
        self.assertEqual(random_show.random_overlap_duration(30), 15)

    def test_blend_frames_crossfades_rgb_values(self) -> None:
        current_frame = np.array([[0.0, 100 / 255, 200 / 255]], dtype=np.float32)
        next_frame = np.array([[100 / 255, 200 / 255, 0.0]], dtype=np.float32)

        npt.assert_allclose(
            animation.byte_light_frame_from_float(
                self.script.blend_frames(current_frame, next_frame, 0.25)
            ),
            np.array([[25, 125, 150]], dtype=np.uint8),
        )

    def test_track_reports_verified_device_and_contact(self) -> None:
        devices: list[tuple[str, str | None]] = []
        contacts: list[None] = []
        twinkly_track = make_track()
        twinkly_track.client.mac = 'aa:bb:cc:dd:ee:ff'

        def report_device(host: str, mac: str | None) -> None:
            devices.append((host, mac))

        twinkly_track.on_device_connected = report_device
        twinkly_track.on_health_check = lambda: contacts.append(None)

        with patch('lyte.twinkly.track.realtime.prepare_device', return_value=True):
            assert twinkly_track.prepare()

        assert devices == [('192.168.1.23', 'aa:bb:cc:dd:ee:ff')]
        assert contacts == [None]

    def test_track_blackout_uses_three_second_deadline(self) -> None:
        twinkly_track = make_track()

        with (
            patch('lyte.twinkly.track.time.monotonic', return_value=10.0),
            patch(
                'lyte.twinkly.track.realtime.turn_off_streaming_device',
                return_value=True,
            ) as turn_off,
        ):
            twinkly_track.close()

        assert turn_off.call_args.args[3] == 13.0

    def test_frame_deadline_report_counts_late_frames_and_recovery(self) -> None:
        report = track.FrameDeadlineReport()

        report.record_frame(0.15, 0.1)
        report.record_frame(0.31, 0.1)
        report.record_recovery(3.5)

        self.assertEqual(report.frame_count, 2)
        self.assertEqual(report.late_frames, 2)
        self.assertEqual(report.missed_deadlines, 4)
        self.assertEqual(report.worst_overrun_ms, 210)
        self.assertEqual(report.recovery_count, 1)
        self.assertEqual(report.recovery_duration_ms, 3500)

    def test_track_recovers_after_a_failed_health_probe(self) -> None:
        states: list[track.realtime.PlaybackConnectionState] = []
        twinkly_track = make_track()
        twinkly_track.last_health_check = 0
        twinkly_track.on_connection_state = states.append

        with (
            patch(
                'lyte.twinkly.track.realtime.probe_streaming_device',
                return_value=False,
            ),
            patch(
                'lyte.twinkly.track.realtime.recover_streaming_device',
                return_value='192.168.1.23',
            ) as recover,
            patch(
                'lyte.twinkly.track.time.monotonic', side_effect=[0.0, 2.0, 2.0, 11.0]
            ),
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            twinkly_track.stream_frames(
                'test', 60, 10, lambda: np.zeros((1, 3), dtype=np.uint8)
            )

        recover.assert_called_once()
        assert states == [
            track.realtime.PlaybackConnectionState.RECOVERING,
            track.realtime.PlaybackConnectionState.STREAMING,
        ]

    def test_animation_recovers_after_streaming_token_loss(self) -> None:
        class ConstantAnimation(animation.Animation):
            def render(
                self, device: animation.Device, state: animation.State
            ) -> NDArray[np.float32]:
                return np.zeros((device.led_count, 3), dtype=np.float32)

        args = config.AnimateConfig(animation='color_fill', fps=1, duration=0.5)
        connection = self.script.realtime.PlaybackConnection()
        failed = self.script.realtime.FrameSendResult(
            status=self.script.realtime.FrameSendStatus.TOKEN_MISSING
        )
        sent = self.script.realtime.FrameSendResult(
            status=self.script.realtime.FrameSendStatus.SENT, byte_count=3
        )

        twinkly_track = make_track()
        twinkly_track.connection = connection
        with (
            patch(
                'lyte.twinkly.track.realtime.send_realtime_frame',
                side_effect=[failed, sent],
            ),
            patch(
                'lyte.twinkly.track.realtime.recover_streaming_device',
                return_value='192.168.1.23',
            ) as recover,
            patch(
                'lyte.twinkly.track.time.monotonic',
                side_effect=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
            ),
            patch('lyte.twinkly.track.time.sleep'),
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            self.script.run_animation_state(
                ConstantAnimation(),
                animation.State(),
                args,
                twinkly_track,
                args.duration,
            )

        recover.assert_called_once()
        self.assertEqual(
            connection.state, self.script.realtime.PlaybackConnectionState.STREAMING
        )

    def test_crossfade_advances_both_streamers(self) -> None:
        class ConstantAnimation(animation.Animation):
            color: tuple[int, int, int]
            calls: int = 0

            def render(
                self, device: animation.Device, state: animation.State
            ) -> NDArray[np.float32]:
                state.frame += 1
                object.__setattr__(self, 'calls', self.calls + 1)
                return np.array([self.color], dtype=np.float32) / 255

        current_animation = ConstantAnimation(color=(0, 0, 0))
        next_animation = ConstantAnimation(color=(100, 200, 250))
        device = animation.Device(led_count=1)
        current_state = animation.State()
        next_state = animation.State()
        args = config.AnimateConfig(fps=1, animation='color_fill')
        sent_frames = []

        with (
            patch(
                'lyte.twinkly.track.time.monotonic',
                side_effect=[0.0, 0.0, 0.0, 0.0, 0.5, 0.5, 2.0],
            ),
            patch('lyte.twinkly.track.time.sleep'),
            patch(
                'lyte.twinkly.track.realtime.send_realtime_frame',
                lambda *a: (
                    sent_frames.append(a[-1])
                    or self.script.realtime.FrameSendResult(
                        status=self.script.realtime.FrameSendStatus.SENT,
                        byte_count=a[-1].nbytes,
                    )
                ),
            ),
        ):
            self.script.run_crossfade(
                current_animation,
                current_state,
                next_animation,
                next_state,
                args,
                make_track(device.led_count),
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
                'lyte',
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
                'lyte',
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

        self.assertIsInstance(animation, bibliopixel.ColorChase)
        npt.assert_array_equal(
            render(animation, device, state),
            np.array([[1, 2, 3], [1, 2, 3], [0, 0, 0]], dtype=np.uint8),
        )

    def test_build_animation_creates_ported_strip_animation(self) -> None:
        with patch('sys.argv', ['lyte', 'rainbow']):
            args = self.script.parse_args()

        animation = self.script.build_animation(args)
        device, state = initial_state(animation, 3)

        self.assertIsInstance(animation, bibliopixel.Rainbow)
        npt.assert_array_equal(
            render(animation, device, state),
            np.array([[255, 0, 0], [252, 3, 0], [249, 6, 0]], dtype=np.uint8),
        )

    def test_off_mode_skips_realtime_streaming(self) -> None:
        with (
            patch('sys.argv', ['lyte', 'off', '--host', '192.168.1.23']),
            patch(
                'lyte.twinkly.realtime.session.read_gestalt', return_value={'mac': 'AA'}
            ),
            patch(
                'lyte.twinkly.realtime.session.authenticate_device',
                return_value=object(),
            ),
            patch(
                'lyte.twinkly.realtime.session.set_off_mode_with_retry',
                return_value=TwinklyResponse(http_status=200, data={'code': 1000}),
            ) as set_off_mode,
            patch('lyte.animate.playback.realtime.read_led_count') as read_led_count,
            patch('lyte.animate.playback.realtime.prepare_device') as prepare_device,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            result = self.script.main()

        self.assertEqual(result, 0)
        set_off_mode.assert_called_once()
        read_led_count.assert_not_called()
        prepare_device.assert_not_called()

    def test_read_led_count_prints_device_info(self) -> None:
        with (
            patch(
                'lyte.twinkly.realtime.session.read_device_led_count',
                return_value=(250, {'mac': 'AA', 'number_of_led': 250}),
            ),
            patch('lyte.twinkly.realtime.LOGGER.info') as log_info,
        ):
            led_count = self.script.realtime.read_led_count(
                TwinklyClient(host='192.168.1.23'),
                RetryConfig(attempts=1, delay=0, backoff=1),
                None,
                '192.168.1.23',
            )

        self.assertEqual(led_count, 250)
        log_info.assert_called_once_with('[connected] 192.168.1.23: 250 LEDs')

    def test_animation_attempts_blackout_after_realtime_setup_fails(self) -> None:
        args = config.AnimateConfig(animation='color_fill', host='192.168.1.23')

        with (
            patch('lyte.animate.playback.realtime.read_led_count', return_value=1),
            patch('lyte.animate.playback.realtime.prepare_device', return_value=False),
            patch(
                'lyte.animate.playback.realtime.turn_off_streaming_device',
                return_value=True,
            ) as turn_off,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            result = self.script.run_animate(args)

        self.assertEqual(result, 1)
        turn_off.assert_called_once()

    def test_failed_animation_cleanup_is_reported_as_unknown(self) -> None:
        args = config.AnimateConfig(animation='color_fill', host='192.168.1.23')
        with (
            patch('lyte.animate.playback.realtime.read_led_count', return_value=1),
            patch('lyte.animate.playback.realtime.prepare_device', return_value=False),
            patch(
                'lyte.animate.playback.realtime.turn_off_streaming_device',
                return_value=False,
            ),
            patch('lyte.twinkly.realtime.LOGGER.info') as log_info,
        ):
            result = self.script.run_animate(args)

        self.assertEqual(result, 1)
        log_info.assert_any_call('[connection] unknown')

    def test_animation_turns_off_device_after_exception(self) -> None:
        class BrokenAnimation(animation.Animation):
            def render(
                self, device: animation.Device, state: animation.State
            ) -> NDArray[np.float32]:
                raise RuntimeError('boom')

        with (
            patch(
                'sys.argv',
                [
                    'lyte',
                    'color_fill',
                    '--host',
                    '192.168.1.23',
                ],
            ),
            patch('lyte.animate.playback.realtime.read_led_count', return_value=1),
            patch('lyte.animate.playback.realtime.prepare_device', return_value=True),
            patch(
                'lyte.animate.playback.build_animation',
                return_value=BrokenAnimation(),
            ),
            patch(
                'lyte.twinkly.realtime.session.set_off_mode_with_retry',
                return_value=TwinklyResponse(http_status=200, data={'code': 1000}),
            ) as set_off_mode,
            patch('sys.stdout', new_callable=io.StringIO),
        ):
            with self.assertRaisesRegex(RuntimeError, 'boom'):
                self.script.main()

        set_off_mode.assert_called_once()
