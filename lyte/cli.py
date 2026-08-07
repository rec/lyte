from __future__ import annotations

# ruff: noqa: I001

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import tyro

from . import fps_test
from . import show
from .animate.config import AnimateConfig
from .animate.playback import run_animate
from .preview.command import PreviewConfig, run_preview
from .twinkly import diagnostic
from .twinkly import inputs
from .twinkly import layout
from .twinkly import media
from .twinkly import mode
from .twinkly import networking
from .twinkly import output
from .twinkly import timer


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
    action: Annotated[output.OutputControlAction, tyro.conf.Positional] = 'get'
    value: Annotated[int | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class SaturationConfig(DeviceCommandConfig):
    action: Annotated[output.OutputControlAction, tyro.conf.Positional] = 'get'
    value: Annotated[int | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class ModeConfig(DeviceCommandConfig):
    action: Annotated[mode.ModeAction, tyro.conf.Positional] = 'get'
    value: Annotated[mode.LedMode | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class ColorConfig(DeviceCommandConfig):
    action: Annotated[mode.ColorAction, tyro.conf.Positional] = 'get'
    red: Annotated[int | None, tyro.conf.Positional] = None
    green: Annotated[int | None, tyro.conf.Positional] = None
    blue: Annotated[int | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class EffectsConfig(DeviceCommandConfig):
    action: Annotated[mode.EffectAction, tyro.conf.Positional] = 'list'
    effect_id: Annotated[int | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class LayoutConfig(DeviceCommandConfig):
    action: Annotated[layout.LayoutAction, tyro.conf.Positional] = 'get'
    path: Annotated[Path | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class LedConfigConfig(DeviceCommandConfig):
    action: Annotated[layout.LedConfigAction, tyro.conf.Positional] = 'get'
    path: Annotated[Path | None, tyro.conf.Positional] = None


@dataclass(frozen=True)
class TimerConfig(DeviceCommandConfig):
    action: Annotated[timer.TimerAction, tyro.conf.Positional] = 'get'
    time_on: Annotated[int | None, tyro.conf.Positional] = None
    time_off: Annotated[int | None, tyro.conf.Positional] = None
    time_now: int | None = None


@dataclass(frozen=True)
class MovieConfig(DeviceCommandConfig):
    action: Annotated[media.MovieAction, tyro.conf.Positional] = 'list'


@dataclass(frozen=True)
class PlaylistConfig(DeviceCommandConfig):
    action: Annotated[media.PlaylistAction, tyro.conf.Positional] = 'list'


@dataclass(frozen=True)
class NetworkConfig(DeviceCommandConfig):
    action: Annotated[networking.NetworkAction, tyro.conf.Positional] = 'status'


@dataclass(frozen=True)
class MqttConfig(DeviceCommandConfig):
    action: Annotated[inputs.MqttAction, tyro.conf.Positional] = 'config'


@dataclass(frozen=True)
class MicConfig(DeviceCommandConfig):
    action: Annotated[inputs.MicAction, tyro.conf.Positional] = 'config'


@dataclass(frozen=True)
class MusicConfig(DeviceCommandConfig):
    action: Annotated[inputs.MusicAction, tyro.conf.Positional] = 'drivers'


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
            'show': show.ShowConfig,
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
        return output.run_output_control(
            config.diagnostic_config(), 'brightness', config.action, config.value
        )
    if isinstance(config, ColorConfig):
        return mode.run_color_control(
            config.diagnostic_config(),
            config.action,
            config.red,
            config.green,
            config.blue,
        )
    if isinstance(config, diagnostic.DiagnosticCommandConfig):
        return diagnostic.run_diagnostic_command(config)
    if isinstance(config, EffectsConfig):
        return mode.run_effect_control(
            config.diagnostic_config(), config.action, config.effect_id
        )
    if isinstance(config, fps_test.FpsTestConfig):
        return fps_test.run_fps_test(config)
    if isinstance(config, LayoutConfig):
        return layout.run_layout_control(
            config.diagnostic_config(), config.action, config.path
        )
    if isinstance(config, LedConfigConfig):
        return layout.run_led_config_control(
            config.diagnostic_config(), config.action, config.path
        )
    if isinstance(config, MicConfig):
        return inputs.run_mic_control(config.diagnostic_config(), config.action)
    if isinstance(config, ModeConfig):
        return mode.run_mode_control(
            config.diagnostic_config(), config.action, config.value
        )
    if isinstance(config, MovieConfig):
        return media.run_movie_control(config.diagnostic_config(), config.action)
    if isinstance(config, MqttConfig):
        return inputs.run_mqtt_control(config.diagnostic_config(), config.action)
    if isinstance(config, MusicConfig):
        return inputs.run_music_control(config.diagnostic_config(), config.action)
    if isinstance(config, NetworkConfig):
        return networking.run_network_control(config.diagnostic_config(), config.action)
    if isinstance(config, PlaylistConfig):
        return media.run_playlist_control(config.diagnostic_config(), config.action)
    if isinstance(config, PreviewConfig):
        return run_preview(config)
    if isinstance(config, show.ShowConfig):
        return show.run_show(config)
    if isinstance(config, SaturationConfig):
        return output.run_output_control(
            config.diagnostic_config(), 'saturation', config.action, config.value
        )
    if isinstance(config, fps_test.TemporalDitherTestConfig):
        return fps_test.run_temporal_dither_test(config)
    if isinstance(config, TimerConfig):
        return timer.run_timer_control(
            config.diagnostic_config(),
            config.action,
            config.time_on,
            config.time_off,
            config.time_now,
        )
    if isinstance(config, fps_test.VerifyConfig):
        return fps_test.run_verify_test(config)
    raise TypeError(f'unsupported command config {type(config).__name__}')
