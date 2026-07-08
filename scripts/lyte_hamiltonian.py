#!/usr/bin/env python3
"""Run the Hamiltonian color streamer on Lyte-supported lights."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Callable, TypeVar

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lyte import AuthenticationError, LyteClient, ProtocolError, discover
from lyte.hamiltonian import HamiltonianStreamer
from lyte.realtime import send_frame_v3


T = TypeVar("T")


def main() -> int:
    args = parse_args()
    host = args.host or discover_host(args.discovery_timeout)
    if host is None:
        return 1

    led_count = args.led_count
    client = LyteClient(host=host, timeout=args.timeout)
    print(f"[step] Reading device info from {host}")
    gestalt = retry_call(
        f"HTTP device info read from {host}",
        args.attempts,
        args.retry_delay,
        args.retry_backoff,
        lambda: client.get("gestalt", authenticated=False).data,
        (ProtocolError,),
    )
    if gestalt is None:
        sys.exit(f"Could not read device info from {host}.")

    if led_count is None:
        value = gestalt.get("number_of_led")
        if not isinstance(value, int) or value <= 0:
            sys.exit("Device did not report number_of_led; pass --led-count.")
        led_count = value
    mac = gestalt.get("mac")
    if isinstance(mac, str):
        client.mac = mac

    print("[step] Authenticating")
    token = retry_call(
        f"login and verify with {host}",
        args.attempts,
        args.retry_delay,
        args.retry_backoff,
        client.authenticate,
        (AuthenticationError, ProtocolError),
    )
    if token is None:
        sys.exit(f"Could not authenticate with {host}.")
    if client.token is None:
        sys.exit("Authentication succeeded without producing a token.")

    print("[step] Switching to realtime mode")
    realtime_response = retry_call(
        f"switch {host} to realtime mode",
        args.attempts,
        args.retry_delay,
        args.retry_backoff,
        client.set_realtime_mode,
        (AuthenticationError, ProtocolError),
    )
    if realtime_response is None:
        sys.exit(f"Could not switch {host} to realtime mode.")

    streamer = HamiltonianStreamer(
        led_count=led_count,
        speed=args.speed,
        fps=args.fps,
        n=args.n,
        order=args.order,
        inverted=args.inverted,
        pre_fill=args.pre_fill,
    )
    frame_delay = 1 / args.fps
    stop_at = None if args.duration is None else time.monotonic() + args.duration

    print(
        "[ok] Streaming Hamiltonian frames to "
        f"{host} for {led_count} LEDs at {args.speed} pixels/second"
    )
    try:
        while stop_at is None or time.monotonic() < stop_at:
            started_at = time.monotonic()
            frame = streamer.next_frame()
            sent = retry_call(
                f"UDP realtime frame send to {host}",
                args.attempts,
                args.retry_delay,
                args.retry_backoff,
                lambda frame=frame: send_frame_v3(host, client.token.value, frame),
                (OSError, ProtocolError),
            )
            if sent is None:
                sys.exit(f"Could not send realtime frame to {host}.")
            remaining = frame_delay - (time.monotonic() - started_at)
            if remaining > 0:
                time.sleep(remaining)
    except KeyboardInterrupt:
        print()
        print("[ok] Stopped")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--discovery-timeout", type=float, default=5.0)
    parser.add_argument(
        "--attempts",
        type=int,
        default=5,
        help="Attempts for transient HTTP and UDP operations.",
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
    parser.add_argument("--led-count", type=int)
    parser.add_argument(
        "--speed",
        type=float,
        default=25,
        help="Hamiltonian color movement speed in LEDs per second.",
    )
    parser.add_argument("--fps", type=float, default=20)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--n", type=int, default=32)
    parser.add_argument("--order", default="rgb")
    parser.add_argument("--inverted", default="")
    parser.add_argument("--pre-fill", action="store_true")
    args = parser.parse_args()
    if args.attempts < 1:
        parser.error("--attempts must be at least 1")
    if args.retry_delay < 0:
        parser.error("--retry-delay must not be negative")
    if args.retry_backoff < 1:
        parser.error("--retry-backoff must be at least 1")
    return args


def discover_host(timeout: float) -> str | None:
    print("[step] Discovering Twinkly devices")
    devices = list(discover(timeout=timeout))
    if not devices:
        print("[failed] No Twinkly discovery replies received.", file=sys.stderr)
        print("Pass --host with the device IP address.", file=sys.stderr)
        return None
    if len(devices) > 1:
        print("[warn] Multiple devices found; using the first one.")
    device = devices[0]
    print(f"[ok] Found {device.device_id} at {device.ip_address}")
    return device.ip_address


def retry_call(
    label: str,
    attempts: int,
    delay: float,
    backoff: float,
    operation: Callable[[], T],
    retry_errors: tuple[type[BaseException], ...],
) -> T | None:
    current_delay = delay
    for attempt in range(1, attempts + 1):
        print(f"[try] {label}: attempt {attempt}/{attempts}")
        started_at = time.monotonic()
        try:
            result = operation()
        except retry_errors as err:
            elapsed = (time.monotonic() - started_at) * 1000
            print(
                f"[failed] {label} failed on attempt {attempt}/{attempts} "
                f"after {elapsed:.1f} ms: {type(err).__name__}: {err}",
                file=sys.stderr,
            )
            if attempt == attempts:
                print(
                    f"[failed] {label} exhausted all retry attempts.",
                    file=sys.stderr,
                )
                return None
            print(f"[retry] Waiting {current_delay * 1000:.1f} ms before retrying.")
            time.sleep(current_delay)
            current_delay *= backoff
            continue

        elapsed = (time.monotonic() - started_at) * 1000
        if attempt > 1:
            print(
                f"[ok] {label} recovered on attempt {attempt} "
                f"after {elapsed:.1f} ms."
            )
        else:
            print(f"[ok] {label} completed in {elapsed:.1f} ms.")
        return result
    return None


if __name__ == "__main__":
    raise SystemExit(main())
