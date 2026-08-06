"""Higher-level runtime helpers for Twinkly device scripts."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from .retry import RetryConfig
from .twinkly.client import AuthToken, LyteClient, LyteResponse
from .twinkly.session import (
    authenticate_with_retry,
    led_count_from_gestalt,
    read_gestalt,
    send_frame_with_retry,
    set_mac_from_gestalt,
    set_realtime_mode_with_retry,
)


def read_device_led_count(
    client: LyteClient,
    retry: RetryConfig,
    configured_led_count: int | None,
    label: str,
) -> tuple[int | None, dict[str, object] | None]:
    gestalt = read_gestalt(client, retry, label)
    if gestalt is None:
        return None, None
    set_mac_from_gestalt(client, gestalt)
    if configured_led_count is not None:
        return configured_led_count, gestalt
    return led_count_from_gestalt(gestalt), gestalt


def authenticate_device(
    client: LyteClient,
    retry: RetryConfig,
    label: str,
) -> AuthToken | None:
    token = authenticate_with_retry(client, retry, label)
    if token is None or client.token is None:
        return None
    return token


def set_device_realtime_mode(
    client: LyteClient,
    retry: RetryConfig,
    label: str,
) -> LyteResponse | None:
    return set_realtime_mode_with_retry(client, retry, label)


def send_authenticated_frame(
    client: LyteClient,
    host: str,
    frame: NDArray[np.uint8],
    retry: RetryConfig,
    label: str,
) -> int | None:
    if client.token is None:
        return None
    return send_frame_with_retry(host, client.token.value, frame, retry, label)
