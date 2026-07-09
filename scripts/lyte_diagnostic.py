#!/usr/bin/env python3
"""Exercise a Lyte device with detailed diagnostics."""

from __future__ import annotations

import argparse
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel

from lyte import (
    DiscoveredDevice,
    LyteClient,
    ProtocolError,
)
from lyte.discovery import (
    DEFAULT_BROADCAST,
    DISCOVERY_MESSAGE,
    DISCOVERY_PORT,
    parse_discovery_response,
)
from lyte.errors import DiscoveryError
from lyte.logging import log, log_error
from lyte.realtime import solid_rgb_frame
from lyte.retry import RetryConfig, retry_call
from lyte.session import (
    authenticate_with_retry,
    led_count_from_gestalt,
    read_gestalt,
    send_frame_with_retry,
    set_mac_from_gestalt,
    set_realtime_mode_with_retry,
)


class DiagnosticConfig(BaseModel, frozen=True):
    host: str | None
    timeout: float
    discovery_timeout: float
    led_count: int | None
    pause: float
    retry: RetryConfig
    discovery_retry: RetryConfig


DiagnosticConfig.model_rebuild(_types_namespace={"RetryConfig": RetryConfig})


def main() -> int:
    config = parse_args()
    log("Lyte diagnostic")
    log("==============================")
    log("This script uses only the Python standard library.")
    log("It will discover a device, authenticate, switch to realtime mode,")
    log("then send red, green, and blue UDP frames.")
    log()

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

    log()
    log("Diagnostic completed. The lights should have flashed red, green, and blue.")
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
        default=10,
        help="Attempts for transient network operations.",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=0.5,
        help="Initial delay between retries, in seconds.",
    )
    parser.add_argument(
        "--discovery-retry-delay",
        type=float,
        default=0.05,
        help="Initial delay between UDP discovery retries, in seconds.",
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
    if args.discovery_retry_delay < 0:
        parser.error("--discovery-retry-delay must not be negative")
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
            delay=args.discovery_retry_delay,
            backoff=args.retry_backoff,
            backoff_after=args.discovery_backoff_after,
        ),
    )


def discover_one(timeout: float, retry: RetryConfig) -> str | None:
    print_step("Discovering Twinkly devices with UDP broadcast on port 5555")

    delay = retry.delay
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", 0))
        for attempt in range(1, retry.attempts + 1):
            device = discovery_attempt(
                sock,
                timeout,
                attempt,
                retry.attempts,
                report_failure=attempt == retry.attempts,
            )
            if device is not None:
                print_success(f"Found {device.device_id} at {device.ip_address}")
                return device.ip_address

            if attempt == retry.attempts:
                break
            log(
                "[retry] Waiting "
                f"{delay * 1000:.1f} ms before retrying UDP discovery broadcast."
            )
            time.sleep(delay)
            if attempt >= retry.backoff_after:
                delay *= retry.backoff

    log("Check that the lights are powered on and joined to this network.")
    log("Check that this computer is on the same IPv4 network as the lights.")
    log("Some routers block broadcast traffic between WiFi clients.")
    log("Try passing --host with the device IP address.")
    return None


def discovery_attempt(
    sock: socket.socket,
    timeout: float,
    attempt: int,
    attempts: int,
    destination: str = DEFAULT_BROADCAST,
    report_failure: bool = True,
) -> DiscoveredDevice | None:
    log(f"[try] UDP discovery broadcast: attempt {attempt}/{attempts}")
    started_at = time.monotonic()
    deadline = started_at + timeout
    sock.sendto(DISCOVERY_MESSAGE, (destination, DISCOVERY_PORT))
    last_failure = ""

    while (remaining := deadline - time.monotonic()) > 0:
        sock.settimeout(remaining)
        try:
            data, _address = sock.recvfrom(256)
        except TimeoutError:
            break
        if data == DISCOVERY_MESSAGE:
            continue
        try:
            device = parse_discovery_response(data)
        except DiscoveryError as err:
            elapsed = (time.monotonic() - started_at) * 1000
            last_failure = (
                "UDP discovery broadcast received an invalid response on "
                f"attempt {attempt}/{attempts} after {elapsed:.1f} ms: {err}"
            )
            continue

        elapsed = (time.monotonic() - started_at) * 1000
        if attempt > 1:
            print_success(
                "UDP discovery broadcast recovered on attempt "
                f"{attempt} after {elapsed:.1f} ms."
            )
        else:
            print_success(f"UDP discovery broadcast completed in {elapsed:.1f} ms.")
        return device

    elapsed = (time.monotonic() - started_at) * 1000
    if report_failure:
        print_failure(
            last_failure
            or (
                "UDP discovery broadcast got no replies on "
                f"attempt {attempt}/{attempts} after {elapsed:.1f} ms."
            )
        )
    return None


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
        log("The host may not be a Twinkly device, or HTTP port 80 may be blocked.")
        return False
    status, firmware, gestalt = result

    print_success(f"Status: {status}")
    print_success(f"Firmware: {firmware}")
    print_success(f"Device name: {gestalt.get('device_name', '<missing>')}")
    print_success(f"MAC: {gestalt.get('mac', '<missing>')}")
    print_success(f"LED count: {gestalt.get('number_of_led', '<missing>')}")

    if not set_mac_from_gestalt(client, gestalt):
        log("Warning: gestalt did not include a MAC address.")
        log("Authentication can continue, but challenge-response cannot be verified.")
    return True


def authenticate(client: LyteClient, retry: RetryConfig) -> bool:
    print_step("Authenticating with login and verify")

    token = authenticate_with_retry(
        client,
        retry,
        "login and verify",
    )
    if token is None:
        log("Check that no other app is rapidly invalidating the token.")
        log("Power-cycling the controller can clear stale auth state.")
        log("The firmware may not match generation 2 REST behavior.")
        return False
    print_success(f"Authenticated. Token expires at {token.expires_at!r}.")
    return True


def detect_led_count(client: LyteClient, retry: RetryConfig) -> int | None:
    print_step("Detecting LED count from gestalt")

    gestalt = read_gestalt(client, retry, "HTTP gestalt read for LED count")
    if gestalt is None:
        log("Pass --led-count if you know the number of LEDs.")
        return None

    if (led_count := led_count_from_gestalt(gestalt)) is not None:
        print_success(f"Using {led_count} LEDs.")
        return led_count

    print_failure(f"Invalid number_of_led value: {gestalt.get('number_of_led')!r}")
    log("Pass --led-count with the exact LED count for your string.")
    return None


def set_realtime_mode(client: LyteClient, retry: RetryConfig) -> bool:
    print_step("Switching device to realtime mode")

    response = set_realtime_mode_with_retry(
        client,
        retry,
        "HTTP switch to realtime mode",
    )
    if response is None:
        log("Realtime mode requires a valid auth token.")
        return False
    print_success(f"Realtime mode response: {response.data}")
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
        bytes_sent = send_frame_with_retry(
            host,
            client.token.value,
            frame,
            retry,
            f"UDP realtime {name} frame send",
        )
        if bytes_sent is None:
            log("Check that UDP port 7777 is reachable from this computer.")
            log("Confirm this is generation 2 firmware new enough for v3 frames.")
            return False
        print_success(f"Sent {name} frame, {bytes_sent} bytes.")
        time.sleep(pause)
    return True


def print_step(message: str) -> None:
    log()
    log(f"[step] {message}")


def print_success(message: str) -> None:
    log(f"[ok] {message}")


def print_failure(message: str) -> None:
    log_error(f"[failed] {message}")


if __name__ == "__main__":
    raise SystemExit(main())
