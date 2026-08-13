from __future__ import annotations

import importlib
import io
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from lyte.errors import UnsupportedEndpointError
from lyte.retry import RetryConfig
from lyte.twinkly import diagnostic
from lyte.twinkly.client import TwinklyClient, TwinklyResponse
from lyte.twinkly.discovery import DiscoveredDevice

DIAGNOSTIC = 'lyte.twinkly.diagnostic'


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
            patch(f'{DIAGNOSTIC}.LOGGER.info') as log_info,
        ):
            result = diagnostic.run_diagnostic(diagnostic.DiagnosticConfig())

        self.assertEqual(result, 0)
        self.assertEqual(client.mac, 'AA')
        turn_off.assert_called_once()
        self.assertIn(
            'Device name: Tree',
            '\n'.join(call.args[0] for call in log_info.call_args_list),
        )
        self.assertIn(
            "firmware: {'version': '1.0'}",
            '\n'.join(call.args[0] for call in log_info.call_args_list),
        )

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
