from __future__ import annotations

import random
import time
from dataclasses import replace
from typing import cast

from reccy import logging

from . import config

LOGGER = logging.get_logger(__name__)


def random_pattern_duration(generator: random.Random) -> float:
    return generator.uniform(config.RANDOM_MIN_DURATION, config.RANDOM_MAX_DURATION)


def random_overlap_duration(duration: float) -> float:
    return duration / 2


def clipped_duration(duration: float, stop_at: float | None) -> float:
    if stop_at is None:
        return duration
    return min(duration, stop_at - time.monotonic())


def log_pattern_start(animation: str, duration: float) -> None:
    LOGGER.info(f'[pattern] {animation} for {duration:.1f} seconds')


def random_animation_args(
    args: config.AnimateConfig,
    generator: random.Random,
    previous_animation: str | None,
) -> config.AnimateConfig:
    choices = [a for a in config.RANDOM_ANIMATIONS if a != previous_animation]
    animation = cast(config.AnimationName, generator.choice(choices))
    seed = generator.randrange(0, 2**32)
    if animation == 'hamiltonian':
        return replace(args, animation=animation, seed=seed, n=256, speed=100)
    if animation == 'random_walk':
        return replace(
            args,
            animation=animation,
            seed=seed,
            speed=config.RANDOM_WALK_SPEED,
            variance=config.RANDOM_WALK_VARIANCE,
            bounds=config.RANDOM_WALK_BOUNDS,
            period=config.RANDOM_WALK_PERIOD,
            pre_fill=True,
        )
    return replace(args, animation=animation, seed=seed)
