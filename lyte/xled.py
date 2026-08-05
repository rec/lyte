from __future__ import annotations

import sys
from collections.abc import Callable
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
LedMode = Literal['off', 'color', 'demo', 'effect', 'movie', 'playlist', 'rt']
ModeAction = Literal['get', 'set']
ColorAction = Literal['get', 'set']
EffectAction = Literal['list', 'current', 'set-current']


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

    def run(client: LyteClient) -> None:
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

    return run_xled_command(config, run)


def run_mode_control(
    config: DiagnosticConfig,
    action: ModeAction,
    mode: LedMode | None,
) -> int:
    validate_mode_args(action, mode)

    def run(client: LyteClient) -> None:
        if action == 'get':
            log_status(f'[mode] {client.get_led_mode().data}')
        else:
            assert mode is not None
            client.set_led_mode({'mode': mode})
            log_status(f'[mode] set {mode}')

    return run_xled_command(config, run)


def run_color_control(
    config: DiagnosticConfig,
    action: ColorAction,
    red: int | None,
    green: int | None,
    blue: int | None,
) -> int:
    validate_color_args(action, red, green, blue)

    def run(client: LyteClient) -> None:
        if action == 'get':
            log_status(f'[color] {client.get_led_color().data}')
        else:
            assert red is not None
            assert green is not None
            assert blue is not None
            body: dict[str, object] = {
                'mode': 'rgb',
                'red': red,
                'green': green,
                'blue': blue,
            }
            client.set_led_color(body)
            log_status(f'[color] set rgb {red} {green} {blue}')

    return run_xled_command(config, run)


def run_effect_control(
    config: DiagnosticConfig,
    action: EffectAction,
    effect_id: int | None,
) -> int:
    validate_effect_args(action, effect_id)

    def run(client: LyteClient) -> None:
        if action == 'list':
            log_status(f'[effects] {client.get_effects().data}')
        elif action == 'current':
            log_status(f'[effects] current {client.get_current_effect().data}')
        else:
            assert effect_id is not None
            client.set_current_effect({'effect_id': effect_id})
            log_status(f'[effects] set current {effect_id}')

    return run_xled_command(config, run)


def run_xled_command(
    config: DiagnosticConfig,
    action: Callable[[LyteClient], None],
) -> int:
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
        action(client)
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


def validate_mode_args(action: ModeAction, mode: LedMode | None) -> None:
    if action == 'get' and mode is not None:
        sys.exit('get does not accept a mode')
    if action == 'set' and mode is None:
        sys.exit('set requires a mode')


def validate_color_args(
    action: ColorAction,
    red: int | None,
    green: int | None,
    blue: int | None,
) -> None:
    values = (red, green, blue)
    if action == 'get' and any(i is not None for i in values):
        sys.exit('get does not accept color values')
    if action == 'set' and any(i is None for i in values):
        sys.exit('set requires red green blue')
    if any(i is not None and not 0 <= i <= 255 for i in values):
        sys.exit('color values must be between 0 and 255')


def validate_effect_args(action: EffectAction, effect_id: int | None) -> None:
    if action in ('list', 'current') and effect_id is not None:
        sys.exit(f'{action} does not accept an effect id')
    if action == 'set-current' and effect_id is None:
        sys.exit('set-current requires an effect id')
    if effect_id is not None and effect_id < 0:
        sys.exit('effect id must not be negative')


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
