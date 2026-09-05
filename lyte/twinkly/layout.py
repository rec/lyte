from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from reccy.runtime import logging

from .client import TwinklyClient
from .command import read_json_object, run_twinkly_command, write_json_file
from .diagnostic import DiagnosticConfig

LayoutAction = Literal['get', 'export', 'upload', 'delete']
LayoutSource = Literal['linear', '2d', '3d']
LedConfigAction = Literal['get', 'set']


LOGGER = logging.get_logger(__name__)


class LayoutCoordinate(BaseModel, frozen=True):
    x: float
    y: float
    z: float


class TwinklyLayout(BaseModel, frozen=True):
    aspectXY: int = 0
    aspectXZ: int = 0
    coordinates: list[LayoutCoordinate]
    source: LayoutSource
    synthesized: bool = False
    uuid: str | None = None

    @classmethod
    def from_response(cls, data: dict[str, object]) -> TwinklyLayout:
        return cls.model_validate(data)

    def request_body(self) -> dict[str, object]:
        data = self.model_dump(exclude_none=True)
        data['coordinates'] = [i.model_dump() for i in self.coordinates]
        return data


def run_layout_control(
    config: DiagnosticConfig,
    action: LayoutAction,
    path: Path | None,
) -> int:
    validate_layout_args(action, path)

    def run(client: TwinklyClient) -> None:
        if action == 'get':
            LOGGER.info(f'[layout] {client.get_layout_full().data}')
        elif action == 'export':
            assert path is not None
            write_json_file(path, client.get_layout_full().data)
            LOGGER.info(f'[layout] exported {path}')
        elif action == 'upload':
            assert path is not None
            layout = TwinklyLayout.from_response(read_json_object(path))
            client.set_layout_full(layout.request_body())
            LOGGER.info(f'[layout] uploaded {path}')
        else:
            client.delete_layout_full()
            LOGGER.info('[layout] deleted')

    return run_twinkly_command(config, run)


def run_led_config_control(
    config: DiagnosticConfig,
    action: LedConfigAction,
    path: Path | None,
) -> int:
    validate_led_config_args(action, path)

    def run(client: TwinklyClient) -> None:
        if action == 'get':
            LOGGER.info(f'[led-config] {client.get_led_config().data}')
        else:
            assert path is not None
            client.set_led_config(read_json_object(path))
            LOGGER.info(f'[led-config] set {path}')

    return run_twinkly_command(config, run)


def validate_layout_args(action: LayoutAction, path: Path | None) -> None:
    if action in ('get', 'delete') and path is not None:
        sys.exit(f'{action} does not accept a path')
    if action in ('export', 'upload') and path is None:
        sys.exit(f'{action} requires a path')


def validate_led_config_args(action: LedConfigAction, path: Path | None) -> None:
    if action == 'get' and path is not None:
        sys.exit('get does not accept a path')
    if action == 'set' and path is None:
        sys.exit('set requires a path')
