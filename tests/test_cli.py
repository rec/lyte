from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest.mock import patch

from lyte import cli, patches


class CliTests(unittest.TestCase):
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

    def test_cli_patch_command_dispatches_patch_library(self) -> None:
        with patch.object(patches, 'run_patch_command', return_value=0) as run_command:
            result = cli.main(['patch', 'list'])

        self.assertEqual(result, 0)
        self.assertEqual(run_command.call_args.args[0].action, 'list')
