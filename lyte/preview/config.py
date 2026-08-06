from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, cast

import tyro

from ..animate import ANIMATIONS, AnimateConfig, AnimationName

PreviewAnimationName = Literal[
    'alternates',
    'color_chase',
    'color_fade',
    'color_fill',
    'color_pattern',
    'color_wipe',
    'fire_flies',
    'halves_rainbow',
    'hamiltonian',
    'larson_rainbow',
    'larson_scanner',
    'linear_rainbow',
    'party_mode',
    'pixel_ping_pong',
    'pulse',
    'rainbow',
    'rainbow_cycle',
    'random_walk',
    'saber_blade',
    'searchlights',
    'twinkle',
    'wave',
    'wave_move',
    'white_twinkle',
]
PREVIEW_ANIMATIONS: tuple[str, ...] = tuple(
    a for a in ANIMATIONS if a not in ('off', 'random')
)


@dataclass(frozen=True)
class PreviewConfig:
    animation: Annotated[PreviewAnimationName | None, tyro.conf.Positional] = None
    output: Annotated[Path | None, tyro.conf.Positional] = None
    open: bool = False
    name: str | None = None
    width: int = 16
    height: int = 16
    spacing: float = 1.0
    led_size: float = 1.0
    fps: float = 20
    duration: float = 10
    speed: float = 25
    pre_fill: bool = False
    center_in: bool = False
    individual_pixel: bool = False
    step: int = 1
    start: int = 0
    end: int | None = None
    count: int = 1
    tail: int = 2
    chance: int = 30
    min_speed: int = 1
    max_speed: int = 5
    total_pixels: int = 1
    fade_delay: int = 1
    density: int = 20
    max_bright: int = 255
    cycles: int = 2
    level_step: int = 5
    rainbow_inc: int = 4
    max_led: int | None = None
    reverse: bool = False
    n: int = 32
    order: str = 'rgb'
    inverted: str = ''
    variance: float = 1
    bounds: tuple[float, float] = (0, 180)
    color: tuple[int, int, int] | None = None
    color2: tuple[int, int, int] | None = None
    colors: tuple[int, ...] | None = None
    period: float = 0
    seed: int | None = None

    @property
    def animation_config(self) -> AnimateConfig:
        if self.animation is None:
            raise ValueError('preview animation is required')
        return AnimateConfig(
            animation=cast(AnimationName, self.animation),
            speed=self.speed,
            fps=self.fps,
            duration=self.duration,
            pre_fill=self.pre_fill,
            center_in=self.center_in,
            individual_pixel=self.individual_pixel,
            step=self.step,
            start=self.start,
            end=self.end,
            width=1,
            count=self.count,
            tail=self.tail,
            chance=self.chance,
            min_speed=self.min_speed,
            max_speed=self.max_speed,
            total_pixels=self.total_pixels,
            fade_delay=self.fade_delay,
            density=self.density,
            max_bright=self.max_bright,
            cycles=self.cycles,
            level_step=self.level_step,
            rainbow_inc=self.rainbow_inc,
            max_led=self.max_led,
            reverse=self.reverse,
            n=self.n,
            order=self.order,
            inverted=self.inverted,
            variance=self.variance,
            bounds=self.bounds,
            color=self.color,
            color2=self.color2,
            colors=self.colors,
            period=self.period,
            seed=self.seed,
        )
