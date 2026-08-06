from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, field_validator

from ..logging import log_status
from ..retry import RetryConfig
from ..runtime import authenticate_device
from .client import LyteClient
from .diagnostic import DiagnosticConfig
from .realtime import discover_host
from .session import (
    read_gestalt,
    set_mac_from_gestalt,
    turn_off_with_retry,
    twinkly_request_label,
)

OutputControlKind = Literal['brightness', 'saturation']
OutputControlAction = Literal['get', 'set']
OutputControlMode = Literal['enabled', 'disabled']
OutputControlType = Literal['A', 'R']
LedMode = Literal['off', 'color', 'demo', 'effect', 'movie', 'playlist', 'rt']
ModeAction = Literal['get', 'set']
ColorAction = Literal['get', 'set']
EffectAction = Literal['list', 'current', 'set-current']
LayoutAction = Literal['get', 'export', 'upload', 'delete']
LayoutSource = Literal['linear', '2d', '3d']
LedConfigAction = Literal['get', 'set']
TimerAction = Literal['get', 'set']
MovieAction = Literal['config', 'list', 'current']
PlaylistAction = Literal['list', 'current']
NetworkAction = Literal['status', 'scan', 'scan-results']
MqttAction = Literal['config']
MicAction = Literal['config', 'sample']
MusicAction = Literal['drivers', 'driver-sets', 'current-driver-set']


class LayoutCoordinate(BaseModel, frozen=True):
    x: float
    y: float
    z: float


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

    return run_twinkly_command(config, run)


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

    return run_twinkly_command(config, run)


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

    return run_twinkly_command(config, run)


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

    return run_twinkly_command(config, run)


def run_layout_control(
    config: DiagnosticConfig,
    action: LayoutAction,
    path: Path | None,
) -> int:
    validate_layout_args(action, path)

    def run(client: LyteClient) -> None:
        if action == 'get':
            log_status(f'[layout] {client.get_layout_full().data}')
        elif action == 'export':
            assert path is not None
            write_json_file(path, client.get_layout_full().data)
            log_status(f'[layout] exported {path}')
        elif action == 'upload':
            assert path is not None
            layout = TwinklyLayout.from_response(read_json_object(path))
            client.set_layout_full(layout.request_body())
            log_status(f'[layout] uploaded {path}')
        else:
            client.delete_layout_full()
            log_status('[layout] deleted')

    return run_twinkly_command(config, run)


def run_led_config_control(
    config: DiagnosticConfig,
    action: LedConfigAction,
    path: Path | None,
) -> int:
    validate_led_config_args(action, path)

    def run(client: LyteClient) -> None:
        if action == 'get':
            log_status(f'[led-config] {client.get_led_config().data}')
        else:
            assert path is not None
            client.set_led_config(read_json_object(path))
            log_status(f'[led-config] set {path}')

    return run_twinkly_command(config, run)


def run_timer_control(
    config: DiagnosticConfig,
    action: TimerAction,
    time_on: int | None,
    time_off: int | None,
    time_now: int | None,
) -> int:
    validate_timer_args(action, time_on, time_off, time_now)

    def run(client: LyteClient) -> None:
        if action == 'get':
            timer = TwinklyTimer.from_response(client.get_timer().data)
            log_status(
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
            log_status(
                '[timer] set '
                f'time_now={timer.time_now} '
                f'time_on={timer.time_on} '
                f'time_off={timer.time_off}'
            )

    return run_twinkly_command(config, run)


def run_movie_control(config: DiagnosticConfig, action: MovieAction) -> int:
    def run(client: LyteClient) -> None:
        if action == 'config':
            log_status(f'[movie] config {client.get_movie_config().data}')
        elif action == 'list':
            log_status(f'[movie] list {client.get_movies().data}')
        else:
            log_status(f'[movie] current {client.get_current_movie().data}')

    return run_twinkly_command(config, run)


def run_playlist_control(config: DiagnosticConfig, action: PlaylistAction) -> int:
    def run(client: LyteClient) -> None:
        if action == 'list':
            log_status(f'[playlist] list {client.get_playlist().data}')
        else:
            log_status(f'[playlist] current {client.get_current_playlist_entry().data}')

    return run_twinkly_command(config, run)


def run_network_control(config: DiagnosticConfig, action: NetworkAction) -> int:
    def run(client: LyteClient) -> None:
        if action == 'status':
            log_status(f'[network] status {client.get_network_status().data}')
        elif action == 'scan':
            log_status(f'[network] scan {client.get_network_scan().data}')
        else:
            log_status(
                f'[network] scan-results {client.get_network_scan_results().data}'
            )

    return run_twinkly_command(config, run)


def run_mqtt_control(config: DiagnosticConfig, action: MqttAction) -> int:
    def run(client: LyteClient) -> None:
        if action == 'config':
            log_status(f'[mqtt] config {client.get_mqtt_config().data}')

    return run_twinkly_command(config, run)


def run_mic_control(config: DiagnosticConfig, action: MicAction) -> int:
    def run(client: LyteClient) -> None:
        if action == 'config':
            log_status(f'[mic] config {client.get_mic_config().data}')
        else:
            log_status(f'[mic] sample {client.get_mic_sample().data}')

    return run_twinkly_command(config, run)


def run_music_control(config: DiagnosticConfig, action: MusicAction) -> int:
    def run(client: LyteClient) -> None:
        if action == 'drivers':
            log_status(f'[music] drivers {client.get_music_drivers().data}')
        elif action == 'driver-sets':
            log_status(f'[music] driver-sets {client.get_music_driver_sets().data}')
        else:
            log_status(
                f'[music] current-driver-set '
                f'{client.get_current_music_driver_set().data}'
            )

    return run_twinkly_command(config, run)


def run_twinkly_command(
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


def read_json_object(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        sys.exit(f'{path} must contain a JSON object')
    return data


def write_json_file(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def prepare_authenticated_client(
    client: LyteClient,
    retry: RetryConfig,
    host: str,
) -> None:
    gestalt = read_gestalt(client, retry, twinkly_request_label('GET', 'gestalt', host))
    if gestalt is None:
        sys.exit(f'Could not read device info from {host}.')
    set_mac_from_gestalt(client, gestalt)
    if authenticate_device(client, retry, twinkly_request_label('POST', 'login', host)):
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
