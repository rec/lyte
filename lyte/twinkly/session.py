"""Common device setup helpers for Lyte scripts and applications."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray

from ..errors import AuthenticationError, ProtocolError
from ..retry import RetryConfig, retry_call
from .client import TWINKLY_API_PREFIX, AuthToken, TwinklyClient, TwinklyResponse
from .frame import send_frame_v3


def twinkly_request_label(method: str, path: str, host: str) -> str:
    return f'{method.upper()} {TWINKLY_API_PREFIX}/{path} on {host}'


def read_gestalt(
    client: TwinklyClient,
    retry: RetryConfig,
    label: str,
    deadline: float | None = None,
    stop_event: threading.Event | None = None,
) -> dict[str, object] | None:
    return retry_call(
        label,
        retry,
        lambda: _with_deadline(
            client, lambda: client.get('gestalt', authenticated=False).data, deadline
        ),
        (ProtocolError, TimeoutError),
        deadline,
        stop_event,
    )


def set_mac_from_gestalt(client: TwinklyClient, gestalt: dict[str, object]) -> bool:
    if isinstance(mac := gestalt.get('mac'), str):
        client.mac = mac
        return True
    return False


def led_count_from_gestalt(gestalt: dict[str, object]) -> int | None:
    if isinstance(led_count := gestalt.get('number_of_led'), int) and led_count > 0:
        return led_count
    return None


def authenticate_with_retry(
    client: TwinklyClient,
    retry: RetryConfig,
    label: str,
    deadline: float | None = None,
    stop_event: threading.Event | None = None,
) -> AuthToken | None:
    def authenticate_once() -> AuthToken:
        client.token = None
        return client.authenticate()

    return retry_call(
        label,
        retry,
        lambda: _with_deadline(client, authenticate_once, deadline),
        (AuthenticationError, ProtocolError, TimeoutError),
        deadline,
        stop_event,
    )


def set_realtime_mode_with_retry(
    client: TwinklyClient,
    retry: RetryConfig,
    label: str,
    deadline: float | None = None,
    stop_event: threading.Event | None = None,
) -> TwinklyResponse | None:
    return retry_call(
        label,
        retry,
        lambda: _with_deadline(client, client.set_realtime_mode, deadline),
        (AuthenticationError, ProtocolError, TimeoutError),
        deadline,
        stop_event,
    )


def set_off_mode_with_retry(
    client: TwinklyClient,
    retry: RetryConfig,
    label: str,
    deadline: float | None = None,
) -> TwinklyResponse | None:
    return retry_call(
        label,
        retry,
        lambda: _with_deadline(client, client.set_off_mode, deadline),
        (AuthenticationError, ProtocolError, TimeoutError),
        deadline,
    )


def turn_off_with_retry(
    client: TwinklyClient,
    retry: RetryConfig,
    host: str,
    deadline: float | None = None,
) -> bool:
    label = twinkly_request_label('POST', 'led/mode', host)
    if deadline is None:
        return set_off_mode_with_retry(client, retry, label) is not None
    return set_off_mode_with_retry(client, retry, label, deadline) is not None


def send_frame_with_retry(
    host: str,
    token: str,
    frame: NDArray[np.uint8],
    retry: RetryConfig,
    label: str,
) -> int | None:
    return retry_call(
        label,
        retry,
        lambda: send_frame_v3(host, token, frame),
        (OSError, ProtocolError, ValueError),
    )


def read_device_led_count(
    client: TwinklyClient,
    retry: RetryConfig,
    configured_led_count: int | None,
    label: str,
    deadline: float | None = None,
    stop_event: threading.Event | None = None,
) -> tuple[int | None, dict[str, object] | None]:
    gestalt = read_gestalt(client, retry, label, deadline, stop_event)
    if gestalt is None:
        return None, None
    set_mac_from_gestalt(client, gestalt)
    if configured_led_count is not None:
        return configured_led_count, gestalt
    return led_count_from_gestalt(gestalt), gestalt


def authenticate_device(
    client: TwinklyClient,
    retry: RetryConfig,
    label: str,
    deadline: float | None = None,
    stop_event: threading.Event | None = None,
) -> AuthToken | None:
    token = authenticate_with_retry(client, retry, label, deadline, stop_event)
    if token is None or client.token is None:
        return None
    return token


def set_device_realtime_mode(
    client: TwinklyClient,
    retry: RetryConfig,
    label: str,
    deadline: float | None = None,
    stop_event: threading.Event | None = None,
) -> TwinklyResponse | None:
    return set_realtime_mode_with_retry(client, retry, label, deadline, stop_event)


def send_authenticated_frame(
    client: TwinklyClient,
    host: str,
    frame: NDArray[np.uint8],
    retry: RetryConfig,
    label: str,
) -> int | None:
    if client.token is None:
        return None
    return send_frame_with_retry(host, client.token.value, frame, retry, label)


def _with_deadline[Result](
    client: TwinklyClient, operation: Callable[[], Result], deadline: float | None
) -> Result:
    if deadline is None:
        return operation()
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('operation deadline exceeded')
    timeout = client.timeout
    client.timeout = min(timeout, remaining)
    try:
        return operation()
    finally:
        client.timeout = timeout
