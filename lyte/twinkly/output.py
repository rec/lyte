from __future__ import annotations

import sys
from typing import Literal

from pydantic import BaseModel, field_validator
from reccy.runtime import logging

from .client import TwinklyClient
from .command import run_twinkly_command
from .diagnostic import DiagnosticConfig

OutputControlKind = Literal['brightness', 'saturation']
OutputControlAction = Literal['get', 'set']
OutputControlMode = Literal['enabled', 'disabled']
OutputControlType = Literal['A', 'R']


LOGGER = logging.get_logger(__name__)


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

    def run(client: TwinklyClient) -> None:
        if action == 'get':
            control = read_output_control(client, kind)
            LOGGER.info(
                f'[{kind}] mode={control.mode} type={control.type} '
                f'value={control.value}'
            )
        else:
            assert value is not None
            control = OutputControl(value=value)
            write_output_control(client, kind, control)
            LOGGER.info(
                f'[{kind}] set mode={control.mode} type={control.type} '
                f'value={control.value}'
            )

    return run_twinkly_command(config, run)


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


def read_output_control(
    client: TwinklyClient,
    kind: OutputControlKind,
) -> OutputControl:
    if kind == 'brightness':
        return OutputControl.from_response(client.get_brightness().data)
    return OutputControl.from_response(client.get_saturation().data)


def write_output_control(
    client: TwinklyClient,
    kind: OutputControlKind,
    control: OutputControl,
) -> None:
    if kind == 'brightness':
        client.set_brightness(control.request_body())
    else:
        client.set_saturation(control.request_body())
