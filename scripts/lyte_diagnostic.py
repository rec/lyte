#!/usr/bin/env python3
"""Exercise a Lyte device with detailed diagnostics."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Callable, TypeVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel

from lyte import (
    AuthenticationError,
    DiscoveredDevice,
    ProtocolError,
    LyteClient,
    discover,
)
from lyte.errors import DiscoveryError
from lyte.realtime import send_frame_v3, solid_rgb_frame


T = TypeVar("T")


class RetryableDiagnosticError(Exception):
    """A diagnostic operation returned a retryable non-exception result."""


class RetryConfig(BaseModel, frozen=True):
    attempts: int
    delay: float
    backoff: float
    backoff_after: int


class DiagnosticConfig(BaseModel, frozen=True):
    host: str | None
    timeout: float
    discovery_timeout: float
    led_count: int | None
    pause: float
    retry: RetryConfig
    discovery_retry: RetryConfig


def main() -> int:
    config = parse_args()
    print("Lyte diagnostic")
    print("==============================")
    print("This script uses only the Python standard library.")
    print("It will discover a device, authenticate, switch to realtime mode,")
    print("then send red, green, and blue UDP frames.")
    print()

    host = config.host or discover_one(
        config.discovery_timeout,
        config.discovery_retry,
    )
    if host is None:
        return 1

    client = LyteClient(host=host, timeout=config.timeout)
    print_step(f"Using device host {host}")

    if not get_unauthenticated_info(client, config.retry):
        return 1
    if not authenticate(client, config.retry):
        return 1
    led_count = config.led_count or detect_led_count(client, config.retry)
    if led_count is None:
        return 1
    if not set_realtime_mode(client, config.retry):
        return 1
    if not send_visible_test(client, host, led_count, config.pause, config.retry):
        return 1

    print()
    print("Diagnostic completed. The lights should have flashed red, green, and blue.")
    return 0


def parse_args() -> DiagnosticConfig:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--host",
        help="Device IP address. If omitted, use UDP discovery.",
    )
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument(
        "--discovery-timeout",
        type=float,
        default=0.1,
        help="Seconds to wait for each UDP discovery broadcast attempt.",
    )
    parser.add_argument(
        "--discovery-attempts",
        type=int,
        default=20,
        help="Attempts for UDP discovery.",
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=5,
        help="Attempts for transient network operations.",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=0.05,
        help="Initial delay between retries, in seconds.",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=2.0,
        help="Retry delay multiplier after each failed attempt.",
    )
    parser.add_argument(
        "--discovery-backoff-after",
        type=int,
        default=10,
        help="Discovery attempt number after which retry delay backs off.",
    )
    parser.add_argument(
        "--led-count",
        type=int,
        help="Number of LEDs. If omitted, read number_of_led from gestalt.",
    )
    parser.add_argument("--pause", type=float, default=0.7)
    args = parser.parse_args()
    if args.attempts < 1:
        parser.error("--attempts must be at least 1")
    if args.discovery_attempts < 1:
        parser.error("--discovery-attempts must be at least 1")
    if args.discovery_timeout <= 0:
        parser.error("--discovery-timeout must be greater than zero")
    if args.retry_delay < 0:
        parser.error("--retry-delay must not be negative")
    if args.retry_backoff < 1:
        parser.error("--retry-backoff must be at least 1")
    if args.discovery_backoff_after < 1:
        parser.error("--discovery-backoff-after must be at least 1")
    return DiagnosticConfig(
        host=args.host,
        timeout=args.timeout,
        discovery_timeout=args.discovery_timeout,
        led_count=args.led_count,
        pause=args.pause,
        retry=RetryConfig(
            attempts=args.attempts,
            delay=args.retry_delay,
            backoff=args.retry_backoff,
            backoff_after=1,
        ),
        discovery_retry=RetryConfig(
            attempts=args.discovery_attempts,
            delay=args.retry_delay,
            backoff=args.retry_backoff,
            backoff_after=args.discovery_backoff_after,
        ),
    )


def discover_one(timeout: float, retry: RetryConfig) -> str | None:
    print_step("Discovering Twinkly devices with UDP broadcast on port 5555")

    def discover_once() -> list[DiscoveredDevice]:
        devices = list(discover(timeout=timeout))
        if not devices:
            raise RetryableDiagnosticError("No Twinkly discovery replies received")
        return devices

    devices = retry_call(
        "UDP discovery broadcast",
        retry,
        discover_once,
        (DiscoveryError, OSError, RetryableDiagnosticError),
    )
    if devices is None:
        print("Check that this computer is on the same IPv4 network as the lights.")
        print("Some routers block broadcast traffic between WiFi clients.")
        print("Try passing --host with the device IP address.")
        return None

    if not devices:
        print_failure("No Twinkly discovery replies received.")
        print("Check that the lights are powered on and joined to this network.")
        print("If discovery is blocked by the router, pass --host with the device IP.")
        return None
    if len(devices) > 1:
        print("Multiple devices responded:")
        for device in devices:
            print(f"  {device.ip_address}  {device.device_id}")
        print(f"Using the first device: {devices[0].ip_address}")
    else:
        print_success(f"Found {devices[0].device_id} at {devices[0].ip_address}")
    return devices[0].ip_address


def get_unauthenticated_info(client: LyteClient, retry: RetryConfig) -> bool:
    print_step("Reading unauthenticated status, firmware, and device details")

    result = retry_call(
        "HTTP status, firmware, and gestalt reads",
        retry,
        lambda: (
            client.get("status", authenticated=False).data,
            client.get("fw/version", authenticated=False).data,
            client.get("gestalt", authenticated=False).data,
        ),
        (ProtocolError,),
    )
    if result is None:
        print("The host may not be a Twinkly device, or HTTP port 80 may be blocked.")
        return False
    status, firmware, gestalt = result

    print_success(f"Status: {status}")
    print_success(f"Firmware: {firmware}")
    print_success(f"Device name: {gestalt.get('device_name', '<missing>')}")
    print_success(f"MAC: {gestalt.get('mac', '<missing>')}")
    print_success(f"LED count: {gestalt.get('number_of_led', '<missing>')}")

    mac = gestalt.get("mac")
    if isinstance(mac, str):
        client.mac = mac
    else:
        print("Warning: gestalt did not include a MAC address.")
        print("Authentication can continue, but challenge-response cannot be verified.")
    return True


def authenticate(client: LyteClient, retry: RetryConfig) -> bool:
    print_step("Authenticating with login and verify")

    def authenticate_once() -> object:
        client.token = None
        return client.authenticate()

    token = retry_call(
        "login and verify",
        retry,
        authenticate_once,
        (AuthenticationError, ProtocolError),
    )
    if token is None:
        print("Check that no other app is rapidly invalidating the token.")
        print("Power-cycling the controller can clear stale auth state.")
        print("The firmware may not match generation 2 REST behavior.")
        return False
    print_success(f"Authenticated. Token expires at {token.expires_at!r}.")
    return True


def detect_led_count(client: LyteClient, retry: RetryConfig) -> int | None:
    print_step("Detecting LED count from gestalt")

    gestalt = retry_call(
        "HTTP gestalt read for LED count",
        retry,
        lambda: client.get("gestalt", authenticated=False).data,
        (ProtocolError,),
    )
    if gestalt is None:
        print("Pass --led-count if you know the number of LEDs.")
        return None

    led_count = gestalt.get("number_of_led")
    if isinstance(led_count, int) and led_count > 0:
        print_success(f"Using {led_count} LEDs.")
        return led_count

    print_failure(f"Invalid number_of_led value: {led_count!r}")
    print("Pass --led-count with the exact LED count for your string.")
    return None


def set_realtime_mode(client: LyteClient, retry: RetryConfig) -> bool:
    print_step("Switching device to realtime mode")

    response = retry_call(
        "HTTP switch to realtime mode",
        retry,
        lambda: client.set_realtime_mode().data,
        (AuthenticationError, ProtocolError),
    )
    if response is None:
        print("Realtime mode requires a valid auth token.")
        return False
    print_success(f"Realtime mode response: {response}")
    return True


def send_visible_test(
    client: LyteClient,
    host: str,
    led_count: int,
    pause: float,
    retry: RetryConfig,
) -> bool:
    if client.token is None:
        print_failure("Cannot send realtime frames without an auth token.")
        return False

    print_step("Sending red, green, and blue UDP frames to port 7777")
    colors = (("red", (255, 0, 0)), ("green", (0, 255, 0)), ("blue", (0, 0, 255)))
    for name, color in colors:
        frame = solid_rgb_frame(led_count, *color)
        bytes_sent = retry_call(
            f"UDP realtime {name} frame send",
            retry,
            lambda frame=frame: send_frame_v3(host, client.token.value, frame),
            (OSError, ProtocolError, ValueError),
        )
        if bytes_sent is None:
            print("Check that UDP port 7777 is reachable from this computer.")
            print("Confirm this is generation 2 firmware new enough for v3 frames.")
            return False
        print_success(f"Sent {name} frame, {bytes_sent} bytes.")
        time.sleep(pause)
    return True


def retry_call(
    label: str,
    retry: RetryConfig,
    operation: Callable[[], T],
    retry_errors: tuple[type[BaseException], ...],
) -> T | None:
    delay = retry.delay
    for attempt in range(1, retry.attempts + 1):
        print(f"[try] {label}: attempt {attempt}/{retry.attempts}")
        started_at = time.monotonic()
        try:
            result = operation()
        except retry_errors as err:
            elapsed = (time.monotonic() - started_at) * 1000
            print_failure(
                f"{label} failed on attempt {attempt}/{retry.attempts} "
                f"after {elapsed:.1f} ms: {type(err).__name__}: {err}"
            )
            if attempt == retry.attempts:
                print_failure(f"{label} exhausted all retry attempts.")
                return None
            print(f"[retry] Waiting {delay * 1000:.1f} ms before retrying {label}.")
            time.sleep(delay)
            if attempt >= retry.backoff_after:
                delay *= retry.backoff
            continue

        elapsed = (time.monotonic() - started_at) * 1000
        if attempt > 1:
            print_success(
                f"{label} recovered on attempt {attempt} after {elapsed:.1f} ms."
            )
        else:
            print_success(f"{label} completed in {elapsed:.1f} ms.")
        return result
    return None


def print_step(message: str) -> None:
    print()
    print(f"[step] {message}")


def print_success(message: str) -> None:
    print(f"[ok] {message}")


def print_failure(message: str) -> None:
    print(f"[failed] {message}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
