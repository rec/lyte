from __future__ import annotations

import unittest

from lyte.errors import DiscoveryError
from lyte.twinkly.discovery import parse_discovery_response


class DiscoveryTests(unittest.TestCase):
    def test_parse_discovery_response(self) -> None:
        device = parse_discovery_response(b'\xab\x01\xa8\xc0OKTwinkly_A1234B\x00')

        self.assertEqual(device.ip_address, '192.168.1.171')
        self.assertEqual(device.device_id, 'Twinkly_A1234B')

    def test_rejects_bad_discovery_response(self) -> None:
        with self.assertRaises(DiscoveryError):
            parse_discovery_response(b'\xab\x01\xa8\xc0NOTwinkly_A1234B\x00')
