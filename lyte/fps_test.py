from __future__ import annotations

import math
import os
import select
import sys
import termios
import time
import tty
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal, TextIO

import numpy as np
from numpy.typing import NDArray

from .animation import Device, validate_byte_rgb_frame
from .animations.bibliopixel import RGB
from .logging import log, log_error, log_status
from .retry import RetryConfig
from .twinkly.client import TwinklyClient
from .twinkly.realtime import (
    discover_host,
    prepare_device,
    read_led_count,
    send_realtime_frame,
    turn_off_device,
)

FPS_VALUES: tuple[float, ...] = (30.0, 60.0, 120.0, 240, 480, 960, 1920)
LOW_CONTRAST_BLEND: tuple[RGB, RGB] = ((255, 0, 80), (0, 160, 255))
HIGH_CONTRAST_BLEND: tuple[RGB, RGB] = ((0, 255, 120), (255, 240, 0))
TEST2_ANIMATION_FPS = 60.0
TEST2_TEMPORAL_FACTOR = 4
TEST2_TRANSPORT_FPS = TEST2_ANIMATION_FPS * TEST2_TEMPORAL_FACTOR
VERIFY_FPS = 60.0
VERIFY_BLACK_DURATION = 1.0
VERIFY_DEMO_DURATION = 3.0
VERIFY_SLOW_FADE_DURATION = 1.0
UP_KEY = '\x1b[A'
DOWN_KEY = '\x1b[B'


@dataclass(frozen=True)
class FadeReport:
    fps: float
    phase: str
    total_frames: int
    unique_frames: int
    late_frames: int
    short_sends: int
    max_late_ms: float
    elapsed_ms: float

    @property
    def duplicate_frames(self) -> int:
        return self.total_frames - self.unique_frames


@dataclass(frozen=True)
class VerifyDemo:
    name: str
    frame_at: Callable[[Device, int, int], NDArray[np.uint8]]


@dataclass(frozen=True)
class VerifyResult:
    name: str
    worked: bool | None


@dataclass(frozen=True)
class FpsTestConfig:
    host: str | None = None
    timeout: float = 5.0
    discovery_timeout: float | None = None
    attempts: int = 10
    retry_delay: float = 0.5
    retry_backoff: float = 2.0
    led_count: int | None = None
    duration: float = 2.0
    pause: float = 1


@dataclass(frozen=True)
class TemporalDitherTestConfig:
    host: str | None = None
    timeout: float = 5.0
    discovery_timeout: float | None = None
    attempts: int = 10
    retry_delay: float = 0.5
    retry_backoff: float = 2.0
    led_count: int | None = None
    time: float = 5.0


@dataclass(frozen=True)
class BlackFloorTestConfig:
    host: str | None = None
    timeout: float = 5.0
    discovery_timeout: float | None = None
    attempts: int = 10
    retry_delay: float = 0.5
    retry_backoff: float = 2.0
    led_count: int | None = None


@dataclass(frozen=True)
class VerifyConfig:
    host: str | None = None
    timeout: float = 5.0
    discovery_timeout: float | None = None
    attempts: int = 10
    retry_delay: float = 0.5
    retry_backoff: float = 2.0
    led_count: int | None = None
    mode: Literal['fast', 'slow'] = 'fast'


def run_fps_test(config: FpsTestConfig) -> int:
    validate_config(config)
    return run_realtime_command(
        config.host,
        config.timeout,
        config.discovery_timeout,
        config.attempts,
        config.retry_delay,
        config.retry_backoff,
        config.led_count,
        lambda client, retry, host, device: run_fades(
            client, retry, host, device, config.duration, config.pause
        ),
    )


def run_verify_test(config: VerifyConfig) -> int:
    validate_verify_config(config)

    def verify_action(
        client: TwinklyClient,
        retry: RetryConfig,
        host: str,
        device: Device,
    ) -> None:
        log_verify_demos()
        if config.mode == 'slow':
            results = run_slow_verify(client, retry, host, device)
        else:
            results = run_fast_verify(client, retry, host, device)
        report_verify_results(results)

    return run_realtime_command(
        config.host,
        config.timeout,
        config.discovery_timeout,
        config.attempts,
        config.retry_delay,
        config.retry_backoff,
        config.led_count,
        verify_action,
    )


def run_temporal_dither_test(config: TemporalDitherTestConfig) -> int:
    validate_temporal_dither_config(config)
    return run_realtime_command(
        config.host,
        config.timeout,
        config.discovery_timeout,
        config.attempts,
        config.retry_delay,
        config.retry_backoff,
        config.led_count,
        lambda client, retry, host, device: run_temporal_dither_comparison(
            client, retry, host, device, config.time
        ),
    )


def run_black_floor_test(config: BlackFloorTestConfig) -> int:
    validate_black_floor_config(config)
    return run_realtime_command(
        config.host,
        config.timeout,
        config.discovery_timeout,
        config.attempts,
        config.retry_delay,
        config.retry_backoff,
        config.led_count,
        run_interactive_black_floor,
    )


def run_realtime_command(
    configured_host: str | None,
    timeout: float,
    discovery_timeout: float | None,
    attempts: int,
    retry_delay: float,
    retry_backoff: float,
    configured_led_count: int | None,
    action: Callable[[TwinklyClient, RetryConfig, str, Device], None],
) -> int:
    host = configured_host or discover_host(discovery_timeout)
    if host is None:
        return 1

    retry = RetryConfig(
        attempts=attempts,
        delay=retry_delay,
        backoff=retry_backoff,
    )
    client = TwinklyClient(host=host, timeout=timeout)
    try:
        led_count = read_led_count(client, retry, configured_led_count, host)
        if led_count is None:
            return 1
        device = Device(led_count=led_count)
        if not prepare_device(client, retry, host):
            return 1
        action(client, retry, host, device)
    except KeyboardInterrupt:
        log()
        log('[ok] Stopped')
    finally:
        turn_off_device(client, retry, host)
    return 0


def validate_config(config: FpsTestConfig) -> None:
    validate_discovery_timeout(config.discovery_timeout)
    if config.attempts < 1:
        sys.exit('--attempts must be at least 1')
    if config.retry_delay < 0:
        sys.exit('--retry-delay must not be negative')
    if config.retry_backoff < 1:
        sys.exit('--retry-backoff must be at least 1')
    if config.duration <= 0:
        sys.exit('--duration must be greater than zero')
    if config.pause < 0:
        sys.exit('--pause must not be negative')


def validate_temporal_dither_config(config: TemporalDitherTestConfig) -> None:
    validate_discovery_timeout(config.discovery_timeout)
    if config.attempts < 1:
        sys.exit('--attempts must be at least 1')
    if config.retry_delay < 0:
        sys.exit('--retry-delay must not be negative')
    if config.retry_backoff < 1:
        sys.exit('--retry-backoff must be at least 1')
    if config.time <= 0:
        sys.exit('--time must be greater than zero')


def validate_black_floor_config(config: BlackFloorTestConfig) -> None:
    validate_discovery_timeout(config.discovery_timeout)
    if config.attempts < 1:
        sys.exit('--attempts must be at least 1')
    if config.retry_delay < 0:
        sys.exit('--retry-delay must not be negative')
    if config.retry_backoff < 1:
        sys.exit('--retry-backoff must be at least 1')


def validate_verify_config(config: VerifyConfig) -> None:
    validate_discovery_timeout(config.discovery_timeout)
    if config.attempts < 1:
        sys.exit('--attempts must be at least 1')
    if config.retry_delay < 0:
        sys.exit('--retry-delay must not be negative')
    if config.retry_backoff < 1:
        sys.exit('--retry-backoff must be at least 1')


def validate_discovery_timeout(timeout: float | None) -> None:
    if timeout is not None and timeout <= 0:
        sys.exit('--discovery-timeout must be greater than zero')


def gradient_frame(led_count: int, start: RGB, end: RGB) -> NDArray[np.uint8]:
    if led_count <= 0:
        raise ValueError('led_count must be greater than zero')
    if led_count == 1:
        return np.array([start], dtype=np.uint8)
    start_array = np.array(start, dtype=np.float32)
    end_array = np.array(end, dtype=np.float32)
    positions = np.linspace(0.0, 1.0, led_count, dtype=np.float32)[:, np.newaxis]
    return np.rint(start_array * (1.0 - positions) + end_array * positions).astype(
        np.uint8
    )


def blend_frames(
    first_frame: NDArray[np.uint8],
    second_frame: NDArray[np.uint8],
    progress: float,
) -> NDArray[np.uint8]:
    if first_frame.shape != second_frame.shape:
        raise ValueError('cannot blend frames with different shapes')
    progress = max(0.0, min(1.0, progress))
    blended = (
        first_frame.astype(np.float32) * (1.0 - progress)
        + second_frame.astype(np.float32) * progress
    )
    return np.rint(blended).astype(np.uint8)


def dispersed_pixel_order(led_count: int) -> NDArray[np.int64]:
    if led_count <= 0:
        raise ValueError('led_count must be greater than zero')
    if led_count == 1:
        return np.array([0], dtype=np.int64)
    midpoint = led_count / 2
    stride = min(
        (i for i in range(1, led_count) if math.gcd(i, led_count) == 1),
        key=lambda i: (abs(i - midpoint), i),
    )
    return np.fromiter(
        ((i * stride) % led_count for i in range(led_count)),
        dtype=np.int64,
        count=led_count,
    )


def temporal_dither_grayscale_frame(
    device: Device,
    start: int,
    end: int,
    index: int,
    frame_count: int,
    order: NDArray[np.int64],
) -> NDArray[np.uint8]:
    if frame_count < 2:
        raise ValueError('frame_count must be at least 2')
    if not 0 <= start <= 255 or not 0 <= end <= 255:
        raise ValueError('start and end must be 8-bit channel values')
    if len(order) != device.led_count:
        raise ValueError('order must have one entry per LED')
    progress = index / (frame_count - 1)
    ideal = start + (end - start) * max(0.0, min(1.0, progress))
    lower = math.floor(ideal)
    upper = math.ceil(ideal)
    fraction = ideal - lower
    high_count = round(fraction * device.led_count)
    frame = np.full((device.led_count, 3), lower, dtype=np.uint8)
    if high_count and upper != lower:
        offset = lower % device.led_count
        selected = np.concatenate((order[offset:], order[:offset]))[:high_count]
        frame[selected] = upper
    return frame


def run_fades(
    client: TwinklyClient,
    retry: RetryConfig,
    host: str,
    device: Device,
    duration: float,
    pause: float,
) -> None:
    black_frame = np.zeros((device.led_count, 3), dtype=np.uint8)
    first_frame = gradient_frame(device.led_count, *LOW_CONTRAST_BLEND)
    second_frame = gradient_frame(device.led_count, *HIGH_CONTRAST_BLEND)
    for fps in FPS_VALUES:
        log_status(f'[test] Fading black -> blend -> blend -> black at {fps:g} FPS')
        reports = (
            stream_fade(
                client,
                retry,
                host,
                device,
                black_frame,
                first_frame,
                fps,
                duration,
                'black-to-first',
            ),
            stream_fade(
                client,
                retry,
                host,
                device,
                first_frame,
                second_frame,
                fps,
                duration,
                'first-to-second',
            ),
            stream_fade(
                client,
                retry,
                host,
                device,
                second_frame,
                black_frame,
                fps,
                duration,
                'second-to-black',
            ),
        )
        report_fades(reports)
        if pause:
            time.sleep(pause)


def run_fast_verify(
    client: TwinklyClient,
    retry: RetryConfig,
    host: str,
    device: Device,
) -> tuple[VerifyResult, ...]:
    results = []
    black_frame = np.zeros((device.led_count, 3), dtype=np.uint8)
    for demo in VERIFY_DEMOS:
        log_status(f'[verify] {demo.name}')
        reports = (
            stream_frames(
                client,
                retry,
                host,
                device,
                VERIFY_FPS,
                VERIFY_BLACK_DURATION,
                f'{demo.name}-black-before',
                lambda _index, _frame_count: black_frame,
            ),
            stream_frames(
                client,
                retry,
                host,
                device,
                VERIFY_FPS,
                VERIFY_DEMO_DURATION,
                demo.name,
                lambda index, frame_count, demo=demo: demo.frame_at(
                    device, index, frame_count
                ),
            ),
            stream_frames(
                client,
                retry,
                host,
                device,
                VERIFY_FPS,
                VERIFY_BLACK_DURATION,
                f'{demo.name}-black-after',
                lambda _index, _frame_count: black_frame,
            ),
        )
        report_fades(reports)
        results.append(VerifyResult(demo.name, None))
    return tuple(results)


def run_slow_verify(
    client: TwinklyClient,
    retry: RetryConfig,
    host: str,
    device: Device,
) -> tuple[VerifyResult, ...]:
    results = []
    black_frame = np.zeros((device.led_count, 3), dtype=np.uint8)
    log('[verify] Press y if the demo works, n if it does not.')
    with single_key_polling_input(sys.stdin) as read_key:
        for demo in VERIFY_DEMOS:
            log_status(f'[verify] {demo.name}')
            first_frame = demo.frame_at(device, 0, 2)
            stream_fade(
                client,
                retry,
                host,
                device,
                black_frame,
                first_frame,
                VERIFY_FPS,
                VERIFY_SLOW_FADE_DURATION,
                f'{demo.name}-fade-in',
            )
            worked, last_frame = stream_demo_until_vote(
                client,
                retry,
                host,
                device,
                demo,
                read_key,
            )
            stream_fade(
                client,
                retry,
                host,
                device,
                last_frame,
                black_frame,
                VERIFY_FPS,
                VERIFY_SLOW_FADE_DURATION,
                f'{demo.name}-fade-out',
            )
            results.append(VerifyResult(demo.name, worked))
    return tuple(results)


def stream_demo_until_vote(
    client: TwinklyClient,
    retry: RetryConfig,
    host: str,
    device: Device,
    demo: VerifyDemo,
    read_key: Callable[[], str | None],
) -> tuple[bool, NDArray[np.uint8]]:
    frame_delay = 1 / VERIFY_FPS
    index = 0
    frame_count = round(VERIFY_FPS * VERIFY_DEMO_DURATION)
    last_frame = demo.frame_at(device, 0, frame_count)
    while True:
        frame_started_at = time.monotonic()
        last_frame = validate_byte_rgb_frame(
            device, demo.frame_at(device, index, frame_count)
        )
        sent = send_realtime_frame(client, retry, host, last_frame)
        if sent < last_frame.nbytes:
            log_error(
                '[unexpected] '
                f'{demo.name} sent {sent} bytes for {last_frame.nbytes} bytes '
                'of RGB data.'
            )
        if (answer := verify_answer(read_key())) is not None:
            return answer, last_frame
        remaining = frame_delay - (time.monotonic() - frame_started_at)
        if remaining > 0:
            time.sleep(remaining)
        index = (index + 1) % frame_count


def verify_answer(key: str | None) -> bool | None:
    if key == 'y':
        return True
    if key == 'n':
        return False
    return None


def report_verify_results(results: tuple[VerifyResult, ...]) -> None:
    worked = [i.name for i in results if i.worked is True]
    failed = [i.name for i in results if i.worked is False]
    shown = [i.name for i in results if i.worked is None]
    if worked:
        log_status('[verify] Worked: ' + ', '.join(worked))
    if failed:
        log_error('[verify] Did not work: ' + ', '.join(failed))
    if shown:
        log_status('[verify] Shown without pass/fail: ' + ', '.join(shown))


def log_verify_demos() -> None:
    log_status('[verify] Demos: ' + ', '.join(i.name for i in VERIFY_DEMOS))


def verify_primary_channels_frame(
    device: Device,
    index: int,
    frame_count: int,
) -> NDArray[np.uint8]:
    colors: tuple[RGB, ...] = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255))
    color = colors[(index * len(colors)) // frame_count % len(colors)]
    return solid_rgb_level_frame(device, color)


def verify_moving_gradient_frame(
    device: Device,
    index: int,
    frame_count: int,
) -> NDArray[np.uint8]:
    frame = gradient_frame(device.led_count, (255, 0, 80), (0, 160, 255))
    return np.roll(frame, round(index * device.led_count / frame_count), axis=0)


def verify_crossfade_frame(
    device: Device,
    index: int,
    frame_count: int,
) -> NDArray[np.uint8]:
    first_frame = gradient_frame(device.led_count, *LOW_CONTRAST_BLEND)
    second_frame = gradient_frame(device.led_count, *HIGH_CONTRAST_BLEND)
    cycle = math.sin((index / frame_count) * math.tau) * 0.5 + 0.5
    return blend_frames(first_frame, second_frame, cycle)


def verify_temporal_dither_frame(
    device: Device,
    index: int,
    frame_count: int,
) -> NDArray[np.uint8]:
    if frame_count < 2:
        raise ValueError('frame_count must be at least 2')
    half = max(2, frame_count // 2)
    if index < half:
        return temporal_dither_grayscale_frame(
            device,
            0,
            32,
            index,
            half,
            dispersed_pixel_order(device.led_count),
        )
    return temporal_dither_grayscale_frame(
        device,
        32,
        0,
        index - half,
        max(2, frame_count - half),
        dispersed_pixel_order(device.led_count),
    )


def solid_grayscale_frame(device: Device, level: int) -> NDArray[np.uint8]:
    if not 0 <= level <= 255:
        raise ValueError('level must be an 8-bit channel value')
    return np.full((device.led_count, 3), level, dtype=np.uint8)


def solid_rgb_level_frame(device: Device, level: RGB) -> NDArray[np.uint8]:
    if any(not 0 <= i <= 255 for i in level):
        raise ValueError('levels must be 8-bit channel values')
    return np.full((device.led_count, 3), level, dtype=np.uint8)


def adjust_black_floor_level(level: RGB, key: str) -> RGB:
    red, green, blue = level
    if key == 'r':
        red = min(255, red + 1)
    elif key == 'g':
        green = min(255, green + 1)
    elif key == 'b':
        blue = min(255, blue + 1)
    elif key == 'R':
        red = max(0, red - 1)
    elif key == 'G':
        green = max(0, green - 1)
    elif key == 'B':
        blue = max(0, blue - 1)
    elif key == UP_KEY:
        red = min(255, red + 1)
        green = min(255, green + 1)
        blue = min(255, blue + 1)
    elif key == DOWN_KEY:
        red = max(0, red - 1)
        green = max(0, green - 1)
        blue = max(0, blue - 1)
    return red, green, blue


def is_black_floor_key(key: str) -> bool:
    return key in {'r', 'g', 'b', 'R', 'G', 'B', UP_KEY, DOWN_KEY}


def run_interactive_black_floor(
    client: TwinklyClient,
    retry: RetryConfig,
    host: str,
    device: Device,
) -> None:
    log(
        '[black-floor] r/g/b increase, R/G/B decrease, arrows adjust all, Ctrl-C stops.'
    )
    with single_key_input(sys.stdin) as read_key:
        run_black_floor_keys(client, retry, host, device, read_key)


def run_black_floor_keys(
    client: TwinklyClient,
    retry: RetryConfig,
    host: str,
    device: Device,
    read_key: Callable[[], str],
) -> None:
    level = (0, 0, 0)
    send_black_floor_level(client, retry, host, device, level)
    while True:
        key = read_key()
        if is_black_floor_key(key):
            level = adjust_black_floor_level(level, key)
            send_black_floor_level(client, retry, host, device, level)


def send_black_floor_level(
    client: TwinklyClient,
    retry: RetryConfig,
    host: str,
    device: Device,
    level: RGB,
) -> None:
    frame = solid_rgb_level_frame(device, level)
    red, green, blue = level
    log_status(f'[black-floor] RGB {red} {green} {blue}')
    sent = send_realtime_frame(client, retry, host, frame)
    if sent < frame.nbytes:
        log_error(
            '[unexpected] '
            f'black floor RGB {red} {green} {blue} sent {sent} bytes for '
            f'{frame.nbytes} bytes of RGB data.'
        )


@contextmanager
def single_key_input(stream: TextIO) -> Iterator[Callable[[], str]]:
    fd = stream.fileno()
    settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield lambda: read_single_key(fd)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, settings)


@contextmanager
def single_key_polling_input(stream: TextIO) -> Iterator[Callable[[], str | None]]:
    fd = stream.fileno()
    settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield lambda: read_available_key(fd)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, settings)


def read_single_key(fd: int) -> str:
    key = os.read(fd, 1).decode()
    if key == '\x1b':
        key += os.read(fd, 2).decode()
    return key


def read_available_key(fd: int) -> str | None:
    ready, _, _ = select.select([fd], [], [], 0)
    if not ready:
        return None
    return read_single_key(fd)


def run_temporal_dither_comparison(
    client: TwinklyClient,
    retry: RetryConfig,
    host: str,
    device: Device,
    duration: float,
) -> None:
    black_frame = np.zeros((device.led_count, 3), dtype=np.uint8)
    white_frame = np.full((device.led_count, 3), 255, dtype=np.uint8)
    log_status(
        f'[test2] Linear fade at {TEST2_TRANSPORT_FPS:g} FPS for {duration:g} seconds'
    )
    report_fades(
        (
            stream_fade(
                client,
                retry,
                host,
                device,
                black_frame,
                white_frame,
                TEST2_TRANSPORT_FPS,
                duration,
                'normal-black-to-white',
            ),
            stream_fade(
                client,
                retry,
                host,
                device,
                white_frame,
                black_frame,
                TEST2_TRANSPORT_FPS,
                duration,
                'normal-white-to-black',
            ),
            stream_frames(
                client,
                retry,
                host,
                device,
                TEST2_TRANSPORT_FPS,
                1.0,
                'normal-black-hold',
                lambda _index, _frame_count: black_frame,
            ),
        )
    )
    log_status(
        f'[test2] {TEST2_ANIMATION_FPS:g} FPS animation with '
        f'{TEST2_TEMPORAL_FACTOR}x temporal dithering'
    )
    order = dispersed_pixel_order(device.led_count)
    report_fades(
        (
            stream_temporal_dither_fade(
                client,
                retry,
                host,
                device,
                0,
                255,
                TEST2_ANIMATION_FPS,
                TEST2_TEMPORAL_FACTOR,
                duration,
                'dithered-black-to-white',
                order,
            ),
            stream_temporal_dither_fade(
                client,
                retry,
                host,
                device,
                255,
                0,
                TEST2_ANIMATION_FPS,
                TEST2_TEMPORAL_FACTOR,
                duration,
                'dithered-white-to-black',
                order,
            ),
            stream_frames(
                client,
                retry,
                host,
                device,
                TEST2_TRANSPORT_FPS,
                1.0,
                'dithered-black-hold',
                lambda _index, _frame_count: black_frame,
            ),
        )
    )


def stream_fade(
    client: TwinklyClient,
    retry: RetryConfig,
    host: str,
    device: Device,
    first_frame: NDArray[np.uint8],
    second_frame: NDArray[np.uint8],
    fps: float,
    duration: float,
    phase: str,
) -> FadeReport:
    return stream_frames(
        client,
        retry,
        host,
        device,
        fps,
        duration,
        phase,
        lambda index, frame_count: blend_frames(
            first_frame,
            second_frame,
            index / (frame_count - 1),
        ),
    )


def stream_temporal_dither_fade(
    client: TwinklyClient,
    retry: RetryConfig,
    host: str,
    device: Device,
    start: int,
    end: int,
    animation_fps: float,
    temporal_factor: int,
    duration: float,
    phase: str,
    order: NDArray[np.int64],
) -> FadeReport:
    transport_fps = animation_fps * temporal_factor
    return stream_frames(
        client,
        retry,
        host,
        device,
        transport_fps,
        duration,
        phase,
        lambda index, frame_count: temporal_dither_grayscale_frame(
            device,
            start,
            end,
            index,
            frame_count,
            order,
        ),
    )


def stream_frames(
    client: TwinklyClient,
    retry: RetryConfig,
    host: str,
    device: Device,
    fps: float,
    duration: float,
    phase: str,
    frame_at: Callable[[int, int], NDArray[np.uint8]],
) -> FadeReport:
    frame_delay = 1 / fps
    frame_count = max(2, round(fps * duration))
    unique_frames: set[bytes] = set()
    late_frames = 0
    short_sends = 0
    max_late = 0.0
    started_at = time.monotonic()
    for index in range(frame_count):
        frame_started_at = time.monotonic()
        frame = validate_byte_rgb_frame(device, frame_at(index, frame_count))
        unique_frames.add(frame.tobytes())
        sent = send_realtime_frame(client, retry, host, frame)
        if sent < frame.nbytes:
            short_sends += 1
            log_error(
                '[unexpected] '
                f'{phase} at {fps:g} FPS frame {index + 1}/{frame_count} '
                f'sent {sent} bytes for {frame.nbytes} bytes of RGB data.'
            )
        remaining = frame_delay - (time.monotonic() - frame_started_at)
        if remaining > 0:
            time.sleep(remaining)
        else:
            late_frames += 1
            max_late = max(max_late, -remaining)
    return FadeReport(
        fps=fps,
        phase=phase,
        total_frames=frame_count,
        unique_frames=len(unique_frames),
        late_frames=late_frames,
        short_sends=short_sends,
        max_late_ms=max_late * 1000,
        elapsed_ms=(time.monotonic() - started_at) * 1000,
    )


def report_fades(reports: tuple[FadeReport, ...]) -> None:
    for report in reports:
        log_status(
            '[report] '
            f'{report.phase} {report.fps:g} FPS: '
            f'{report.unique_frames}/{report.total_frames} unique frames, '
            f'{report.duplicate_frames} duplicate frames'
        )
        if report.late_frames:
            log_error(
                '[unexpected] '
                f'{report.phase} {report.fps:g} FPS missed frame timing '
                f'{report.late_frames}/{report.total_frames} times; '
                f'worst overrun {report.max_late_ms:.2f} ms.'
            )
        if report.short_sends:
            log_error(
                '[unexpected] '
                f'{report.phase} {report.fps:g} FPS had '
                f'{report.short_sends} short UDP sends.'
            )


VERIFY_DEMOS: tuple[VerifyDemo, ...] = (
    # Add new demos at the start; new features are the most likely to break.
    VerifyDemo('primary-channels', verify_primary_channels_frame),
    VerifyDemo('moving-gradient', verify_moving_gradient_frame),
    VerifyDemo('crossfade', verify_crossfade_frame),
    VerifyDemo('temporal-dither', verify_temporal_dither_frame),
)
