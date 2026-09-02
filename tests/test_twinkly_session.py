from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

import numpy as np

from lyte.animations.colors import solid_rgb_frame
from lyte.retry import RetryConfig
from lyte.twinkly import client, realtime, session
from lyte.twinkly.client import TWINKLY_API_PREFIX, TwinklyClient, TwinklyResponse


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


class PlaybackConnectionTests(unittest.TestCase):
    def test_recovery_requests_blackout_until_streaming_resumes(self) -> None:
        connection = realtime.PlaybackConnection()

        connection.begin_recovery()

        self.assertTrue(connection.blackout_requested)
        self.assertEqual(connection.state, realtime.PlaybackConnectionState.RECOVERING)
        connection.resume_streaming()
        self.assertFalse(connection.blackout_requested)
        self.assertEqual(connection.state, realtime.PlaybackConnectionState.STREAMING)

    def test_failed_blackout_is_reported_as_unknown(self) -> None:
        connection = realtime.PlaybackConnection()

        connection.finish_blackout(False)

        self.assertTrue(connection.blackout_requested)
        self.assertEqual(connection.state, realtime.PlaybackConnectionState.UNKNOWN)

    def test_connection_state_is_reported(self) -> None:
        connection = realtime.PlaybackConnection()

        with patch('lyte.twinkly.realtime.LOGGER.info') as log_info:
            connection.set_state(realtime.PlaybackConnectionState.CONNECTING)
            connection.set_state(realtime.PlaybackConnectionState.STREAMING)
            connection.set_state(realtime.PlaybackConnectionState.RECOVERING)
            connection.set_state(realtime.PlaybackConnectionState.BLACKED_OUT)
            connection.set_state(realtime.PlaybackConnectionState.UNKNOWN)

        self.assertEqual(connection.state, realtime.PlaybackConnectionState.UNKNOWN)
        self.assertEqual(
            [call.args[0] for call in log_info.call_args_list],
            [
                '[connection] connecting',
                '[connection] streaming',
                '[connection] recovering',
                '[connection] blacked_out',
                '[connection] unknown',
            ],
        )


class RealtimeTransportTests(unittest.TestCase):
    def test_recovery_rediscovers_and_restores_realtime_mode(self) -> None:
        client = TwinklyClient(host='192.168.1.2', mac='old')

        with (
            patch('lyte.twinkly.realtime.discover_host', return_value='192.168.1.23'),
            patch('lyte.twinkly.realtime.read_led_count', return_value=3),
            patch('lyte.twinkly.realtime.prepare_device', return_value=True),
        ):
            host = realtime.recover_streaming_device(
                client,
                RetryConfig(attempts=1, delay=0, backoff=1),
                None,
                None,
                3,
            )

        self.assertEqual(host, '192.168.1.23')
        self.assertEqual(client.host, '192.168.1.23')
        self.assertIsNone(client.mac)

    def test_recovery_requires_the_original_device_mac(self) -> None:
        client = TwinklyClient(host='192.168.1.2')
        macs = iter(['other', 'expected'])

        def read_led_count(*args: object) -> int:
            client.mac = next(macs)
            return 3

        with (
            patch(
                'lyte.twinkly.realtime.discover_host',
                side_effect=['192.168.1.3', '192.168.1.4'],
            ),
            patch('lyte.twinkly.realtime.read_led_count', read_led_count),
            patch('lyte.twinkly.realtime.prepare_device', return_value=True) as prepare,
            patch('lyte.twinkly.realtime.time.sleep'),
            patch('lyte.twinkly.realtime.LOGGER.error') as log_error,
        ):
            host = realtime.recover_streaming_device(
                client,
                RetryConfig(attempts=1, delay=0, backoff=1),
                None,
                None,
                3,
                'expected',
            )

        assert host == '192.168.1.4'
        prepare.assert_called_once()
        log_error.assert_called_once_with(
            '[failed] 192.168.1.3 MAC changed: expected expected, found other.'
        )

    def test_recovery_reports_changed_led_count(self) -> None:
        client = TwinklyClient(host='192.168.1.2')

        with (
            patch(
                'lyte.twinkly.realtime.discover_host',
                side_effect=['192.168.1.3', '192.168.1.4'],
            ),
            patch('lyte.twinkly.realtime.read_led_count', side_effect=[100, 250]),
            patch('lyte.twinkly.realtime.prepare_device', return_value=True),
            patch('lyte.twinkly.realtime.time.sleep'),
            patch('lyte.twinkly.realtime.LOGGER.error') as log_error,
        ):
            host = realtime.recover_streaming_device(
                client,
                RetryConfig(attempts=1, delay=0, backoff=1),
                None,
                None,
                250,
            )

        assert host == '192.168.1.4'
        log_error.assert_called_once_with(
            '[failed] 192.168.1.3 LED count changed: expected 250, found 100.'
        )

    def test_recovery_stops_when_requested(self) -> None:
        stop_event = threading.Event()
        stop_event.set()

        host = realtime.recover_streaming_device(
            TwinklyClient(host='192.168.1.2'),
            RetryConfig(attempts=1, delay=0, backoff=1),
            None,
            None,
            3,
            stop_event=stop_event,
        )

        assert host is None

    def test_realtime_frame_reports_missing_token(self) -> None:
        result = realtime.send_realtime_frame(
            TwinklyClient(host='192.168.1.23'),
            RetryConfig(attempts=1, delay=0, backoff=1),
            '192.168.1.23',
            np.zeros((1, 3), dtype=np.uint8),
        )

        self.assertEqual(result.status, realtime.FrameSendStatus.TOKEN_MISSING)
        self.assertEqual(result.byte_count, 0)

    def test_realtime_frame_reports_transport_failure(self) -> None:
        twinkly_client = TwinklyClient(host='192.168.1.23')
        twinkly_client.token = client.AuthToken(
            value='AAAAAAAAAAA=', challenge_response='', expires_at=None
        )
        with patch(
            'lyte.twinkly.realtime.send_frame_v3',
            side_effect=OSError('Network is unreachable'),
        ):
            result = realtime.send_realtime_frame(
                twinkly_client,
                RetryConfig(attempts=1, delay=0, backoff=1),
                '192.168.1.23',
                np.zeros((1, 3), dtype=np.uint8),
            )

        self.assertEqual(result.status, realtime.FrameSendStatus.TRANSPORT_FAILED)
        self.assertEqual(result.byte_count, 0)
        self.assertEqual(result.error, 'OSError: Network is unreachable')


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
