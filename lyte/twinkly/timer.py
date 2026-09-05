from __future__ import annotations

import sys
from typing import Literal

from pydantic import BaseModel, field_validator
from reccy.runtime import logging

from .client import TwinklyClient
from .command import run_twinkly_command
from .diagnostic import DiagnosticConfig

TimerAction = Literal['get', 'set']


LOGGER = logging.get_logger(__name__)


class TwinklyTimer(BaseModel, frozen=True):
    time_on: int
    time_off: int
    time_now: int | None = None

    @field_validator('time_on', 'time_off')
    @classmethod
    def check_timer_time(cls, value: int) -> int:
        if value != -1 and not 0 <= value < 86400:
            raise ValueError('timer time must be -1 or seconds after midnight')
        return value

    @field_validator('time_now')
    @classmethod
    def check_current_time(cls, value: int | None) -> int | None:
        if value is not None and not 0 <= value < 86400:
            raise ValueError('current time must be seconds after midnight')
        return value

    @classmethod
    def from_response(cls, data: dict[str, object]) -> TwinklyTimer:
        return cls.model_validate(data)

    def request_body(self) -> dict[str, object]:
        return self.model_dump(exclude_none=True)


def run_timer_control(
    config: DiagnosticConfig,
    action: TimerAction,
    time_on: int | None,
    time_off: int | None,
    time_now: int | None,
) -> int:
    validate_timer_args(action, time_on, time_off, time_now)

    def run(client: TwinklyClient) -> None:
        if action == 'get':
            timer = TwinklyTimer.from_response(client.get_timer().data)
            LOGGER.info(
                '[timer] '
                f'time_now={timer.time_now} '
                f'time_on={timer.time_on} '
                f'time_off={timer.time_off}'
            )
        else:
            assert time_on is not None
            assert time_off is not None
            timer = TwinklyTimer(time_on=time_on, time_off=time_off, time_now=time_now)
            client.set_timer(timer.request_body())
            LOGGER.info(
                '[timer] set '
                f'time_now={timer.time_now} '
                f'time_on={timer.time_on} '
                f'time_off={timer.time_off}'
            )

    return run_twinkly_command(config, run)


def validate_timer_args(
    action: TimerAction,
    time_on: int | None,
    time_off: int | None,
    time_now: int | None,
) -> None:
    if action == 'get':
        if time_on is not None or time_off is not None or time_now is not None:
            sys.exit('get does not accept timer values')
        return
    if time_on is None or time_off is None:
        sys.exit('set requires time-on and time-off')
    try:
        TwinklyTimer(time_on=time_on, time_off=time_off, time_now=time_now)
    except ValueError as err:
        sys.exit(str(err))
