from __future__ import annotations

from collections.abc import Sequence

import tyro

from .fps_test import FpsTestConfig, run_fps_test


def main(args: Sequence[str] | None = None) -> int:
    return tyro.extras.subcommand_cli_from_dict(
        {'test': test},
        prog='lyte',
        args=args,
    )


def test(
    host: str | None = None,
    timeout: float = 5.0,
    discovery_timeout: float = 5.0,
    attempts: int = 10,
    retry_delay: float = 0.5,
    retry_backoff: float = 2.0,
    led_count: int | None = None,
    duration: float = 2.0,
    pause: float = 0.5,
) -> int:
    """Show contrasting blend fades at 20, 45, and 60 FPS."""
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
