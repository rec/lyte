from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import tyro

from . import fps_test, twinkly
from .animate import AnimateConfig, run_animate
from .preview.command import PreviewConfig, run_preview
from .twinkly import diagnostic


@dataclass(frozen=True)
class DeviceCommandConfig:
    host: str | None = None
    timeout: float = 5.0
    discovery_timeout: float | None = None
    attempts: int = 10
    retry_delay: float = 0.5
    retry_backoff: float = 2.0

    def diagnostic_config(self) -> diagnostic.DiagnosticConfig:
        return diagnostic.DiagnosticConfig(
            host=self.host,
            timeout=self.timeout,
            discovery_timeout=self.discovery_timeout,
            attempts=self.attempts,
            retry_delay=self.retry_delay,
            retry_backoff=self.retry_backoff,
        )


@dataclass(frozen=True)
class BrightnessConfig(DeviceCommandConfig):
    action: Annotated[twinkly.OutputControlAction, tyro.conf.Positional] = 'get'
    value: Annotated[int | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class SaturationConfig(DeviceCommandConfig):
    action: Annotated[twinkly.OutputControlAction, tyro.conf.Positional] = 'get'
    value: Annotated[int | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class ModeConfig(DeviceCommandConfig):
    action: Annotated[twinkly.ModeAction, tyro.conf.Positional] = 'get'
    value: Annotated[twinkly.LedMode | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class ColorConfig(DeviceCommandConfig):
    action: Annotated[twinkly.ColorAction, tyro.conf.Positional] = 'get'
    red: Annotated[int | None, tyro.conf.Positional] = None
    green: Annotated[int | None, tyro.conf.Positional] = None
    blue: Annotated[int | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class EffectsConfig(DeviceCommandConfig):
    action: Annotated[twinkly.EffectAction, tyro.conf.Positional] = 'list'
    effect_id: Annotated[int | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class LayoutConfig(DeviceCommandConfig):
    action: Annotated[twinkly.LayoutAction, tyro.conf.Positional] = 'get'
    path: Annotated[Path | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class LedConfigConfig(DeviceCommandConfig):
    action: Annotated[twinkly.LedConfigAction, tyro.conf.Positional] = 'get'
    path: Annotated[Path | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class TimerConfig(DeviceCommandConfig):
    action: Annotated[twinkly.TimerAction, tyro.conf.Positional] = 'get'
    time_on: Annotated[int | None, tyro.conf.Positional] = None
    time_off: Annotated[int | None, tyro.conf.Positional] = None
    time_now: int | None = None


@dataclass(frozen=True)
class MovieConfig(DeviceCommandConfig):
    action: Annotated[twinkly.MovieAction, tyro.conf.Positional] = 'list'


@dataclass(frozen=True)
class PlaylistConfig(DeviceCommandConfig):
    action: Annotated[twinkly.PlaylistAction, tyro.conf.Positional] = 'list'


@dataclass(frozen=True)
class NetworkConfig(DeviceCommandConfig):
    action: Annotated[twinkly.NetworkAction, tyro.conf.Positional] = 'status'


@dataclass(frozen=True)
class MqttConfig(DeviceCommandConfig):
    action: Annotated[twinkly.MqttAction, tyro.conf.Positional] = 'config'


@dataclass(frozen=True)
class MicConfig(DeviceCommandConfig):
    action: Annotated[twinkly.MicAction, tyro.conf.Positional] = 'config'


@dataclass(frozen=True)
class MusicConfig(DeviceCommandConfig):
    action: Annotated[twinkly.MusicAction, tyro.conf.Positional] = 'drivers'


def main(args: Sequence[str] | None = None) -> int:
    config = tyro.extras.subcommand_cli_from_dict(
        {
            'animate': AnimateConfig,
            'black-floor': fps_test.BlackFloorTestConfig,
            'brightness': BrightnessConfig,
            'color': ColorConfig,
            'diagnostic': diagnostic.DiagnosticCommandConfig,
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
            'test': fps_test.FpsTestConfig,
            'test2': fps_test.TemporalDitherTestConfig,
            'timer': TimerConfig,
            'verify': fps_test.VerifyConfig,
        },
        prog='lyte',
        args=args,
    )
    return run_command(config)


def run_command(config: object) -> int:
    if isinstance(config, AnimateConfig):
        return run_animate(config)
    if isinstance(config, fps_test.BlackFloorTestConfig):
        return fps_test.run_black_floor_test(config)
    if isinstance(config, BrightnessConfig):
        return twinkly.run_output_control(
            config.diagnostic_config(), 'brightness', config.action, config.value
        )
    if isinstance(config, ColorConfig):
        return twinkly.run_color_control(
            config.diagnostic_config(),
            config.action,
            config.red,
            config.green,
            config.blue,
        )
    if isinstance(config, diagnostic.DiagnosticCommandConfig):
        return diagnostic.run_diagnostic_command(config)
    if isinstance(config, EffectsConfig):
        return twinkly.run_effect_control(
            config.diagnostic_config(), config.action, config.effect_id
        )
    if isinstance(config, fps_test.FpsTestConfig):
        return fps_test.run_fps_test(config)
    if isinstance(config, LayoutConfig):
        return twinkly.run_layout_control(
            config.diagnostic_config(), config.action, config.path
        )
    if isinstance(config, LedConfigConfig):
        return twinkly.run_led_config_control(
            config.diagnostic_config(), config.action, config.path
        )
    if isinstance(config, MicConfig):
        return twinkly.run_mic_control(config.diagnostic_config(), config.action)
    if isinstance(config, ModeConfig):
        return twinkly.run_mode_control(
            config.diagnostic_config(), config.action, config.value
        )
    if isinstance(config, MovieConfig):
        return twinkly.run_movie_control(config.diagnostic_config(), config.action)
    if isinstance(config, MqttConfig):
        return twinkly.run_mqtt_control(config.diagnostic_config(), config.action)
    if isinstance(config, MusicConfig):
        return twinkly.run_music_control(config.diagnostic_config(), config.action)
    if isinstance(config, NetworkConfig):
        return twinkly.run_network_control(config.diagnostic_config(), config.action)
    if isinstance(config, PlaylistConfig):
        return twinkly.run_playlist_control(config.diagnostic_config(), config.action)
    if isinstance(config, PreviewConfig):
        return run_preview(config)
    if isinstance(config, SaturationConfig):
        return twinkly.run_output_control(
            config.diagnostic_config(), 'saturation', config.action, config.value
        )
    if isinstance(config, fps_test.TemporalDitherTestConfig):
        return fps_test.run_temporal_dither_test(config)
    if isinstance(config, TimerConfig):
        return twinkly.run_timer_control(
            config.diagnostic_config(),
            config.action,
            config.time_on,
            config.time_off,
            config.time_now,
        )
    if isinstance(config, fps_test.VerifyConfig):
        return fps_test.run_verify_test(config)
    raise TypeError(f'unsupported command config {type(config).__name__}')
