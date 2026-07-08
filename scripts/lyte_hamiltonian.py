#!/usr/bin/env python3
"""Run the Hamiltonian color streamer on Lyte-supported lights."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lyte import AuthenticationError, LyteClient, ProtocolError, discover
from lyte.hamiltonian import HamiltonianStreamer
from lyte.realtime import send_frame_v3


def main() -> int:
    args = parse_args()
    host = args.host or discover_host(args.discovery_timeout)
    if host is None:
        return 1

    led_count = args.led_count
    client = LyteClient(host=host, timeout=args.timeout)
    print(f"[step] Reading device info from {host}")
    try:
        gestalt = client.get("gestalt", authenticated=False).data
    except ProtocolError as err:
        sys.exit(f"Could not read device info from {host}: {err}")

    if led_count is None:
        value = gestalt.get("number_of_led")
        if not isinstance(value, int) or value <= 0:
            sys.exit("Device did not report number_of_led; pass --led-count.")
        led_count = value
    mac = gestalt.get("mac")
    if isinstance(mac, str):
        client.mac = mac

    print("[step] Authenticating")
    try:
        client.authenticate()
    except (AuthenticationError, ProtocolError) as err:
        sys.exit(f"Could not authenticate with {host}: {err}")
    if client.token is None:
        sys.exit("Authentication succeeded without producing a token.")

    print("[step] Switching to realtime mode")
    try:
        client.set_realtime_mode()
    except (AuthenticationError, ProtocolError) as err:
        sys.exit(f"Could not switch {host} to realtime mode: {err}")

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

    print(f"[ok] Streaming Hamiltonian frames to {host} for {led_count} LEDs")
    try:
        while stop_at is None or time.monotonic() < stop_at:
            started_at = time.monotonic()
            send_frame_v3(host, client.token.value, streamer.next_frame())
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
    parser.add_argument("--led-count", type=int)
    parser.add_argument("--speed", type=float, default=25)
    parser.add_argument("--fps", type=float, default=20)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--n", type=int, default=32)
    parser.add_argument("--order", default="rgb")
    parser.add_argument("--inverted", default="")
    parser.add_argument("--pre-fill", action="store_true")
    return parser.parse_args()


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


if __name__ == "__main__":
    raise SystemExit(main())
