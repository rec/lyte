from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lyte.twinkly import (
    diagnostic,
    inputs,
    layout,
    media,
    mode,
    networking,
    output,
    timer,
)
from lyte.twinkly.client import TwinklyClient, TwinklyResponse

COMMAND = 'lyte.twinkly.command'
OUTPUT = 'lyte.twinkly.output'


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
            patch('lyte.twinkly.output.LOGGER.info') as log_info,
        ):
            result = output.run_output_control(
                diagnostic.DiagnosticConfig(),
                'brightness',
                'get',
                None,
            )

        self.assertEqual(result, 0)
        turn_off.assert_called_once()
        self.assertIn(
            '[brightness] mode=enabled type=A value=75', log_info.call_args.args[0]
        )

    def test_run_output_control_set_writes_value(self) -> None:
        client = TwinklyClient(host='192.168.1.23')

        with (
            patch(f'{COMMAND}.discover_host', return_value='192.168.1.23'),
            patch(f'{COMMAND}.TwinklyClient', return_value=client),
            patch(f'{COMMAND}.prepare_authenticated_client'),
            patch(f'{OUTPUT}.write_output_control') as write_output_control,
            patch(
                f'{COMMAND}.session.turn_off_with_retry', return_value=True
            ) as turn_off,
            patch('lyte.twinkly.output.LOGGER.info') as log_info,
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
            log_info.call_args.args[0],
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
                patch('lyte.twinkly.layout.LOGGER.info') as log_info,
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
            self.assertIn('[layout] exported', log_info.call_args.args[0])

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
            patch('lyte.twinkly.timer.LOGGER.info') as log_info,
        ):
            result = timer.run_timer_control(
                diagnostic.DiagnosticConfig(), 'get', None, None, None
            )

        self.assertEqual(result, 0)
        self.assertIn(
            '[timer] time_now=1800 time_on=-1 time_off=7200',
            log_info.call_args.args[0],
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
            patch('lyte.twinkly.media.LOGGER.info') as log_info,
        ):
            result = media.run_movie_control(diagnostic.DiagnosticConfig(), 'current')

        self.assertEqual(result, 0)
        get_current_movie.assert_called_once()
        turn_off.assert_called_once()
        self.assertIn("[movie] current {'id': 0}", log_info.call_args.args[0])

    def test_run_playlist_control_reads_playlist_then_turns_off(self) -> None:
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
            patch('lyte.twinkly.media.LOGGER.info') as log_info,
        ):
            result = media.run_playlist_control(diagnostic.DiagnosticConfig(), 'list')

        self.assertEqual(result, 0)
        get_playlist.assert_called_once()
        turn_off.assert_called_once()
        self.assertIn("[playlist] list {'entries': []}", log_info.call_args.args[0])

    def test_run_network_control_reads_status_then_turns_off(self) -> None:
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
            patch('lyte.twinkly.networking.LOGGER.info') as log_info,
        ):
            result = networking.run_network_control(
                diagnostic.DiagnosticConfig(), 'status'
            )

        self.assertEqual(result, 0)
        get_network_status.assert_called_once()
        turn_off.assert_called_once()
        self.assertIn("[network] status {'mode': 1}", log_info.call_args.args[0])

    def test_run_mqtt_control_reads_config_then_turns_off(self) -> None:
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
            patch('lyte.twinkly.inputs.LOGGER.info') as log_info,
        ):
            result = inputs.run_mqtt_control(diagnostic.DiagnosticConfig(), 'config')

        self.assertEqual(result, 0)
        get_mqtt_config.assert_called_once()
        turn_off.assert_called_once()
        self.assertIn("[mqtt] config {'enabled': False}", log_info.call_args.args[0])

    def test_run_mic_control_reads_sample_then_turns_off(self) -> None:
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
            patch('lyte.twinkly.inputs.LOGGER.info') as log_info,
        ):
            result = inputs.run_mic_control(diagnostic.DiagnosticConfig(), 'sample')

        self.assertEqual(result, 0)
        get_mic_sample.assert_called_once()
        turn_off.assert_called_once()
        self.assertIn("[mic] sample {'sample': 3}", log_info.call_args.args[0])

    def test_run_music_control_reads_current_driver_set_then_turns_off(self) -> None:
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
            patch('lyte.twinkly.inputs.LOGGER.info') as log_info,
        ):
            result = inputs.run_music_control(
                diagnostic.DiagnosticConfig(), 'current-driver-set'
            )

        self.assertEqual(result, 0)
        get_current_music_driver_set.assert_called_once()
        turn_off.assert_called_once()
        self.assertIn(
            "[music] current-driver-set {'id': 1}", log_info.call_args.args[0]
        )
