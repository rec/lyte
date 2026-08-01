#!/usr/bin/env python3
"""Render a Lyte animation to a standalone HTML preview."""

import sys
import webbrowser
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, NoReturn, cast

import tyro

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lyte_animate import ANIMATIONS, AnimateConfig, AnimationName, build_animation

from lyte import Layout, render_animation_html

PreviewAnimationName = Literal[
    "alternates",
    "color_chase",
    "color_fade",
    "color_fill",
    "color_pattern",
    "color_wipe",
    "fire_flies",
    "halves_rainbow",
    "hamiltonian",
    "larson_rainbow",
    "larson_scanner",
    "linear_rainbow",
    "party_mode",
    "pixel_ping_pong",
    "pulse",
    "rainbow",
    "rainbow_cycle",
    "random_walk",
    "saber_blade",
    "searchlights",
    "twinkle",
    "wave",
    "wave_move",
    "white_twinkle",
]
PREVIEW_ANIMATIONS: tuple[str, ...] = tuple(
    a for a in ANIMATIONS if a not in ("off", "random")
)


@dataclass(frozen=True)
class PreviewConfig:
    animation: Annotated[PreviewAnimationName, tyro.conf.Positional]
    output: Annotated[Path, tyro.conf.Positional]
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
    order: str = "rgb"
    inverted: str = ""
    variance: float = 1
    bounds: tuple[float, float] = (0, 180)
    color: tuple[int, int, int] | None = None
    color2: tuple[int, int, int] | None = None
    colors: tuple[int, ...] | None = None
    period: float = 0
    seed: int | None = None

    @property
    def animation_config(self) -> AnimateConfig:
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


def main() -> int:
    if len(sys.argv) == 1:
        print_preview_patterns()
        return 0
    args = parse_args()
    layout = Layout(
        name=args.name or args.animation,
        dims=[args.height, args.width],
        spacing=args.spacing,
    )
    animation = build_animation(args.animation_config)
    render_animation_html(
        animation,
        layout,
        args.output,
        fps=args.fps,
        duration=args.duration,
        led_size=args.led_size,
    )
    if args.open:
        webbrowser.open(args.output.resolve().as_uri())
    return 0


def parse_args(args: Sequence[str] | None = None) -> PreviewConfig:
    config = tyro.cli(PreviewConfig, args=args)
    validate_args(config)
    return config


def validate_args(args: PreviewConfig) -> None:
    if args.fps <= 0:
        fail("--fps must be greater than zero")
    if args.duration <= 0:
        fail("--duration must be greater than zero")
    if args.width <= 0:
        fail("--width must be greater than zero")
    if args.height <= 0:
        fail("--height must be greater than zero")
    if args.spacing <= 0:
        fail("--spacing must be greater than zero")
    if args.led_size <= 0:
        fail("--led-size must be greater than zero")
    if args.speed < 0:
        fail("--speed must not be negative")
    if args.variance < 0:
        fail("--variance must not be negative")
    if args.bounds[0] >= args.bounds[1]:
        fail("--bounds must be ordered low high")
    if args.color is not None and any(c < 0 or c > 255 for c in args.color):
        fail("--color components must be between 0 and 255")
    if args.color2 is not None and any(c < 0 or c > 255 for c in args.color2):
        fail("--color2 components must be between 0 and 255")
    if args.colors is not None:
        if len(args.colors) % 3:
            fail("--colors must contain complete RGB triples")
        if any(c < 0 or c > 255 for c in args.colors):
            fail("--colors components must be between 0 and 255")
    if args.step < 1:
        fail("--step must be at least 1")
    if args.count < 1:
        fail("--count must be at least 1")
    if args.tail < 0:
        fail("--tail must not be negative")
    if args.chance < 0 or args.chance > 100:
        fail("--chance must be between 0 and 100")
    if args.min_speed < 1 or args.max_speed <= args.min_speed:
        fail("--min-speed and --max-speed must define a non-empty range")
    if args.total_pixels < 1:
        fail("--total-pixels must be at least 1")
    if args.fade_delay < 1:
        fail("--fade-delay must be at least 1")
    if args.density < 1:
        fail("--density must be at least 1")
    if args.max_bright < 1 or args.max_bright > 255:
        fail("--max-bright must be between 1 and 255")
    if args.cycles < 1:
        fail("--cycles must be at least 1")
    if args.level_step < 1:
        fail("--level-step must be at least 1")
    if args.rainbow_inc < 0:
        fail("--rainbow-inc must not be negative")
    if args.start < 0:
        fail("--start must not be negative")


def fail(message: str) -> NoReturn:
    sys.exit(message)


def print_preview_patterns() -> None:
    for animation in PREVIEW_ANIMATIONS:
        print(animation)


if __name__ == "__main__":
    raise SystemExit(main())
