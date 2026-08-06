from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import tyro

from .animate import AnimateConfig, run_animate
from .diagnostic import (
    DiagnosticCommandConfig,
    DiagnosticConfig,
    run_diagnostic_command,
)
from .fps_test import (
    BlackFloorTestConfig,
    FpsTestConfig,
    TemporalDitherTestConfig,
    VerifyConfig,
    run_black_floor_test,
    run_fps_test,
    run_temporal_dither_test,
    run_verify_test,
)
from .preview_command import PreviewConfig, run_preview
from .xled import (
    ColorAction,
    EffectAction,
    LayoutAction,
    LedConfigAction,
    LedMode,
    MicAction,
    ModeAction,
    MovieAction,
    MqttAction,
    MusicAction,
    NetworkAction,
    OutputControlAction,
    PlaylistAction,
    TimerAction,
    run_color_control,
    run_effect_control,
    run_layout_control,
    run_led_config_control,
    run_mic_control,
    run_mode_control,
    run_movie_control,
    run_mqtt_control,
    run_music_control,
    run_network_control,
    run_output_control,
    run_playlist_control,
    run_timer_control,
)


@dataclass(frozen=True)
class DeviceCommandConfig:
    host: str | None = None
    timeout: float = 5.0
    discovery_timeout: float | None = None
    attempts: int = 10
    retry_delay: float = 0.5
    retry_backoff: float = 2.0

    def diagnostic_config(self) -> DiagnosticConfig:
        return DiagnosticConfig(
            host=self.host,
            timeout=self.timeout,
            discovery_timeout=self.discovery_timeout,
            attempts=self.attempts,
            retry_delay=self.retry_delay,
            retry_backoff=self.retry_backoff,
        )


@dataclass(frozen=True)
class BrightnessConfig(DeviceCommandConfig):
    action: Annotated[OutputControlAction, tyro.conf.Positional] = 'get'
    value: Annotated[int | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class SaturationConfig(DeviceCommandConfig):
    action: Annotated[OutputControlAction, tyro.conf.Positional] = 'get'
    value: Annotated[int | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class ModeConfig(DeviceCommandConfig):
    action: Annotated[ModeAction, tyro.conf.Positional] = 'get'
    value: Annotated[LedMode | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class ColorConfig(DeviceCommandConfig):
    action: Annotated[ColorAction, tyro.conf.Positional] = 'get'
    red: Annotated[int | None, tyro.conf.Positional] = None
    green: Annotated[int | None, tyro.conf.Positional] = None
    blue: Annotated[int | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class EffectsConfig(DeviceCommandConfig):
    action: Annotated[EffectAction, tyro.conf.Positional] = 'list'
    effect_id: Annotated[int | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class LayoutConfig(DeviceCommandConfig):
    action: Annotated[LayoutAction, tyro.conf.Positional] = 'get'
    path: Annotated[Path | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class LedConfigConfig(DeviceCommandConfig):
    action: Annotated[LedConfigAction, tyro.conf.Positional] = 'get'
    path: Annotated[Path | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class TimerConfig(DeviceCommandConfig):
    action: Annotated[TimerAction, tyro.conf.Positional] = 'get'
    time_on: Annotated[int | None, tyro.conf.Positional] = None
    time_off: Annotated[int | None, tyro.conf.Positional] = None
    time_now: int | None = None


@dataclass(frozen=True)
class MovieConfig(DeviceCommandConfig):
    action: Annotated[MovieAction, tyro.conf.Positional] = 'list'


@dataclass(frozen=True)
class PlaylistConfig(DeviceCommandConfig):
    action: Annotated[PlaylistAction, tyro.conf.Positional] = 'list'


@dataclass(frozen=True)
class NetworkConfig(DeviceCommandConfig):
    action: Annotated[NetworkAction, tyro.conf.Positional] = 'status'


@dataclass(frozen=True)
class MqttConfig(DeviceCommandConfig):
    action: Annotated[MqttAction, tyro.conf.Positional] = 'config'


@dataclass(frozen=True)
class MicConfig(DeviceCommandConfig):
    action: Annotated[MicAction, tyro.conf.Positional] = 'config'


@dataclass(frozen=True)
class MusicConfig(DeviceCommandConfig):
    action: Annotated[MusicAction, tyro.conf.Positional] = 'drivers'


def main(args: Sequence[str] | None = None) -> int:
    config = tyro.extras.subcommand_cli_from_dict(
        {
            'animate': AnimateConfig,
            'black-floor': BlackFloorTestConfig,
            'brightness': BrightnessConfig,
            'color': ColorConfig,
            'diagnostic': DiagnosticCommandConfig,
            'effects': EffectsConfig,
            'layout': LayoutConfig,
            'led-config': LedConfigConfig,
            'mic': MicConfig,
            'mode': ModeConfig,
            'movie': MovieConfig,
            'mqtt': MqttConfig,
            'music': MusicConfig,
            'network': NetworkConfig,
            'playlist': PlaylistConfig,
            'preview': PreviewConfig,
            'saturation': SaturationConfig,
            'test': FpsTestConfig,
            'test2': TemporalDitherTestConfig,
            'timer': TimerConfig,
            'verify': VerifyConfig,
        },
        prog='lyte',
        args=args,
    )
    return run_command(config)


def run_command(config: object) -> int:
    if isinstance(config, AnimateConfig):
        return run_animate(config)
    if isinstance(config, BlackFloorTestConfig):
        return run_black_floor_test(config)
    if isinstance(config, BrightnessConfig):
        return run_output_control(
            config.diagnostic_config(), 'brightness', config.action, config.value
        )
    if isinstance(config, ColorConfig):
        return run_color_control(
            config.diagnostic_config(),
            config.action,
            config.red,
            config.green,
            config.blue,
        )
    if isinstance(config, DiagnosticCommandConfig):
        return run_diagnostic_command(config)
    if isinstance(config, EffectsConfig):
        return run_effect_control(
            config.diagnostic_config(), config.action, config.effect_id
        )
    if isinstance(config, FpsTestConfig):
        return run_fps_test(config)
    if isinstance(config, LayoutConfig):
        return run_layout_control(
            config.diagnostic_config(), config.action, config.path
        )
    if isinstance(config, LedConfigConfig):
        return run_led_config_control(
            config.diagnostic_config(), config.action, config.path
        )
    if isinstance(config, MicConfig):
        return run_mic_control(config.diagnostic_config(), config.action)
    if isinstance(config, ModeConfig):
        return run_mode_control(config.diagnostic_config(), config.action, config.value)
    if isinstance(config, MovieConfig):
        return run_movie_control(config.diagnostic_config(), config.action)
    if isinstance(config, MqttConfig):
        return run_mqtt_control(config.diagnostic_config(), config.action)
    if isinstance(config, MusicConfig):
        return run_music_control(config.diagnostic_config(), config.action)
    if isinstance(config, NetworkConfig):
        return run_network_control(config.diagnostic_config(), config.action)
    if isinstance(config, PlaylistConfig):
        return run_playlist_control(config.diagnostic_config(), config.action)
    if isinstance(config, PreviewConfig):
        return run_preview(config)
    if isinstance(config, SaturationConfig):
        return run_output_control(
            config.diagnostic_config(), 'saturation', config.action, config.value
        )
    if isinstance(config, TemporalDitherTestConfig):
        return run_temporal_dither_test(config)
    if isinstance(config, TimerConfig):
        return run_timer_control(
            config.diagnostic_config(),
            config.action,
            config.time_on,
            config.time_off,
            config.time_now,
        )
    if isinstance(config, VerifyConfig):
        return run_verify_test(config)
    raise TypeError(f'unsupported command config {type(config).__name__}')
