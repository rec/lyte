from __future__ import annotations

import unittest

from lyte.twinkly.authentication import CHALLENGE_KEY, derive_key, mac_bytes, rc4


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
