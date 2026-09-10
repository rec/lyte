from __future__ import annotations

from collections.abc import Sequence

import tyro
from reccy.runtime import logging
from ufor.lights import Interpretation

from .. import animation, show
from ..retry import RetryConfig
from ..twinkly import realtime, track
from ..twinkly.client import TwinklyClient
from .config import AnimateConfig, validate_args

LOGGER = logging.get_logger(__name__)


def main() -> int:
    logging.configure()
    args = parse_args()
    return run_animate(args)


def run_animate(args: AnimateConfig) -> int:
    validate_args(args)
    prepared = show.prepare_animation(
        show.LightProgramSpec(
            selector=args.selector,
            output=args.output,
            parameters=args.parameters,
            wiring=args.wiring,
        ),
        args.library_config,
    )
    if prepared.output.components != ['red', 'green', 'blue']:
        raise ValueError('Twinkly output requires red, green, blue components')
    if prepared.output.interpretation != Interpretation.drive:
        raise ValueError('Twinkly output requires drive light values')

    host = args.host or realtime.discover_host(args.discovery_timeout)
    if host is None:
        return 1
    retry = RetryConfig(
        attempts=args.attempts,
        delay=args.retry_delay,
        backoff=args.retry_backoff,
    )
    client = TwinklyClient(host=host, timeout=args.timeout)
    led_count = realtime.read_led_count(client, retry, args.led_count, host)
    if led_count is None:
        return 1
    if len(prepared.output.layout.lights) != led_count:
        raise ValueError(
            f'score layout has {len(prepared.output.layout.lights)} lights, '
            f'but the Twinkly has {led_count} LEDs'
        )
    twinkly_track = track.TwinklyTrack(
        client=client,
        retry=retry,
        host=host,
        configured_host=args.host,
        discovery_timeout=args.discovery_timeout,
        device=animation.Device(led_count=led_count),
    )
    try:
        if not twinkly_track.prepare():
            return 1
        LOGGER.debug(
            f'[ok] Streaming {args.selector} to {host} for {led_count} LEDs '
            f'at {prepared.fps:g} FPS'
        )
        twinkly_track.stream_frames(
            args.selector,
            prepared.fps,
            args.duration,
            lambda: prepared.byte_frame(wired=True),
        )
    except KeyboardInterrupt:
        LOGGER.debug('')
        LOGGER.debug('[ok] Stopped')
    finally:
        twinkly_track.close()
    return 0


def parse_args(args: Sequence[str] | None = None) -> AnimateConfig:
    return tyro.cli(AnimateConfig, args=args)
