from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import tyro

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


def main(args: Sequence[str] | None = None) -> int:
    return tyro.extras.subcommand_cli_from_dict(
        {'black-floor': black_floor, 'test': test, 'test2': test2, 'verify': verify},
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
