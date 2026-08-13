from __future__ import annotations

import random
import time
from collections.abc import Sequence

import numpy as np
import tyro
from numpy.typing import NDArray
from reccy import logging

from .. import animation
from ..retry import RetryConfig
from ..twinkly import realtime, track
from ..twinkly.client import TwinklyClient
from . import random_show
from .build import build_animation
from .config import AnimateConfig, validate_args

LOGGER = logging.get_logger(__name__)


def main() -> int:
    args = parse_args()
    return run_animate(args)


def run_animate(args: AnimateConfig) -> int:
    validate_args(args)
    host = args.host or realtime.discover_host(args.discovery_timeout)
    if host is None:
        return 1

    retry = RetryConfig(
        attempts=args.attempts,
        delay=args.retry_delay,
        backoff=args.retry_backoff,
    )
    client = TwinklyClient(host=host, timeout=args.timeout)
    if args.animation == 'off':
        return 0 if realtime.turn_off_device(client, retry, host) else 1

    led_count = realtime.read_led_count(client, retry, args.led_count, host)
    if led_count is None:
        return 1
    twinkly_track = track.TwinklyTrack(
        client=client,
        retry=retry,
        host=host,
        configured_host=args.host,
        discovery_timeout=args.discovery_timeout,
        device=animation.Device(led_count=led_count),
    )
    try:
        if not twinkly_track.prepare():
            return 1
        if args.animation == 'random':
            run_random_animations(args, twinkly_track)
        else:
            run_animation(args, twinkly_track, args.duration)
    except KeyboardInterrupt:
        LOGGER.debug('')
        LOGGER.debug('[ok] Stopped')
    finally:
        twinkly_track.close()
    return 0


def parse_args(args: Sequence[str] | None = None) -> AnimateConfig:
    return tyro.cli(AnimateConfig, args=args)


def run_random_animations(
    args: AnimateConfig,
    twinkly_track: track.TwinklyTrack,
) -> None:
    device = twinkly_track.device
    generator = random.Random(args.seed)
    stop_at = None if args.duration is None else time.monotonic() + args.duration
    current_args = random_show.random_animation_args(args, generator, None)
    current_animation = build_animation(current_args)
    current_state = current_animation.initial_state(device)
    current_state.fps = current_args.fps
    current_duration = random_show.random_pattern_duration(generator)
    previous_animation = current_args.animation
    random_show.log_pattern_start(current_args.animation, current_duration)

    while stop_at is None or time.monotonic() < stop_at:
        overlap_duration = random_show.random_overlap_duration(current_duration)
        solo_duration = random_show.clipped_duration(
            current_duration - overlap_duration,
            stop_at,
        )
        if solo_duration > 0:
            run_animation_state(
                current_animation,
                current_state,
                current_args,
                twinkly_track,
                solo_duration,
            )
        if stop_at is not None and time.monotonic() >= stop_at:
            return

        next_args = random_show.random_animation_args(
            args, generator, previous_animation
        )
        next_animation = build_animation(next_args)
        next_state = next_animation.initial_state(device)
        next_state.fps = next_args.fps
        next_duration = random_show.random_pattern_duration(generator)
        previous_animation = next_args.animation
        random_show.log_pattern_start(next_args.animation, next_duration)

        clipped_overlap_duration = random_show.clipped_duration(
            overlap_duration, stop_at
        )
        if clipped_overlap_duration > 0:
            run_crossfade(
                current_animation,
                current_state,
                next_animation,
                next_state,
                next_args,
                twinkly_track,
                clipped_overlap_duration,
            )
        current_args = next_args
        current_animation = next_animation
        current_state = next_state
        current_duration = next_duration


def run_animation(
    args: AnimateConfig,
    twinkly_track: track.TwinklyTrack,
    duration: float | None,
) -> None:
    source = build_animation(args)
    state = source.initial_state(twinkly_track.device)
    state.fps = args.fps
    run_animation_state(source, state, args, twinkly_track, duration)


def run_animation_state(
    source: animation.Animation,
    state: animation.State,
    args: AnimateConfig,
    twinkly_track: track.TwinklyTrack,
    duration: float | None,
) -> None:
    device = twinkly_track.device
    LOGGER.debug(
        '[ok] Streaming '
        f'{args.animation} frames to {twinkly_track.host} for {device.led_count} LEDs '
        f'at {args.fps} FPS'
    )
    twinkly_track.stream_frames(
        args.animation,
        args.fps,
        duration,
        lambda: animation.byte_light_frame_from_float(
            animation.validate_frame(device, source.render(device, state))
        ),
    )


def run_crossfade(
    current_animation: animation.Animation,
    current_state: animation.State,
    next_animation: animation.Animation,
    next_state: animation.State,
    args: AnimateConfig,
    twinkly_track: track.TwinklyTrack,
    duration: float,
) -> None:
    device = twinkly_track.device
    started_at = time.monotonic()

    def render_frame() -> NDArray[np.uint8]:
        progress = (time.monotonic() - started_at) / duration
        frame = blend_frames(
            animation.validate_frame(
                device, current_animation.render(device, current_state)
            ),
            animation.validate_frame(device, next_animation.render(device, next_state)),
            progress,
        )
        return animation.byte_light_frame_from_float(frame)

    twinkly_track.stream_frames('crossfade', args.fps, duration, render_frame)


def blend_frames(
    current_frame: NDArray[np.float32],
    next_frame: NDArray[np.float32],
    progress: float,
) -> NDArray[np.float32]:
    if current_frame.shape != next_frame.shape:
        raise ValueError('cannot blend frames with different shapes')
    progress = max(0.0, min(1.0, progress))
    return current_frame * (1.0 - progress) + next_frame * progress
