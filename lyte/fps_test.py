from __future__ import annotations

import math
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .animation import Device, validate_frame
from .animations.bibliopixel import RGB
from .logging import log, log_error, log_status
from .network.client import LyteClient
from .network.discovery import discover
from .network.session import set_off_mode_with_retry
from .retry import RetryConfig
from .runtime import (
    authenticate_device,
    read_device_led_count,
    send_authenticated_frame,
    set_device_realtime_mode,
)

FPS_VALUES: tuple[float, ...] = (30.0, 60.0, 120.0, 240, 480, 960, 1920)
LOW_CONTRAST_BLEND: tuple[RGB, RGB] = ((255, 0, 80), (0, 160, 255))
HIGH_CONTRAST_BLEND: tuple[RGB, RGB] = ((0, 255, 120), (255, 240, 0))
TEST2_ANIMATION_FPS = 60.0
TEST2_TEMPORAL_FACTOR = 4
TEST2_TRANSPORT_FPS = TEST2_ANIMATION_FPS * TEST2_TEMPORAL_FACTOR


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
class FpsTestConfig:
    host: str | None = None
    timeout: float = 5.0
    discovery_timeout: float = 5.0
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
    discovery_timeout: float = 5.0
    attempts: int = 10
    retry_delay: float = 0.5
    retry_backoff: float = 2.0
    led_count: int | None = None
    time: float = 5.0


def run_fps_test(config: FpsTestConfig) -> int:
    validate_config(config)
    host = config.host or discover_host(config.discovery_timeout)
    if host is None:
        return 1

    retry = RetryConfig(
        attempts=config.attempts,
        delay=config.retry_delay,
        backoff=config.retry_backoff,
    )
    client = LyteClient(host=host, timeout=config.timeout)
    led_count = read_led_count(client, retry, config.led_count, host)
    if led_count is None:
        return 1
    device = Device(led_count=led_count)
    if not prepare_device(client, retry, host):
        return 1

    try:
        run_fades(client, retry, host, device, config.duration, config.pause)
    except KeyboardInterrupt:
        log()
        log('[ok] Stopped')
    finally:
        turn_off_streaming_device(client, retry, host)
    return 0


def run_temporal_dither_test(config: TemporalDitherTestConfig) -> int:
    validate_temporal_dither_config(config)
    host = config.host or discover_host(config.discovery_timeout)
    if host is None:
        return 1

    retry = RetryConfig(
        attempts=config.attempts,
        delay=config.retry_delay,
        backoff=config.retry_backoff,
    )
    client = LyteClient(host=host, timeout=config.timeout)
    led_count = read_led_count(client, retry, config.led_count, host)
    if led_count is None:
        return 1
    device = Device(led_count=led_count)
    if not prepare_device(client, retry, host):
        return 1

    try:
        run_temporal_dither_comparison(client, retry, host, device, config.time)
    except KeyboardInterrupt:
        log()
        log('[ok] Stopped')
    finally:
        turn_off_streaming_device(client, retry, host)
    return 0


def validate_config(config: FpsTestConfig) -> None:
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
    if config.attempts < 1:
        sys.exit('--attempts must be at least 1')
    if config.retry_delay < 0:
        sys.exit('--retry-delay must not be negative')
    if config.retry_backoff < 1:
        sys.exit('--retry-backoff must be at least 1')
    if config.time <= 0:
        sys.exit('--time must be greater than zero')


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
    client: LyteClient,
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


def run_temporal_dither_comparison(
    client: LyteClient,
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
    client: LyteClient,
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
    client: LyteClient,
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
    client: LyteClient,
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
        frame = validate_frame(device, frame_at(index, frame_count))
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


def send_realtime_frame(
    client: LyteClient,
    retry: RetryConfig,
    host: str,
    frame: NDArray[np.uint8],
) -> int:
    if client.token is None:
        sys.exit('Authentication token disappeared before frame send.')
    sent = send_authenticated_frame(
        client,
        host,
        frame,
        retry,
        f'UDP realtime frame send to {host}',
    )
    if sent is None:
        sys.exit(f'Could not send realtime frame to {host}.')
    return sent


def read_led_count(
    client: LyteClient,
    retry: RetryConfig,
    configured_led_count: int | None,
    host: str,
) -> int | None:
    log(f'[step] Reading device info from {host}')
    led_count, gestalt = read_device_led_count(
        client,
        retry,
        configured_led_count,
        f'HTTP device info read from {host}',
    )
    if gestalt is None:
        sys.exit(f'Could not read device info from {host}.')
    if configured_led_count is not None:
        log_status(f'[connected] {host}: using {configured_led_count} LEDs')
        return configured_led_count
    if led_count is None:
        sys.exit('Device did not report number_of_led; pass --led-count.')
    log_status(f'[connected] {host}: {led_count} LEDs')
    return led_count


def prepare_device(client: LyteClient, retry: RetryConfig, host: str) -> bool:
    log('[step] Authenticating')
    token = authenticate_device(
        client,
        retry,
        f'login and verify with {host}',
    )
    if token is None:
        sys.exit(f'Could not authenticate with {host}.')
    if client.token is None:
        sys.exit('Authentication succeeded without producing a token.')
    log_status(f'[connected] Authenticated with {host}')

    log('[step] Switching to realtime mode')
    response = set_device_realtime_mode(
        client,
        retry,
        f'switch {host} to realtime mode',
    )
    if response is None:
        sys.exit(f'Could not switch {host} to realtime mode.')
    log_status(f'[connected] {host} is in realtime mode')
    return True


def turn_off_streaming_device(
    client: LyteClient, retry: RetryConfig, host: str
) -> bool:
    log('[step] Switching device to off mode')
    response = set_off_mode_with_retry(
        client,
        retry,
        f'switch {host} to off mode',
    )
    if response is None:
        log_error(f'[failed] Could not switch {host} to off mode.')
        return False
    log(f'[ok] {host} is off')
    return True


def discover_host(timeout: float) -> str | None:
    log('[step] Discovering Twinkly devices')
    devices = list(discover(timeout=timeout))
    if not devices:
        log_error('[failed] No Twinkly discovery replies received.')
        log_error('Pass --host with the device IP address.')
        return None
    if len(devices) > 1:
        log('[warn] Multiple devices found; using the first one.')
    device = devices[0]
    log_status(f'[connected] Found {device.device_id} at {device.ip_address}')
    return device.ip_address
