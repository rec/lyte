from __future__ import annotations

import random
import time
from dataclasses import replace
from typing import cast

from ..logging import log_status
from .config import (
    RANDOM_ANIMATIONS,
    RANDOM_MAX_DURATION,
    RANDOM_MIN_DURATION,
    RANDOM_WALK_BOUNDS,
    RANDOM_WALK_PERIOD,
    RANDOM_WALK_SPEED,
    RANDOM_WALK_VARIANCE,
    AnimateConfig,
    AnimationName,
)


def random_pattern_duration(generator: random.Random) -> float:
    return generator.uniform(RANDOM_MIN_DURATION, RANDOM_MAX_DURATION)


def random_overlap_duration(duration: float) -> float:
    return duration / 2


def clipped_duration(duration: float, stop_at: float | None) -> float:
    if stop_at is None:
        return duration
    return min(duration, stop_at - time.monotonic())


def log_pattern_start(animation: str, duration: float) -> None:
    log_status(f'[pattern] {animation} for {duration:.1f} seconds')


def random_animation_args(
    args: AnimateConfig,
    generator: random.Random,
    previous_animation: str | None,
) -> AnimateConfig:
    choices = [a for a in RANDOM_ANIMATIONS if a != previous_animation]
    animation = cast(AnimationName, generator.choice(choices))
    seed = generator.randrange(0, 2**32)
    if animation == 'hamiltonian':
        return replace(args, animation=animation, seed=seed, n=256, speed=100)
    if animation == 'random_walk':
        return replace(
            args,
            animation=animation,
            seed=seed,
            speed=RANDOM_WALK_SPEED,
            variance=RANDOM_WALK_VARIANCE,
            bounds=RANDOM_WALK_BOUNDS,
            period=RANDOM_WALK_PERIOD,
            pre_fill=True,
        )
    return replace(args, animation=animation, seed=seed)
