from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal

import tyro

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
from .xled import (
    ColorAction,
    EffectAction,
    LayoutAction,
    LedConfigAction,
    LedMode,
    ModeAction,
    OutputControlAction,
    run_color_control,
    run_effect_control,
    run_layout_control,
    run_led_config_control,
    run_mode_control,
    run_output_control,
)


def main(args: Sequence[str] | None = None) -> int:
    return tyro.extras.subcommand_cli_from_dict(
        {
            'black-floor': black_floor,
            'brightness': brightness,
            'color': color,
            'diagnostic': diagnostic,
            'effects': effects,
            'layout': layout,
            'led-config': led_config,
            'mode': mode,
            'saturation': saturation,
            'test': test,
            'test2': test2,
            'verify': verify,
        },
        prog='lyte',
        args=args,
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
