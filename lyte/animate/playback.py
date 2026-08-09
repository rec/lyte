from __future__ import annotations

import math
import random
import time
from collections.abc import Sequence

import numpy as np
import tyro
from numpy.typing import NDArray
from pydantic import BaseModel

from .. import animation
from ..logging import log, log_status
from ..retry import RetryConfig
from ..twinkly import realtime
from ..twinkly.client import TwinklyClient
from . import random_show
from .build import build_animation
from .config import AnimateConfig, validate_args


class FrameDeadlineReport(BaseModel):
    frame_count: int = 0
    late_frames: int = 0
    missed_deadlines: int = 0
    worst_overrun_ms: float = 0
    recovery_count: int = 0
    recovery_duration_ms: float = 0

    def record_frame(self, elapsed: float, deadline: float) -> None:
        self.frame_count += 1
        overrun = elapsed - deadline
        if overrun <= 0:
            return
        self.late_frames += 1
        self.missed_deadlines += max(1, math.floor(elapsed / deadline))
        self.worst_overrun_ms = max(self.worst_overrun_ms, overrun * 1000)

    def record_recovery(self, duration: float) -> None:
        self.recovery_count += 1
        self.recovery_duration_ms += duration * 1000

    def log_report(self, name: str, fps: float) -> None:
        log_status(
            f'[report] {name} {fps:g} FPS: {self.frame_count} frames, '
            f'{self.late_frames} late frames, {self.missed_deadlines} missed '
            f'deadlines, worst overrun {self.worst_overrun_ms:.2f} ms, '
            f'{self.recovery_count} recoveries over '
            f'{self.recovery_duration_ms:.2f} ms.'
        )


def main() -> int:
    args = parse_args()
    return run_animate(args)


def run_animate(args: AnimateConfig) -> int:
    validate_args(args)
    connection = realtime.PlaybackConnection()
    connection.set_state(realtime.PlaybackConnectionState.CONNECTING)
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
    device = animation.Device(led_count=led_count)
    try:
        if not realtime.prepare_device(client, retry, host):
            return 1
        connection.resume_streaming()
        if args.animation == 'random':
            run_random_animations(args, client, retry, host, device, connection)
        else:
            run_animation(args, client, retry, host, device, args.duration, connection)
    except KeyboardInterrupt:
        log()
        log('[ok] Stopped')
    finally:
        connection.finish_blackout(
            realtime.turn_off_streaming_device(client, retry, host)
        )
    return 0


def parse_args(args: Sequence[str] | None = None) -> AnimateConfig:
    return tyro.cli(AnimateConfig, args=args)


def run_random_animations(
    args: AnimateConfig,
    client: TwinklyClient,
    retry: RetryConfig,
    host: str,
    device: animation.Device,
    connection: realtime.PlaybackConnection | None = None,
) -> None:
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
                client,
                retry,
                host,
                device,
                solo_duration,
                connection,
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
                client,
                retry,
                host,
                device,
                clipped_overlap_duration,
                connection,
            )
        current_args = next_args
        current_animation = next_animation
        current_state = next_state
        current_duration = next_duration


def run_animation(
    args: AnimateConfig,
    client: TwinklyClient,
    retry: RetryConfig,
    host: str,
    device: animation.Device,
    duration: float | None,
    connection: realtime.PlaybackConnection | None = None,
) -> None:
    source = build_animation(args)
    state = source.initial_state(device)
    state.fps = args.fps
    run_animation_state(
        source, state, args, client, retry, host, device, duration, connection
    )


def run_animation_state(
    source: animation.Animation,
    state: animation.State,
    args: AnimateConfig,
    client: TwinklyClient,
    retry: RetryConfig,
    host: str,
    device: animation.Device,
    duration: float | None,
    connection: realtime.PlaybackConnection | None = None,
) -> None:
    frame_delay = 1 / args.fps
    stop_at = None if duration is None else time.monotonic() + duration
    report = FrameDeadlineReport()
    log(
        '[ok] Streaming '
        f'{args.animation} frames to {host} for {device.led_count} LEDs '
        f'at {args.fps} FPS'
    )

    try:
        while stop_at is None or time.monotonic() < stop_at:
            started_at = time.monotonic()
            frame = animation.byte_light_frame_from_float(
                animation.validate_frame(device, source.render(device, state))
            )
            result = realtime.send_realtime_frame(client, retry, host, frame)
            elapsed = time.monotonic() - started_at
            report.record_frame(elapsed, frame_delay)
            if result.status is not realtime.FrameSendStatus.SENT:
                if connection is not None:
                    connection.begin_recovery()
                recovery_started_at = time.monotonic()
                host = realtime.recover_streaming_device(
                    client,
                    retry,
                    args.host,
                    args.discovery_timeout,
                    device.led_count,
                )
                report.record_recovery(time.monotonic() - recovery_started_at)
                if connection is not None:
                    connection.resume_streaming()
                continue
            remaining = frame_delay - elapsed
            if remaining > 0:
                time.sleep(remaining)
    finally:
        report.log_report(args.animation, args.fps)


def run_crossfade(
    current_animation: animation.Animation,
    current_state: animation.State,
    next_animation: animation.Animation,
    next_state: animation.State,
    args: AnimateConfig,
    client: TwinklyClient,
    retry: RetryConfig,
    host: str,
    device: animation.Device,
    duration: float,
    connection: realtime.PlaybackConnection | None = None,
) -> None:
    frame_delay = 1 / args.fps
    started_at = time.monotonic()
    stop_at = started_at + duration
    report = FrameDeadlineReport()

    try:
        while time.monotonic() < stop_at:
            frame_started_at = time.monotonic()
            progress = (frame_started_at - started_at) / duration
            frame = blend_frames(
                animation.validate_frame(
                    device, current_animation.render(device, current_state)
                ),
                animation.validate_frame(
                    device, next_animation.render(device, next_state)
                ),
                progress,
            )
            result = realtime.send_realtime_frame(
                client, retry, host, animation.byte_light_frame_from_float(frame)
            )
            elapsed = time.monotonic() - frame_started_at
            report.record_frame(elapsed, frame_delay)
            if result.status is not realtime.FrameSendStatus.SENT:
                if connection is not None:
                    connection.begin_recovery()
                recovery_started_at = time.monotonic()
                host = realtime.recover_streaming_device(
                    client,
                    retry,
                    args.host,
                    args.discovery_timeout,
                    device.led_count,
                )
                report.record_recovery(time.monotonic() - recovery_started_at)
                if connection is not None:
                    connection.resume_streaming()
                continue
            remaining = frame_delay - elapsed
            if remaining > 0:
                time.sleep(remaining)
    finally:
        report.log_report('crossfade', args.fps)


def blend_frames(
    current_frame: NDArray[np.float32],
    next_frame: NDArray[np.float32],
    progress: float,
) -> NDArray[np.float32]:
    if current_frame.shape != next_frame.shape:
        raise ValueError('cannot blend frames with different shapes')
    progress = max(0.0, min(1.0, progress))
    return current_frame * (1.0 - progress) + next_frame * progress
