from __future__ import annotations

import sys
from typing import Literal

from pydantic import BaseModel, field_validator

from .diagnostic import DiagnosticConfig
from .fps_test import discover_host
from .logging import log_status
from .network.client import LyteClient
from .network.session import (
    read_gestalt,
    set_mac_from_gestalt,
    turn_off_with_retry,
    xled_request_label,
)
from .retry import RetryConfig
from .runtime import authenticate_device

OutputControlKind = Literal['brightness', 'saturation']
OutputControlAction = Literal['get', 'set']
OutputControlMode = Literal['enabled', 'disabled']
OutputControlType = Literal['A', 'R']


class OutputControl(BaseModel, frozen=True):
    mode: OutputControlMode = 'enabled'
    type: OutputControlType = 'A'
    value: int

    @field_validator('value')
    @classmethod
    def check_value(cls, value: int) -> int:
        if not 0 <= value <= 100:
            raise ValueError('value must be between 0 and 100')
        return value

    @classmethod
    def from_response(cls, data: dict[str, object]) -> OutputControl:
        raw_value = data.get('value')
        if isinstance(raw_value, str):
            value = int(raw_value)
        elif isinstance(raw_value, int):
            value = raw_value
        else:
            raise ValueError('output control response did not include integer value')
        raw_mode = data.get('mode', 'enabled')
        if raw_mode == 'enabled':
            mode: OutputControlMode = 'enabled'
        elif raw_mode == 'disabled':
            mode = 'disabled'
        else:
            raise ValueError('output control response did not include valid mode')
        return cls(value=value, mode=mode)

    def request_body(self) -> dict[str, object]:
        return {'mode': self.mode, 'type': self.type, 'value': self.value}


def run_output_control(
    config: DiagnosticConfig,
    kind: OutputControlKind,
    action: OutputControlAction,
    value: int | None,
) -> int:
    validate_output_control_args(action, value)
    host = config.host or discover_host(config.discovery_timeout)
    if host is None:
        return 1

    retry = RetryConfig(
        attempts=config.attempts,
        delay=config.retry_delay,
        backoff=config.retry_backoff,
    )
    client = LyteClient(host=host, timeout=config.timeout)
    prepare_authenticated_client(client, retry, host)

    off_succeeded = True
    try:
        if action == 'get':
            control = read_output_control(client, kind)
            log_status(
                f'[{kind}] mode={control.mode} type={control.type} '
                f'value={control.value}'
            )
        else:
            assert value is not None
            control = OutputControl(value=value)
            write_output_control(client, kind, control)
            log_status(
                f'[{kind}] set mode={control.mode} type={control.type} '
                f'value={control.value}'
            )
    finally:
        off_succeeded = turn_off_with_retry(client, retry, host)
    return 0 if off_succeeded else 1


def validate_output_control_args(
    action: OutputControlAction,
    value: int | None,
) -> None:
    if action == 'get' and value is not None:
        sys.exit('get does not accept a value')
    if action == 'set' and value is None:
        sys.exit('set requires a value')
    if value is not None and not 0 <= value <= 100:
        sys.exit('value must be between 0 and 100')


def prepare_authenticated_client(
    client: LyteClient,
    retry: RetryConfig,
    host: str,
) -> None:
    gestalt = read_gestalt(client, retry, xled_request_label('GET', 'gestalt', host))
    if gestalt is None:
        sys.exit(f'Could not read device info from {host}.')
    set_mac_from_gestalt(client, gestalt)
    if authenticate_device(client, retry, xled_request_label('POST', 'login', host)):
        return
    sys.exit(f'Could not authenticate with {host}.')


def read_output_control(
    client: LyteClient,
    kind: OutputControlKind,
) -> OutputControl:
    if kind == 'brightness':
        return OutputControl.from_response(client.get_brightness().data)
    return OutputControl.from_response(client.get_saturation().data)


def write_output_control(
    client: LyteClient,
    kind: OutputControlKind,
    control: OutputControl,
) -> None:
    if kind == 'brightness':
        client.set_brightness(control.request_body())
    else:
        client.set_saturation(control.request_body())
