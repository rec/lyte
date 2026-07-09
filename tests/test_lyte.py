from __future__ import annotations

import importlib.util
import io
import unittest
from pathlib import Path
from unittest.mock import patch

from lyte.client import LyteClient
from lyte.crypto import CHALLENGE_KEY, derive_key, mac_bytes, rc4
from lyte.discovery import DiscoveredDevice, parse_discovery_response
from lyte.errors import DiscoveryError, ProtocolError
from lyte.hamiltonian import (
    HamiltonianCounter,
    HamiltonianStreamer,
    hamiltonian_colors,
    next_hamiltonian,
    parse_order,
)
from lyte.logging import LOGGING, log, log_error
from lyte.realtime import frame_packets_v3, solid_rgb_frame
from lyte.retry import RetryConfig, retry_call
from lyte.session import led_count_from_gestalt, set_mac_from_gestalt


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


class SessionTests(unittest.TestCase):
    def test_set_mac_from_gestalt_updates_client(self) -> None:
        client = LyteClient(host="192.168.1.23")

        result = set_mac_from_gestalt(client, {"mac": "AA:BB:CC:DD:EE:FF"})

        self.assertTrue(result)
        self.assertEqual(client.mac, "AA:BB:CC:DD:EE:FF")

    def test_led_count_from_gestalt_returns_positive_ints(self) -> None:
        self.assertEqual(led_count_from_gestalt({"number_of_led": 250}), 250)
        self.assertIsNone(led_count_from_gestalt({"number_of_led": 0}))
        self.assertIsNone(led_count_from_gestalt({"number_of_led": "250"}))


class LoggingTests(unittest.TestCase):
    def test_logging_is_disabled_by_default(self) -> None:
        self.assertFalse(LOGGING)

    def test_error_logging_is_always_displayed(self) -> None:
        output = io.StringIO()

        with patch("sys.stderr", output):
            log_error("failure")

        self.assertEqual(output.getvalue(), "failure\n")

    def test_regular_logging_is_hidden_by_default(self) -> None:
        output = io.StringIO()

        with patch("sys.stdout", output):
            log("hidden")

        self.assertEqual(output.getvalue(), "")


class HamiltonianTests(unittest.TestCase):
    def test_next_hamiltonian_matches_loop_special_case(self) -> None:
        self.assertEqual(next_hamiltonian(4, 1, 0, 0), (0, 0, 0))
        self.assertEqual(next_hamiltonian(4, 1, 0, 1), (2, 0, 1))

    def test_counter_produces_scaled_rgb_values(self) -> None:
        counter = HamiltonianCounter(n=4)

        self.assertEqual(counter.next_color(), (0, 0, 0))
        self.assertEqual(counter.next_color(), (0, 0, 64))
        self.assertEqual(counter.next_color(), (0, 0, 128))

    def test_hamiltonian_colors_generates_one_full_cycle(self) -> None:
        colors = list(hamiltonian_colors(n=4))

        self.assertEqual(len(colors), 64)
        self.assertEqual(colors[:3], [(0, 0, 0), (0, 0, 64), (0, 0, 128)])

    def test_counter_supports_order_and_inversion(self) -> None:
        counter = HamiltonianCounter(n=4, order="bgr", inverted="r")

        self.assertEqual(counter.next_color(), (192, 0, 0))
        self.assertEqual(counter.next_color(), (128, 0, 0))

    def test_parse_order_rejects_invalid_orders(self) -> None:
        with self.assertRaises(ValueError):
            parse_order("rrg")

    def test_streamer_returns_one_rgb_triplet_per_led(self) -> None:
        streamer = HamiltonianStreamer(led_count=3, n=4, speed=4, fps=4)

        self.assertEqual(streamer.next_frame(), b"\x00" * 9)
        self.assertEqual(streamer.next_frame(), b"\x00" * 9)
        self.assertEqual(streamer.next_frame(), b"\x00" * 6 + b"\x00\x00@")


class RetryTests(unittest.TestCase):
    def test_retry_call_retries_retryable_result_failures(self) -> None:
        calls = 0

        def operation() -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RetryableTestError("empty reply")
            return "ok"

        retry = RetryConfig(
            attempts=2,
            delay=0,
            backoff=1,
            backoff_after=1,
        )

        with (
            patch("sys.stdout", new_callable=io.StringIO),
            patch(
                "sys.stderr",
                new_callable=io.StringIO,
            ),
        ):
            result = retry_call(
                "operation",
                retry,
                operation,
                (RetryableTestError,),
            )

        self.assertEqual(result, "ok")
        self.assertEqual(calls, 2)

    def test_retry_call_delays_backoff_until_configured_attempt(self) -> None:
        calls = 0
        sleeps = []

        def operation() -> str:
            nonlocal calls
            calls += 1
            if calls < 4:
                raise RetryableTestError("empty reply")
            return "ok"

        retry = RetryConfig(
            attempts=4,
            delay=0.01,
            backoff=2,
            backoff_after=10,
        )

        with (
            patch("sys.stdout", new_callable=io.StringIO),
            patch(
                "sys.stderr",
                new_callable=io.StringIO,
            ),
            patch("lyte.retry.time.sleep", sleeps.append),
        ):
            result = retry_call(
                "operation",
                retry,
                operation,
                (RetryableTestError,),
            )

        self.assertEqual(result, "ok")
        self.assertEqual(sleeps, [0.01, 0.01, 0.01])


class RetryableTestError(Exception):
    pass


class DiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        path = Path(__file__).parents[1] / "scripts" / "lyte_diagnostic.py"
        spec = importlib.util.spec_from_file_location("lyte_diagnostic", path)
        assert spec is not None
        assert spec.loader is not None
        cls.diagnostic = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.diagnostic)

    def test_discover_one_retries_empty_discovery_attempts(self) -> None:
        calls = 0
        timeouts = []

        def discovery_attempt(sock, timeout: float, attempt: int, attempts: int):
            nonlocal calls
            calls += 1
            timeouts.append(timeout)
            if calls == 1:
                return None
            return DiscoveredDevice(ip_address="192.168.1.23", device_id="Twinkly")

        retry = RetryConfig(
            attempts=2,
            delay=0,
            backoff=1,
            backoff_after=1,
        )

        with (
            patch.object(
                self.diagnostic,
                "discovery_attempt",
                discovery_attempt,
            ),
            patch("sys.stdout", new_callable=io.StringIO),
            patch(
                "sys.stderr",
                new_callable=io.StringIO,
            ),
        ):
            host = self.diagnostic.discover_one(0.01, retry)

        self.assertEqual(host, "192.168.1.23")
        self.assertEqual(calls, 2)
        self.assertEqual(timeouts, [0.01, 0.01])

    def test_parse_args_uses_slower_network_retry_defaults(self) -> None:
        with patch("sys.argv", ["lyte_diagnostic.py"]):
            config = self.diagnostic.parse_args()

        self.assertEqual(config.retry.attempts, 10)
        self.assertEqual(config.retry.delay, 0.5)
        self.assertEqual(config.discovery_retry.delay, 0.05)


class HamiltonianScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        path = Path(__file__).parents[1] / "scripts" / "lyte_hamiltonian.py"
        spec = importlib.util.spec_from_file_location("lyte_hamiltonian", path)
        assert spec is not None
        assert spec.loader is not None
        cls.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.script)

    def test_retry_call_recovers_after_transient_protocol_error(self) -> None:
        calls = 0

        def operation() -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ProtocolError("timed out")
            return "ok"

        with (
            patch("sys.stdout", new_callable=io.StringIO),
            patch(
                "sys.stderr",
                new_callable=io.StringIO,
            ),
            patch("lyte.retry.time.sleep"),
        ):
            result = retry_call(
                "device info",
                RetryConfig(attempts=2, delay=0.01, backoff=2),
                operation,
                (ProtocolError,),
            )

        self.assertEqual(result, "ok")
        self.assertEqual(calls, 2)

    def test_parse_args_uses_slower_network_retry_defaults(self) -> None:
        with patch("sys.argv", ["lyte_hamiltonian.py"]):
            args = self.script.parse_args()

        self.assertEqual(args.attempts, 10)
        self.assertEqual(args.retry_delay, 0.5)


class CheckHamiltonianScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        path = Path(__file__).parents[1] / "scripts" / "check_hamiltonian.py"
        spec = importlib.util.spec_from_file_location("check_hamiltonian", path)
        assert spec is not None
        assert spec.loader is not None
        cls.script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.script)

    def test_find_problems_accepts_valid_sequence(self) -> None:
        colors = list(hamiltonian_colors(n=4))

        self.assertEqual(self.script.find_problems(colors, expected_step=64), [])

    def test_find_problems_reports_bad_transition(self) -> None:
        colors = [(0, 0, 0), (64, 64, 0)]

        problems = self.script.find_problems(colors, expected_step=64)

        self.assertEqual(len(problems), 2)
        self.assertIn("changed 2 components", problems[0])


if __name__ == "__main__":
    unittest.main()
