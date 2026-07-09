#!/usr/bin/env python3
"""Run a selected Lyte animation on Twinkly generation 2 lights."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Protocol

import numpy as np
from numpy import typing as npt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lyte import LyteClient, discover
from lyte.bibliopixel import (
    DEFAULT_PATTERN,
    RGB,
    Alternates,
    ColorChase,
    ColorFade,
    ColorFill,
    ColorPattern,
    ColorWipe,
    FireFlies,
    HalvesRainbow,
    LarsonScanner,
    LinearRainbow,
    PartyMode,
    PixelPingPong,
    Pulse,
    Rainbow,
    RainbowCycle,
    SaberBlade,
    Searchlights,
    Twinkle,
    Wave,
    WhiteTwinkle,
)
from lyte.hamiltonian import HamiltonianStreamer
from lyte.logging import log, log_error
from lyte.random_walk import RandomWalk
from lyte.retry import RetryConfig
from lyte.session import (
    authenticate_with_retry,
    led_count_from_gestalt,
    read_gestalt,
    send_frame_with_retry,
    set_mac_from_gestalt,
    set_realtime_mode_with_retry,
)


class Streamer(Protocol):
    def next_frame(self) -> npt.NDArray[np.uint8]:
        pass


def main() -> int:
    args = parse_args()
    host = args.host or discover_host(args.discovery_timeout)
    if host is None:
        return 1

    retry = RetryConfig(
        attempts=args.attempts,
        delay=args.retry_delay,
        backoff=args.retry_backoff,
    )
    client = LyteClient(host=host, timeout=args.timeout)
    led_count = read_led_count(client, retry, args.led_count, host)
    if led_count is None:
        return 1
    if not prepare_device(client, retry, host):
        return 1

    streamer = build_streamer(args, led_count)
    frame_delay = 1 / args.fps
    stop_at = None if args.duration is None else time.monotonic() + args.duration
    log(
        "[ok] Streaming "
        f"{args.animation} frames to {host} for {led_count} LEDs at {args.fps} FPS"
    )

    try:
        while stop_at is None or time.monotonic() < stop_at:
            started_at = time.monotonic()
            frame = streamer.next_frame()
            if client.token is None:
                sys.exit("Authentication token disappeared before frame send.")
            sent = send_frame_with_retry(
                host,
                client.token.value,
                frame,
                retry,
                f"UDP realtime frame send to {host}",
            )
            if sent is None:
                sys.exit(f"Could not send realtime frame to {host}.")
            remaining = frame_delay - (time.monotonic() - started_at)
            if remaining > 0:
                time.sleep(remaining)
    except KeyboardInterrupt:
        log()
        log("[ok] Stopped")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "animation",
        choices=(
            "alternates",
            "color_chase",
            "color_fade",
            "color_fill",
            "color_pattern",
            "color_wipe",
            "fire_flies",
            "halves_rainbow",
            "hamiltonian",
            "larson_rainbow",
            "larson_scanner",
            "linear_rainbow",
            "party_mode",
            "pixel_ping_pong",
            "pulse",
            "rainbow",
            "rainbow_cycle",
            "random_walk",
            "saber_blade",
            "searchlights",
            "twinkle",
            "wave",
            "wave_move",
            "white_twinkle",
        ),
        help="Animation to stream.",
    )
    parser.add_argument("--host")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--discovery-timeout", type=float, default=5.0)
    parser.add_argument(
        "--attempts",
        type=int,
        default=10,
        help="Attempts for transient HTTP and UDP operations.",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=0.5,
        help="Initial delay between retries, in seconds.",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=2.0,
        help="Retry delay multiplier after each failed attempt.",
    )
    parser.add_argument("--led-count", type=int)
    parser.add_argument("--speed", type=float, default=25)
    parser.add_argument("--fps", type=float, default=20)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--pre-fill", action="store_true")
    parser.add_argument("--center-in", action="store_true")
    parser.add_argument("--individual-pixel", action="store_true")
    parser.add_argument("--step", type=int, default=1)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int)
    parser.add_argument("--width", type=int, default=1)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--tail", type=int, default=2)
    parser.add_argument("--chance", type=int, default=30)
    parser.add_argument("--min-speed", type=int, default=1)
    parser.add_argument("--max-speed", type=int, default=5)
    parser.add_argument("--total-pixels", type=int, default=1)
    parser.add_argument("--fade-delay", type=int, default=1)
    parser.add_argument("--density", type=int, default=20)
    parser.add_argument("--max-bright", type=int, default=255)
    parser.add_argument("--cycles", type=int, default=2)
    parser.add_argument("--level-step", type=int, default=5)
    parser.add_argument("--rainbow-inc", type=int, default=4)
    parser.add_argument("--max-led", type=int)
    parser.add_argument("--reverse", action="store_true")
    parser.add_argument("--n", type=int, default=32)
    parser.add_argument("--order", default="rgb")
    parser.add_argument("--inverted", default="")
    parser.add_argument("--variance", type=float, default=1)
    parser.add_argument("--bounds", type=float, nargs=2, default=(0, 180))
    parser.add_argument("--color", type=int, nargs=3)
    parser.add_argument("--color2", type=int, nargs=3)
    parser.add_argument("--colors", type=int, nargs="+")
    parser.add_argument("--period", type=float, default=0)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    if args.attempts < 1:
        parser.error("--attempts must be at least 1")
    if args.retry_delay < 0:
        parser.error("--retry-delay must not be negative")
    if args.retry_backoff < 1:
        parser.error("--retry-backoff must be at least 1")
    if args.fps <= 0:
        parser.error("--fps must be greater than zero")
    if args.speed < 0:
        parser.error("--speed must not be negative")
    if args.variance < 0:
        parser.error("--variance must not be negative")
    if args.bounds[0] >= args.bounds[1]:
        parser.error("--bounds must be ordered low high")
    if args.color is not None and any(c < 0 or c > 255 for c in args.color):
        parser.error("--color components must be between 0 and 255")
    if args.color2 is not None and any(c < 0 or c > 255 for c in args.color2):
        parser.error("--color2 components must be between 0 and 255")
    if args.colors is not None:
        if len(args.colors) % 3:
            parser.error("--colors must contain complete RGB triples")
        if any(c < 0 or c > 255 for c in args.colors):
            parser.error("--colors components must be between 0 and 255")
    if args.step < 1:
        parser.error("--step must be at least 1")
    if args.width < 1:
        parser.error("--width must be at least 1")
    if args.count < 1:
        parser.error("--count must be at least 1")
    if args.tail < 0:
        parser.error("--tail must not be negative")
    if args.chance < 0 or args.chance > 100:
        parser.error("--chance must be between 0 and 100")
    if args.min_speed < 1 or args.max_speed <= args.min_speed:
        parser.error("--min-speed and --max-speed must define a non-empty range")
    if args.total_pixels < 1:
        parser.error("--total-pixels must be at least 1")
    if args.fade_delay < 1:
        parser.error("--fade-delay must be at least 1")
    if args.density < 1:
        parser.error("--density must be at least 1")
    if args.max_bright < 1 or args.max_bright > 255:
        parser.error("--max-bright must be between 1 and 255")
    if args.cycles < 1:
        parser.error("--cycles must be at least 1")
    if args.level_step < 1:
        parser.error("--level-step must be at least 1")
    if args.rainbow_inc < 0:
        parser.error("--rainbow-inc must not be negative")
    if args.start < 0:
        parser.error("--start must not be negative")
    return args


def build_streamer(args: argparse.Namespace, led_count: int) -> Streamer:
    if args.animation == "hamiltonian":
        return HamiltonianStreamer(
            led_count=led_count,
            speed=args.speed,
            fps=args.fps,
            n=args.n,
            order=args.order,
            inverted=args.inverted,
            pre_fill=args.pre_fill,
        )
    if args.animation == "color_chase":
        return ColorChase(
            led_count=led_count,
            color=rgb_arg(args.color, (255, 0, 0)),
            width=args.width,
            start=args.start,
            end=args.end,
            step=args.step,
        )
    if args.animation == "color_wipe":
        return ColorWipe(
            led_count=led_count,
            color=rgb_arg(args.color, (255, 0, 0)),
            start=args.start,
            end=args.end,
            step=args.step,
        )
    if args.animation == "color_fill":
        return ColorFill(
            led_count=led_count,
            color=rgb_arg(args.color, (255, 0, 0)),
        )
    if args.animation == "color_fade":
        return ColorFade(
            led_count=led_count,
            colors=colors_arg(args.colors, ((255, 0, 0),)),
            level_step=args.level_step,
            start=args.start,
            end=args.end,
        )
    if args.animation == "alternates":
        return Alternates(
            led_count=led_count,
            color1=rgb_arg(args.color, (255, 255, 255)),
            color2=rgb_arg(args.color2, (0, 0, 0)),
            max_led=args.max_led,
        )
    if args.animation == "color_pattern":
        return ColorPattern(
            led_count=led_count,
            colors=colors_arg(args.colors),
            width=args.width,
            reverse=args.reverse,
        )
    if args.animation == "party_mode":
        return PartyMode(led_count=led_count, colors=colors_arg(args.colors))
    if args.animation == "fire_flies":
        return FireFlies(
            led_count=led_count,
            colors=colors_arg(args.colors, ((255, 0, 0),)),
            width=args.width,
            count=args.count,
            start=args.start,
            end=args.end,
            seed=args.seed,
        )
    if args.animation == "saber_blade":
        return SaberBlade(
            led_count=led_count,
            colors=colors_arg(args.colors, ((255, 0, 0),)),
            speed=round(args.speed),
        )
    if args.animation == "rainbow":
        return Rainbow(
            led_count=led_count,
            start=args.start,
            end=args.end,
            step=args.step,
        )
    if args.animation == "rainbow_cycle":
        return RainbowCycle(
            led_count=led_count,
            start=args.start,
            end=args.end,
            step=args.step,
        )
    if args.animation == "linear_rainbow":
        return LinearRainbow(
            led_count=led_count,
            max_led=args.max_led,
            individual_pixel=args.individual_pixel,
            step=args.step,
        )
    if args.animation == "halves_rainbow":
        return HalvesRainbow(
            led_count=led_count,
            max_led=args.max_led,
            center_out=not args.center_in,
            rainbow_inc=args.rainbow_inc,
            step=args.step,
        )
    if args.animation in ("larson_scanner", "larson_rainbow"):
        return LarsonScanner(
            led_count=led_count,
            color=rgb_arg(args.color, (255, 0, 0)),
            tail=args.tail,
            start=args.start,
            end=args.end,
            step=args.step,
            rainbow=args.animation == "larson_rainbow",
        )
    if args.animation == "pulse":
        return Pulse(
            led_count=led_count,
            colors=colors_arg(args.colors, ((255, 0, 0),)),
            tail=args.tail,
            chance=args.chance,
            min_speed=args.min_speed,
            max_speed=args.max_speed,
            seed=args.seed,
        )
    if args.animation == "pixel_ping_pong":
        return PixelPingPong(
            led_count=led_count,
            color=rgb_arg(args.color, (255, 255, 255)),
            max_led=args.max_led,
            total_pixels=args.total_pixels,
            fade_delay=args.fade_delay,
        )
    if args.animation == "searchlights":
        return Searchlights(
            led_count=led_count,
            colors=colors_arg(args.colors, DEFAULT_PATTERN),
            tail=args.tail,
            start=args.start,
            end=args.end,
            seed=args.seed,
        )
    if args.animation in ("wave", "wave_move"):
        return Wave(
            led_count=led_count,
            color=rgb_arg(args.color, (255, 0, 0)),
            cycles=args.cycles,
            start=args.start,
            end=args.end,
            moving=args.animation == "wave_move",
        )
    if args.animation == "twinkle":
        return Twinkle(
            led_count=led_count,
            colors=colors_arg(args.colors),
            density=args.density,
            speed=round(args.speed),
            max_bright=args.max_bright,
            seed=args.seed,
        )
    if args.animation == "white_twinkle":
        return WhiteTwinkle(
            led_count=led_count,
            density=args.density,
            speed=round(args.speed),
            max_bright=args.max_bright,
            seed=args.seed,
        )
    color = (
        None
        if args.color is None
        else (float(args.color[0]), float(args.color[1]), float(args.color[2]))
    )
    return RandomWalk(
        led_count=led_count,
        speed=args.speed,
        fps=args.fps,
        variance=args.variance,
        bounds=(args.bounds[0], args.bounds[1]),
        color=color,
        period=args.period,
        pre_fill=args.pre_fill,
        seed=args.seed,
    )


def rgb_arg(value: list[int] | None, default: RGB) -> RGB:
    if value is None:
        return default
    return value[0], value[1], value[2]


def colors_arg(
    value: list[int] | None,
    default: tuple[RGB, ...] = DEFAULT_PATTERN,
) -> tuple[RGB, ...]:
    if value is None:
        return default
    return tuple(
        (value[i], value[i + 1], value[i + 2]) for i in range(0, len(value), 3)
    )


def read_led_count(
    client: LyteClient,
    retry: RetryConfig,
    configured_led_count: int | None,
    host: str,
) -> int | None:
    log(f"[step] Reading device info from {host}")
    gestalt = read_gestalt(
        client,
        retry,
        f"HTTP device info read from {host}",
    )
    if gestalt is None:
        sys.exit(f"Could not read device info from {host}.")
    set_mac_from_gestalt(client, gestalt)
    if configured_led_count is not None:
        return configured_led_count
    led_count = led_count_from_gestalt(gestalt)
    if led_count is None:
        sys.exit("Device did not report number_of_led; pass --led-count.")
    return led_count


def prepare_device(client: LyteClient, retry: RetryConfig, host: str) -> bool:
    log("[step] Authenticating")
    token = authenticate_with_retry(
        client,
        retry,
        f"login and verify with {host}",
    )
    if token is None:
        sys.exit(f"Could not authenticate with {host}.")
    if client.token is None:
        sys.exit("Authentication succeeded without producing a token.")

    log("[step] Switching to realtime mode")
    realtime_response = set_realtime_mode_with_retry(
        client,
        retry,
        f"switch {host} to realtime mode",
    )
    if realtime_response is None:
        sys.exit(f"Could not switch {host} to realtime mode.")
    return True


def discover_host(timeout: float) -> str | None:
    log("[step] Discovering Twinkly devices")
    devices = list(discover(timeout=timeout))
    if not devices:
        log_error("[failed] No Twinkly discovery replies received.")
        log_error("Pass --host with the device IP address.")
        return None
    if len(devices) > 1:
        log("[warn] Multiple devices found; using the first one.")
    device = devices[0]
    log(f"[ok] Found {device.device_id} at {device.ip_address}")
    return device.ip_address


if __name__ == "__main__":
    raise SystemExit(main())
