from __future__ import annotations

import sys
from typing import Literal

from reccy import logging

from .client import TwinklyClient
from .command import run_twinkly_command
from .diagnostic import DiagnosticConfig

LedMode = Literal['off', 'color', 'demo', 'effect', 'movie', 'playlist', 'rt']
ModeAction = Literal['get', 'set']
ColorAction = Literal['get', 'set']
EffectAction = Literal['list', 'current', 'set-current']


LOGGER = logging.get_logger(__name__)


def run_mode_control(
    config: DiagnosticConfig,
    action: ModeAction,
    mode: LedMode | None,
) -> int:
    validate_mode_args(action, mode)

    def run(client: TwinklyClient) -> None:
        if action == 'get':
            LOGGER.info(f'[mode] {client.get_led_mode().data}')
        else:
            assert mode is not None
            client.set_led_mode({'mode': mode})
            LOGGER.info(f'[mode] set {mode}')

    return run_twinkly_command(config, run)


def run_color_control(
    config: DiagnosticConfig,
    action: ColorAction,
    red: int | None,
    green: int | None,
    blue: int | None,
) -> int:
    validate_color_args(action, red, green, blue)

    def run(client: TwinklyClient) -> None:
        if action == 'get':
            LOGGER.info(f'[color] {client.get_led_color().data}')
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
            LOGGER.info(f'[color] set rgb {red} {green} {blue}')

    return run_twinkly_command(config, run)


def run_effect_control(
    config: DiagnosticConfig,
    action: EffectAction,
    effect_id: int | None,
) -> int:
    validate_effect_args(action, effect_id)

    def run(client: TwinklyClient) -> None:
        if action == 'list':
            LOGGER.info(f'[effects] {client.get_effects().data}')
        elif action == 'current':
            LOGGER.info(f'[effects] current {client.get_current_effect().data}')
        else:
            assert effect_id is not None
            client.set_current_effect({'effect_id': effect_id})
            LOGGER.info(f'[effects] set current {effect_id}')

    return run_twinkly_command(config, run)


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
