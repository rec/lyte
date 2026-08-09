from __future__ import annotations

import enum
import time

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel

from ..logging import log, log_error, log_status
from ..retry import RetryConfig
from . import session
from .client import TwinklyClient
from .discovery import discover

DISCOVERY_ATTEMPT_TIMEOUT = 5.0


class PlaybackConnectionState(enum.StrEnum):
    CONNECTING = enum.auto()
    STREAMING = enum.auto()
    RECOVERING = enum.auto()
    BLACKED_OUT = enum.auto()
    UNKNOWN = enum.auto()


class PlaybackConnection(BaseModel):
    state: PlaybackConnectionState = PlaybackConnectionState.UNKNOWN
    blackout_requested: bool = True

    def set_state(self, state: PlaybackConnectionState) -> None:
        self.state = state
        log_status(f'[connection] {state}')

    def begin_recovery(self) -> None:
        self.blackout_requested = True
        self.set_state(PlaybackConnectionState.RECOVERING)

    def resume_streaming(self) -> None:
        self.blackout_requested = False
        self.set_state(PlaybackConnectionState.STREAMING)

    def finish_blackout(self, succeeded: bool) -> None:
        self.blackout_requested = True
        state = (
            PlaybackConnectionState.BLACKED_OUT
            if succeeded
            else PlaybackConnectionState.UNKNOWN
        )
        self.set_state(state)


class FrameSendStatus(enum.StrEnum):
    SENT = enum.auto()
    TOKEN_MISSING = enum.auto()
    TRANSPORT_FAILED = enum.auto()


class FrameSendResult(BaseModel, frozen=True):
    status: FrameSendStatus
    byte_count: int = 0


def send_realtime_frame(
    client: TwinklyClient,
    retry: RetryConfig,
    host: str,
    frame: NDArray[np.uint8],
) -> FrameSendResult:
    if client.token is None:
        return FrameSendResult(status=FrameSendStatus.TOKEN_MISSING)
    sent = session.send_authenticated_frame(
        client,
        host,
        frame,
        retry,
        f'UDP realtime frame send to {host}',
    )
    if sent is None:
        return FrameSendResult(status=FrameSendStatus.TRANSPORT_FAILED)
    return FrameSendResult(status=FrameSendStatus.SENT, byte_count=sent)


def read_led_count(
    client: TwinklyClient,
    retry: RetryConfig,
    configured_led_count: int | None,
    host: str,
) -> int | None:
    log(f'[step] Reading device info from {host}')
    led_count, gestalt = session.read_device_led_count(
        client,
        retry,
        configured_led_count,
        f'HTTP device info read from {host}',
    )
    if gestalt is None:
        log_error(f'[failed] Could not read device info from {host}.')
        return None
    if configured_led_count is not None:
        log_status(f'[connected] {host}: using {configured_led_count} LEDs')
        return configured_led_count
    if led_count is None:
        log_error('[failed] Device did not report number_of_led.')
        return None
    log_status(f'[connected] {host}: {led_count} LEDs')
    return led_count


def prepare_device(client: TwinklyClient, retry: RetryConfig, host: str) -> bool:
    log('[step] Authenticating')
    token = session.authenticate_device(
        client,
        retry,
        f'login and verify with {host}',
    )
    if token is None:
        log_error(f'[failed] Could not authenticate with {host}.')
        return False
    if client.token is None:
        log_error('[failed] Authentication succeeded without producing a token.')
        return False
    log_status(f'[connected] Authenticated with {host}')

    log('[step] Switching to realtime mode')
    response = session.set_device_realtime_mode(
        client,
        retry,
        f'switch {host} to realtime mode',
    )
    if response is None:
        log_error(f'[failed] Could not switch {host} to realtime mode.')
        return False
    log_status(f'[connected] {host} is in realtime mode')
    return True


def recover_streaming_device(
    client: TwinklyClient,
    retry: RetryConfig,
    configured_host: str | None,
    discovery_timeout: float | None,
    expected_led_count: int,
) -> str:
    while True:
        host = configured_host or discover_host(discovery_timeout)
        if host is None:
            time.sleep(retry.delay)
            continue
        client.host = host
        client.mac = None
        client.token = None
        led_count = read_led_count(client, retry, expected_led_count, host)
        if led_count == expected_led_count and prepare_device(client, retry, host):
            return host
        time.sleep(retry.delay)


def turn_off_device(client: TwinklyClient, retry: RetryConfig, host: str) -> bool:
    log(f'[step] Reading device info from {host}')
    gestalt = session.read_gestalt(client, retry, f'HTTP device info read from {host}')
    if gestalt is None:
        log_error(f'[failed] Could not read device info from {host}.')
        return False
    session.set_mac_from_gestalt(client, gestalt)

    log('[step] Authenticating')
    token = session.authenticate_device(
        client,
        retry,
        f'login and verify with {host}',
    )
    if token is None:
        log_error(f'[failed] Could not authenticate with {host}.')
        return False
    log_status(f'[connected] Authenticated with {host}')

    log('[step] Switching device to off mode')
    response = session.set_off_mode_with_retry(
        client,
        retry,
        f'switch {host} to off mode',
    )
    if response is None:
        log_error(f'[failed] Could not switch {host} to off mode.')
        return False
    log(f'[ok] {host} is off')
    return True


def turn_off_streaming_device(
    client: TwinklyClient, retry: RetryConfig, host: str
) -> bool:
    log('[step] Switching device to off mode')
    response = session.set_off_mode_with_retry(
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
