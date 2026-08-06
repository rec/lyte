"""Common device setup helpers for Lyte scripts and applications."""

from __future__ import annotations

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
) -> dict[str, object] | None:
    return retry_call(
        label,
        retry,
        lambda: client.get('gestalt', authenticated=False).data,
        (ProtocolError,),
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
) -> AuthToken | None:
    def authenticate_once() -> AuthToken:
        client.token = None
        return client.authenticate()

    return retry_call(
        label,
        retry,
        authenticate_once,
        (AuthenticationError, ProtocolError),
    )


def set_realtime_mode_with_retry(
    client: TwinklyClient,
    retry: RetryConfig,
    label: str,
) -> TwinklyResponse | None:
    return retry_call(
        label,
        retry,
        client.set_realtime_mode,
        (AuthenticationError, ProtocolError),
    )


def set_off_mode_with_retry(
    client: TwinklyClient,
    retry: RetryConfig,
    label: str,
) -> TwinklyResponse | None:
    return retry_call(
        label,
        retry,
        client.set_off_mode,
        (AuthenticationError, ProtocolError),
    )


def turn_off_with_retry(client: TwinklyClient, retry: RetryConfig, host: str) -> bool:
    return (
        set_off_mode_with_retry(
            client,
            retry,
            twinkly_request_label('POST', 'led/mode', host),
        )
        is not None
    )


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
