from __future__ import annotations

import unittest
from unittest.mock import patch

from lyte.animations.colors import solid_rgb_frame
from lyte.retry import RetryConfig
from lyte.twinkly import session
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
