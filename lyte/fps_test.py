from __future__ import annotations

import sys
import time
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

FPS_VALUES: tuple[float, ...] = (20.0, 45.0, 60.0, 120.0)
LOW_CONTRAST_BLEND: tuple[RGB, RGB] = ((255, 0, 80), (0, 160, 255))
HIGH_CONTRAST_BLEND: tuple[RGB, RGB] = ((0, 255, 120), (255, 240, 0))


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
    pause: float = 0.5


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
        stream_fade(
            client, retry, host, device, black_frame, first_frame, fps, duration
        )
        stream_fade(
            client, retry, host, device, first_frame, second_frame, fps, duration
        )
        stream_fade(
            client, retry, host, device, second_frame, black_frame, fps, duration
        )
        if pause:
            time.sleep(pause)


def stream_fade(
    client: LyteClient,
    retry: RetryConfig,
    host: str,
    device: Device,
    first_frame: NDArray[np.uint8],
    second_frame: NDArray[np.uint8],
    fps: float,
    duration: float,
) -> None:
    frame_delay = 1 / fps
    frame_count = max(2, round(fps * duration))
    for index in range(frame_count):
        started_at = time.monotonic()
        progress = index / (frame_count - 1)
        frame = validate_frame(
            device, blend_frames(first_frame, second_frame, progress)
        )
        send_realtime_frame(client, retry, host, frame)
        remaining = frame_delay - (time.monotonic() - started_at)
        if remaining > 0:
            time.sleep(remaining)


def send_realtime_frame(
    client: LyteClient,
    retry: RetryConfig,
    host: str,
    frame: NDArray[np.uint8],
) -> None:
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
