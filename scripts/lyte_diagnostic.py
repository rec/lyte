#!/usr/bin/env python3
"""Exercise a Lyte device with detailed diagnostics."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel

from lyte import AuthenticationError, ProtocolError, LyteClient, discover
from lyte.errors import DiscoveryError
from lyte.realtime import send_frame_v3, solid_rgb_frame


class DiagnosticConfig(BaseModel, frozen=True):
    host: str | None
    timeout: float
    led_count: int | None
    pause: float


def main() -> int:
    config = parse_args()
    print("Lyte diagnostic")
    print("==============================")
    print("This script uses only the Python standard library.")
    print("It will discover a device, authenticate, switch to realtime mode,")
    print("then send red, green, and blue UDP frames.")
    print()

    host = config.host or discover_one(config.timeout)
    if host is None:
        return 1

    client = LyteClient(host=host, timeout=config.timeout)
    print_step(f"Using device host {host}")

    if not get_unauthenticated_info(client):
        return 1
    if not authenticate(client):
        return 1
    led_count = config.led_count or detect_led_count(client)
    if led_count is None:
        return 1
    if not set_realtime_mode(client):
        return 1
    if not send_visible_test(client, host, led_count, config.pause):
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
        "--led-count",
        type=int,
        help="Number of LEDs. If omitted, read number_of_led from gestalt.",
    )
    parser.add_argument("--pause", type=float, default=0.7)
    args = parser.parse_args()
    return DiagnosticConfig(
        host=args.host,
        timeout=args.timeout,
        led_count=args.led_count,
        pause=args.pause,
    )


def discover_one(timeout: float) -> str | None:
    print_step("Discovering Twinkly devices with UDP broadcast on port 5555")
    try:
        devices = list(discover(timeout=timeout))
    except (DiscoveryError, OSError) as err:
        print_failure(f"Discovery failed: {err}")
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


def get_unauthenticated_info(client: LyteClient) -> bool:
    print_step("Reading unauthenticated status, firmware, and device details")
    try:
        status = client.get("status", authenticated=False).data
        firmware = client.get("fw/version", authenticated=False).data
        gestalt = client.get("gestalt", authenticated=False).data
    except ProtocolError as err:
        print_failure(f"Could not read unauthenticated endpoints: {err}")
        print("The host may not be a Twinkly device, or HTTP port 80 may be blocked.")
        return False

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


def authenticate(client: LyteClient) -> bool:
    print_step("Authenticating with login and verify")
    try:
        token = client.authenticate()
    except AuthenticationError as err:
        print_failure(f"Authentication failed: {err}")
        print("Check that no other app is rapidly invalidating the token.")
        print("Power-cycling the controller can clear stale auth state.")
        return False
    except ProtocolError as err:
        print_failure(f"Authentication HTTP/protocol failure: {err}")
        print("The firmware may not match generation 2 REST behavior.")
        return False
    print_success(f"Authenticated. Token expires at {token.expires_at!r}.")
    return True


def detect_led_count(client: LyteClient) -> int | None:
    print_step("Detecting LED count from gestalt")
    try:
        gestalt = client.get("gestalt", authenticated=False).data
    except ProtocolError as err:
        print_failure(f"Could not read gestalt: {err}")
        print("Pass --led-count if you know the number of LEDs.")
        return None

    led_count = gestalt.get("number_of_led")
    if isinstance(led_count, int) and led_count > 0:
        print_success(f"Using {led_count} LEDs.")
        return led_count

    print_failure(f"Invalid number_of_led value: {led_count!r}")
    print("Pass --led-count with the exact LED count for your string.")
    return None


def set_realtime_mode(client: LyteClient) -> bool:
    print_step("Switching device to realtime mode")
    try:
        response = client.set_realtime_mode().data
    except (AuthenticationError, ProtocolError) as err:
        print_failure(f"Could not switch to realtime mode: {err}")
        print("Realtime mode requires a valid auth token.")
        return False
    print_success(f"Realtime mode response: {response}")
    return True


def send_visible_test(
    client: LyteClient,
    host: str,
    led_count: int,
    pause: float,
) -> bool:
    if client.token is None:
        print_failure("Cannot send realtime frames without an auth token.")
        return False

    print_step("Sending red, green, and blue UDP frames to port 7777")
    colors = (("red", (255, 0, 0)), ("green", (0, 255, 0)), ("blue", (0, 0, 255)))
    try:
        for name, color in colors:
            frame = solid_rgb_frame(led_count, *color)
            bytes_sent = send_frame_v3(host, client.token.value, frame)
            print_success(f"Sent {name} frame, {bytes_sent} bytes.")
            time.sleep(pause)
    except (OSError, ProtocolError, ValueError) as err:
        print_failure(f"Realtime UDP send failed: {err}")
        print("Check that UDP port 7777 is reachable from this computer.")
        print("Also confirm this is generation 2 firmware new enough for v3 frames.")
        return False
    return True


def print_step(message: str) -> None:
    print()
    print(f"[step] {message}")


def print_success(message: str) -> None:
    print(f"[ok] {message}")


def print_failure(message: str) -> None:
    print(f"[failed] {message}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
