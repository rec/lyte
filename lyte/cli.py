from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal

import tyro

from .animate import AnimateConfig, AnimationName, run_animate
from .diagnostic import DiagnosticConfig, run_diagnostic
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
from .preview_command import (
    PreviewAnimationName,
    PreviewConfig,
    print_preview_patterns,
    run_preview,
)
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


def main(args: Sequence[str] | None = None) -> int:
    return tyro.extras.subcommand_cli_from_dict(
        {
            'animate': animate,
            'black-floor': black_floor,
            'brightness': brightness,
            'color': color,
            'diagnostic': diagnostic,
            'effects': effects,
            'layout': layout,
            'led-config': led_config,
            'mic': mic,
            'mode': mode,
            'movie': movie,
            'mqtt': mqtt,
            'music': music,
            'network': network,
            'playlist': playlist,
            'preview': preview,
            'saturation': saturation,
            'test': test,
            'test2': test2,
            'timer': timer,
            'verify': verify,
        },
        prog='lyte',
        args=args,
    )


def animate(
    animation: Annotated[AnimationName, tyro.conf.Positional] = 'random',
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float = 5.0,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
    led_count: int | None = None,
    speed: float = 25,
    fps: float = 20,
    duration: float | None = None,
    pre_fill: bool = False,
    center_in: bool = False,
    individual_pixel: bool = False,
    step: int = 1,
    start: int = 0,
    end: int | None = None,
    width: int = 1,
    count: int = 1,
    tail: int = 2,
    chance: int = 30,
    min_speed: int = 1,
    max_speed: int = 5,
    total_pixels: int = 1,
    fade_delay: int = 1,
    density: int = 20,
    max_bright: int = 255,
    cycles: int = 2,
    level_step: int = 5,
    rainbow_inc: int = 4,
    max_led: int | None = None,
    reverse: bool = False,
    n: int = 32,
    order: str = 'rgb',
    inverted: str = '',
    variance: float = 1,
    bounds: tuple[float, float] = (0, 180),
    color: tuple[int, int, int] | None = None,
    color2: tuple[int, int, int] | None = None,
    colors: tuple[int, ...] | None = None,
    period: float = 0,
    seed: int | None = None,
) -> int:
    """Run a selected animation on Twinkly lights."""
    return run_animate(
        AnimateConfig(
            animation=animation,
            host=host,
            timeout=timeout,
            discovery_timeout=discovery_timeout,
            attempts=attempts,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
            led_count=led_count,
            speed=speed,
            fps=fps,
            duration=duration,
            pre_fill=pre_fill,
            center_in=center_in,
            individual_pixel=individual_pixel,
            step=step,
            start=start,
            end=end,
            width=width,
            count=count,
            tail=tail,
            chance=chance,
            min_speed=min_speed,
            max_speed=max_speed,
            total_pixels=total_pixels,
            fade_delay=fade_delay,
            density=density,
            max_bright=max_bright,
            cycles=cycles,
            level_step=level_step,
            rainbow_inc=rainbow_inc,
            max_led=max_led,
            reverse=reverse,
            n=n,
            order=order,
            inverted=inverted,
            variance=variance,
            bounds=bounds,
            color=color,
            color2=color2,
            colors=colors,
            period=period,
            seed=seed,
        )
    )


def test(
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float | None = None,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
    led_count: int | None = None,
    duration: float = 2.0,
    pause: float = 0.5,
) -> int:
    """Show contrasting blend fades at several FPS values."""
    return run_fps_test(
        FpsTestConfig(
            host=host,
            timeout=timeout,
            discovery_timeout=discovery_timeout,
            attempts=attempts,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
            led_count=led_count,
            duration=duration,
            pause=pause,
        )
    )


def preview(
    animation: Annotated[PreviewAnimationName | None, tyro.conf.Positional] = None,
    output: Annotated[Path | None, tyro.conf.Positional] = None,
    open: bool = False,
    name: str | None = None,
    width: int = 16,
    height: int = 16,
    spacing: float = 1.0,
    led_size: float = 1.0,
    fps: float = 20,
    duration: float = 10,
    speed: float = 25,
    pre_fill: bool = False,
    center_in: bool = False,
    individual_pixel: bool = False,
    step: int = 1,
    start: int = 0,
    end: int | None = None,
    count: int = 1,
    tail: int = 2,
    chance: int = 30,
    min_speed: int = 1,
    max_speed: int = 5,
    total_pixels: int = 1,
    fade_delay: int = 1,
    density: int = 20,
    max_bright: int = 255,
    cycles: int = 2,
    level_step: int = 5,
    rainbow_inc: int = 4,
    max_led: int | None = None,
    reverse: bool = False,
    n: int = 32,
    order: str = 'rgb',
    inverted: str = '',
    variance: float = 1,
    bounds: tuple[float, float] = (0, 180),
    color: tuple[int, int, int] | None = None,
    color2: tuple[int, int, int] | None = None,
    colors: tuple[int, ...] | None = None,
    period: float = 0,
    seed: int | None = None,
) -> int:
    """Render a selected animation to a standalone HTML preview."""
    if animation is None and output is None:
        print_preview_patterns()
        return 0
    if animation is None or output is None:
        raise SystemExit('preview requires both animation and output')
    return run_preview(
        PreviewConfig(
            animation=animation,
            output=output,
            open=open,
            name=name,
            width=width,
            height=height,
            spacing=spacing,
            led_size=led_size,
            fps=fps,
            duration=duration,
            speed=speed,
            pre_fill=pre_fill,
            center_in=center_in,
            individual_pixel=individual_pixel,
            step=step,
            start=start,
            end=end,
            count=count,
            tail=tail,
            chance=chance,
            min_speed=min_speed,
            max_speed=max_speed,
            total_pixels=total_pixels,
            fade_delay=fade_delay,
            density=density,
            max_bright=max_bright,
            cycles=cycles,
            level_step=level_step,
            rainbow_inc=rainbow_inc,
            max_led=max_led,
            reverse=reverse,
            n=n,
            order=order,
            inverted=inverted,
            variance=variance,
            bounds=bounds,
            color=color,
            color2=color2,
            colors=colors,
            period=period,
            seed=seed,
        )
    )


def test2(
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float | None = None,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
    led_count: int | None = None,
    time: float = 5.0,
) -> int:
    """Compare direct 240 FPS fades with 60 FPS fades using 4x temporal dithering."""
    return run_temporal_dither_test(
        TemporalDitherTestConfig(
            host=host,
            timeout=timeout,
            discovery_timeout=discovery_timeout,
            attempts=attempts,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
            led_count=led_count,
            time=time,
        )
    )


def black_floor(
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float | None = None,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
    led_count: int | None = None,
) -> int:
    """Adjust low RGB levels interactively to find the visible black floor."""
    return run_black_floor_test(
        BlackFloorTestConfig(
            host=host,
            timeout=timeout,
            discovery_timeout=discovery_timeout,
            attempts=attempts,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
            led_count=led_count,
        )
    )


def verify(
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float | None = None,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
    led_count: int | None = None,
    mode: Literal['fast', 'slow'] = 'fast',
) -> int:
    """Show visual demos for the implemented realtime features."""
    return run_verify_test(
        VerifyConfig(
            host=host,
            timeout=timeout,
            discovery_timeout=discovery_timeout,
            attempts=attempts,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
            led_count=led_count,
            mode=mode,
        )
    )


def diagnostic(
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float | None = None,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
) -> int:
    """Report Twinkly XLED device state and endpoint support."""
    return run_diagnostic(
        DiagnosticConfig(
            host=host,
            timeout=timeout,
            discovery_timeout=discovery_timeout,
            attempts=attempts,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
        )
    )


def brightness(
    action: Annotated[OutputControlAction, tyro.conf.Positional] = 'get',
    value: Annotated[int | None, tyro.conf.Positional] = None,
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float | None = None,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
) -> int:
    """Get or set Twinkly app brightness."""
    return run_output_control(
        DiagnosticConfig(
            host=host,
            timeout=timeout,
            discovery_timeout=discovery_timeout,
            attempts=attempts,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
        ),
        'brightness',
        action,
        value,
    )


def saturation(
    action: Annotated[OutputControlAction, tyro.conf.Positional] = 'get',
    value: Annotated[int | None, tyro.conf.Positional] = None,
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float | None = None,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
) -> int:
    """Get or set Twinkly app saturation."""
    return run_output_control(
        DiagnosticConfig(
            host=host,
            timeout=timeout,
            discovery_timeout=discovery_timeout,
            attempts=attempts,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
        ),
        'saturation',
        action,
        value,
    )


def mode(
    action: Annotated[ModeAction, tyro.conf.Positional] = 'get',
    value: Annotated[LedMode | None, tyro.conf.Positional] = None,
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float | None = None,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
) -> int:
    """Get or set Twinkly LED mode, then turn the lights off."""
    return run_mode_control(
        DiagnosticConfig(
            host=host,
            timeout=timeout,
            discovery_timeout=discovery_timeout,
            attempts=attempts,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
        ),
        action,
        value,
    )


def color(
    action: Annotated[ColorAction, tyro.conf.Positional] = 'get',
    red: Annotated[int | None, tyro.conf.Positional] = None,
    green: Annotated[int | None, tyro.conf.Positional] = None,
    blue: Annotated[int | None, tyro.conf.Positional] = None,
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float | None = None,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
) -> int:
    """Get or set Twinkly static RGB color, then turn the lights off."""
    return run_color_control(
        DiagnosticConfig(
            host=host,
            timeout=timeout,
            discovery_timeout=discovery_timeout,
            attempts=attempts,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
        ),
        action,
        red,
        green,
        blue,
    )


def effects(
    action: Annotated[EffectAction, tyro.conf.Positional] = 'list',
    effect_id: Annotated[int | None, tyro.conf.Positional] = None,
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float | None = None,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
) -> int:
    """List, read, or set Twinkly built-in effects, then turn the lights off."""
    return run_effect_control(
        DiagnosticConfig(
            host=host,
            timeout=timeout,
            discovery_timeout=discovery_timeout,
            attempts=attempts,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
        ),
        action,
        effect_id,
    )


def layout(
    action: Annotated[LayoutAction, tyro.conf.Positional] = 'get',
    path: Annotated[Path | None, tyro.conf.Positional] = None,
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float | None = None,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
) -> int:
    """Get, export, upload, or delete Twinkly layout, then turn the lights off."""
    return run_layout_control(
        DiagnosticConfig(
            host=host,
            timeout=timeout,
            discovery_timeout=discovery_timeout,
            attempts=attempts,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
        ),
        action,
        path,
    )


def led_config(
    action: Annotated[LedConfigAction, tyro.conf.Positional] = 'get',
    path: Annotated[Path | None, tyro.conf.Positional] = None,
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float | None = None,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
) -> int:
    """Get or set Twinkly LED string config, then turn the lights off."""
    return run_led_config_control(
        DiagnosticConfig(
            host=host,
            timeout=timeout,
            discovery_timeout=discovery_timeout,
            attempts=attempts,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
        ),
        action,
        path,
    )


def timer(
    action: Annotated[TimerAction, tyro.conf.Positional] = 'get',
    time_on: Annotated[int | None, tyro.conf.Positional] = None,
    time_off: Annotated[int | None, tyro.conf.Positional] = None,
    time_now: int | None = None,
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float | None = None,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
) -> int:
    """Get or set Twinkly timer, then turn the lights off."""
    return run_timer_control(
        DiagnosticConfig(
            host=host,
            timeout=timeout,
            discovery_timeout=discovery_timeout,
            attempts=attempts,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
        ),
        action,
        time_on,
        time_off,
        time_now,
    )


def movie(
    action: Annotated[MovieAction, tyro.conf.Positional] = 'list',
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float | None = None,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
) -> int:
    """Read Twinkly movie config, list, or current movie, then turn the lights off."""
    return run_movie_control(
        DiagnosticConfig(
            host=host,
            timeout=timeout,
            discovery_timeout=discovery_timeout,
            attempts=attempts,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
        ),
        action,
    )


def playlist(
    action: Annotated[PlaylistAction, tyro.conf.Positional] = 'list',
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float | None = None,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
) -> int:
    """Read Twinkly playlist or current playlist entry, then turn the lights off."""
    return run_playlist_control(
        DiagnosticConfig(
            host=host,
            timeout=timeout,
            discovery_timeout=discovery_timeout,
            attempts=attempts,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
        ),
        action,
    )


def network(
    action: Annotated[NetworkAction, tyro.conf.Positional] = 'status',
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float | None = None,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
) -> int:
    """Read Twinkly network status or WiFi scan results, then turn the lights off."""
    return run_network_control(
        DiagnosticConfig(
            host=host,
            timeout=timeout,
            discovery_timeout=discovery_timeout,
            attempts=attempts,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
        ),
        action,
    )


def mqtt(
    action: Annotated[MqttAction, tyro.conf.Positional] = 'config',
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float | None = None,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
) -> int:
    """Read Twinkly MQTT config, then turn the lights off."""
    return run_mqtt_control(
        DiagnosticConfig(
            host=host,
            timeout=timeout,
            discovery_timeout=discovery_timeout,
            attempts=attempts,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
        ),
        action,
    )


def mic(
    action: Annotated[MicAction, tyro.conf.Positional] = 'config',
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float | None = None,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
) -> int:
    """Read Twinkly mic config or sample, then turn the lights off."""
    return run_mic_control(
        DiagnosticConfig(
            host=host,
            timeout=timeout,
            discovery_timeout=discovery_timeout,
            attempts=attempts,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
        ),
        action,
    )


def music(
    action: Annotated[MusicAction, tyro.conf.Positional] = 'drivers',
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float | None = None,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
) -> int:
    """Read Twinkly music drivers and driver sets, then turn the lights off."""
    return run_music_control(
        DiagnosticConfig(
            host=host,
            timeout=timeout,
            discovery_timeout=discovery_timeout,
            attempts=attempts,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
        ),
        action,
    )
