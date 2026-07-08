from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from lyte.crypto import CHALLENGE_KEY, derive_key, mac_bytes, rc4
from lyte.client import LyteClient
from lyte.discovery import DiscoveredDevice, parse_discovery_response
from lyte.errors import DiscoveryError, ProtocolError
from lyte.realtime import frame_packets_v3, solid_rgb_frame


class DiscoveryTests(unittest.TestCase):
    def test_parse_discovery_response(self) -> None:
        device = parse_discovery_response(b"\xab\x01\xa8\xc0OKTwinkly_A1234B\x00")

        self.assertEqual(device.ip_address, "192.168.1.171")
        self.assertEqual(device.device_id, "Twinkly_A1234B")

    def test_rejects_bad_discovery_response(self) -> None:
        with self.assertRaises(DiscoveryError):
            parse_discovery_response(b"\xab\x01\xa8\xc0NOTwinkly_A1234B\x00")


class CryptoTests(unittest.TestCase):
    def test_mac_bytes_accepts_common_formats(self) -> None:
        expected = b"\x5c\xcf\x7f\x33\xaa\xff"

        self.assertEqual(mac_bytes("5C:CF:7F:33:AA:FF"), expected)
        self.assertEqual(mac_bytes("5c-cf-7f-33-aa-ff"), expected)
        self.assertEqual(mac_bytes("5ccf7f33aaff"), expected)

    def test_derive_key_matches_original_driver(self) -> None:
        key = derive_key(CHALLENGE_KEY, "5C:CF:7F:33:AA:FF")

        self.assertEqual(key, b"9\xb9\x1a]\xc7\x90.\xaa\x0cV\xc9\x8d9\xbb^\x12")

    def test_rc4_known_vector(self) -> None:
        self.assertEqual(rc4(b"Plaintext", b"Key").hex(), "bbf316e8d940af0ad3")


class RealtimeTests(unittest.TestCase):
    def test_solid_rgb_frame(self) -> None:
        self.assertEqual(solid_rgb_frame(3, 230, 85, 0), b"\xe6U\x00" * 3)

    def test_generation_2_v3_packet(self) -> None:
        packets = list(frame_packets_v3("MCIGBF1qJlg=", b"\xe6U\x00" * 250))

        self.assertEqual(len(packets), 1)
        self.assertEqual(
            packets[0],
            b'\x030"\x06\x04]j&X\x00\x00\x00' + b"\xe6U\x00" * 250,
        )

    def test_generation_2_v3_fragments_large_frames(self) -> None:
        packets = list(frame_packets_v3("MCIGBF1qJlg=", b"a" * 901))

        self.assertEqual(len(packets), 2)
        self.assertEqual(len(packets[0]), 912)
        self.assertEqual(packets[0][:12], b'\x030"\x06\x04]j&X\x00\x00\x00')
        self.assertEqual(packets[1][:12], b'\x030"\x06\x04]j&X\x00\x00\x01')
        self.assertEqual(packets[1][12:], b"a")

    def test_rejects_bad_realtime_token(self) -> None:
        with self.assertRaises(ProtocolError):
            list(frame_packets_v3("bad", b"abc"))


class ClientTests(unittest.TestCase):
    def test_constructs_with_keyword_arguments(self) -> None:
        client = LyteClient(host="192.168.1.23", timeout=1.5)

        self.assertEqual(client.host, "192.168.1.23")
        self.assertEqual(client.timeout, 1.5)


class DiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        path = Path(__file__).parents[1] / "scripts" / "lyte_diagnostic.py"
        spec = importlib.util.spec_from_file_location("lyte_diagnostic", path)
        assert spec is not None
        assert spec.loader is not None
        cls.diagnostic = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.diagnostic)

    def test_retry_call_retries_retryable_result_failures(self) -> None:
        calls = 0

        def operation() -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise self.diagnostic.RetryableDiagnosticError("empty reply")
            return "ok"

        retry = self.diagnostic.RetryConfig(attempts=2, delay=0, backoff=1)

        with patch("sys.stdout", new_callable=io.StringIO), patch(
            "sys.stderr",
            new_callable=io.StringIO,
        ):
            result = self.diagnostic.retry_call(
                "operation",
                retry,
                operation,
                (self.diagnostic.RetryableDiagnosticError,),
            )

        self.assertEqual(result, "ok")
        self.assertEqual(calls, 2)

    def test_discover_one_retries_empty_discovery_results(self) -> None:
        calls = 0

        def discover(timeout: float):
            nonlocal calls
            calls += 1
            if calls == 1:
                return []
            return [DiscoveredDevice(ip_address="192.168.1.23", device_id="Twinkly")]

        retry = self.diagnostic.RetryConfig(attempts=2, delay=0, backoff=1)

        with patch.object(self.diagnostic, "discover", discover), patch(
            "sys.stdout",
            new_callable=io.StringIO,
        ), patch("sys.stderr", new_callable=io.StringIO):
            host = self.diagnostic.discover_one(0.01, retry)

        self.assertEqual(host, "192.168.1.23")
        self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
