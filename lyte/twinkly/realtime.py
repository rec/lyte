from __future__ import annotations

import sys
import time

import numpy as np
from numpy.typing import NDArray

from ..logging import log, log_error, log_status
from ..retry import RetryConfig
from ..runtime import (
    authenticate_device,
    read_device_led_count,
    send_authenticated_frame,
    set_device_realtime_mode,
)
from .client import LyteClient
from .discovery import discover
from .session import read_gestalt, set_mac_from_gestalt, set_off_mode_with_retry

DISCOVERY_ATTEMPT_TIMEOUT = 5.0


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


def turn_off_device(client: LyteClient, retry: RetryConfig, host: str) -> bool:
    log(f'[step] Reading device info from {host}')
    gestalt = read_gestalt(client, retry, f'HTTP device info read from {host}')
    if gestalt is None:
        sys.exit(f'Could not read device info from {host}.')
    set_mac_from_gestalt(client, gestalt)

    log('[step] Authenticating')
    token = authenticate_device(
        client,
        retry,
        f'login and verify with {host}',
    )
    if token is None:
        sys.exit(f'Could not authenticate with {host}.')
    log_status(f'[connected] Authenticated with {host}')

    log('[step] Switching device to off mode')
    response = set_off_mode_with_retry(
        client,
        retry,
        f'switch {host} to off mode',
    )
    if response is None:
        sys.exit(f'Could not switch {host} to off mode.')
    log(f'[ok] {host} is off')
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


def discover_host(timeout: float | None) -> str | None:
    log('[step] Discovering Twinkly devices')
    started_at = time.monotonic()
    attempts = 0
    while True:
        remaining = (
            None if timeout is None else timeout - (time.monotonic() - started_at)
        )
        if remaining is not None and remaining <= 0:
            log_error('[failed] No Twinkly discovery replies received.')
            log_error('Pass --host with the device IP address.')
            return None
        attempt_timeout = DISCOVERY_ATTEMPT_TIMEOUT
        if remaining is not None:
            attempt_timeout = min(attempt_timeout, remaining)
        attempts += 1
        devices = list(discover(timeout=attempt_timeout))
        if devices:
            if len(devices) > 1:
                log('[warn] Multiple devices found; using the first one.')
            device = devices[0]
            log_status(f'[connected] Found {device.device_id} at {device.ip_address}')
            return device.ip_address
        if timeout is None:
            log(f'[warn] No Twinkly discovery replies on attempt {attempts}; retrying.')
        else:
            log(f'[warn] No Twinkly discovery replies on attempt {attempts}.')
