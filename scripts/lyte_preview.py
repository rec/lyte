#!/usr/bin/env python3
"""Render a Lyte animation to a standalone HTML preview."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lyte_animate import ANIMATIONS, AnimateConfig, AnimationName, build_animation

from lyte import Layout, render_animation_html

PREVIEW_ANIMATIONS: tuple[str, ...] = tuple(
    a for a in ANIMATIONS if a not in ("off", "random")
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
    animation = build_animation(animation_args(args))
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "animation",
        choices=PREVIEW_ANIMATIONS,
        help="Animation to preview.",
    )
    parser.add_argument("output", type=Path)
    parser.add_argument("-o", "--open", action="store_true")
    parser.add_argument("--name")
    parser.add_argument("--width", type=int, default=16)
    parser.add_argument("--height", type=int, default=16)
    parser.add_argument("--spacing", type=float, default=1.0)
    parser.add_argument("--led-size", type=float, default=1.0)
    parser.add_argument("--fps", type=float, default=20)
    parser.add_argument("--duration", type=float, default=10)
    parser.add_argument("--speed", type=float, default=25)
    parser.add_argument("--pre-fill", action="store_true")
    parser.add_argument("--center-in", action="store_true")
    parser.add_argument("--individual-pixel", action="store_true")
    parser.add_argument("--step", type=int, default=1)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--tail", type=int, default=2)
    parser.add_argument("--chance", type=int, default=30)
    parser.add_argument("--min-speed", type=int, default=1)
    parser.add_argument("--max-speed", type=int, default=5)
    parser.add_argument("--total-pixels", type=int, default=1)
    parser.add_argument("--fade-delay", type=int, default=1)
    parser.add_argument("--density", type=int, default=20)
    parser.add_argument("--max-bright", type=int, default=255)
    parser.add_argument("--cycles", type=int, default=2)
    parser.add_argument("--level-step", type=int, default=5)
    parser.add_argument("--rainbow-inc", type=int, default=4)
    parser.add_argument("--max-led", type=int)
    parser.add_argument("--reverse", action="store_true")
    parser.add_argument("--n", type=int, default=32)
    parser.add_argument("--order", default="rgb")
    parser.add_argument("--inverted", default="")
    parser.add_argument("--variance", type=float, default=1)
    parser.add_argument("--bounds", type=float, nargs=2, default=(0, 180))
    parser.add_argument("--color", type=int, nargs=3)
    parser.add_argument("--color2", type=int, nargs=3)
    parser.add_argument("--colors", type=int, nargs="+")
    parser.add_argument("--period", type=float, default=0)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    validate_args(parser, args)
    return args


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.fps <= 0:
        parser.error("--fps must be greater than zero")
    if args.duration <= 0:
        parser.error("--duration must be greater than zero")
    if args.width <= 0:
        parser.error("--width must be greater than zero")
    if args.height <= 0:
        parser.error("--height must be greater than zero")
    if args.spacing <= 0:
        parser.error("--spacing must be greater than zero")
    if args.led_size <= 0:
        parser.error("--led-size must be greater than zero")
    if args.speed < 0:
        parser.error("--speed must not be negative")
    if args.variance < 0:
        parser.error("--variance must not be negative")
    if args.bounds[0] >= args.bounds[1]:
        parser.error("--bounds must be ordered low high")
    if args.color is not None and any(c < 0 or c > 255 for c in args.color):
        parser.error("--color components must be between 0 and 255")
    if args.color2 is not None and any(c < 0 or c > 255 for c in args.color2):
        parser.error("--color2 components must be between 0 and 255")
    if args.colors is not None:
        if len(args.colors) % 3:
            parser.error("--colors must contain complete RGB triples")
        if any(c < 0 or c > 255 for c in args.colors):
            parser.error("--colors components must be between 0 and 255")
    if args.step < 1:
        parser.error("--step must be at least 1")
    if args.count < 1:
        parser.error("--count must be at least 1")
    if args.tail < 0:
        parser.error("--tail must not be negative")
    if args.chance < 0 or args.chance > 100:
        parser.error("--chance must be between 0 and 100")
    if args.min_speed < 1 or args.max_speed <= args.min_speed:
        parser.error("--min-speed and --max-speed must define a non-empty range")
    if args.total_pixels < 1:
        parser.error("--total-pixels must be at least 1")
    if args.fade_delay < 1:
        parser.error("--fade-delay must be at least 1")
    if args.density < 1:
        parser.error("--density must be at least 1")
    if args.max_bright < 1 or args.max_bright > 255:
        parser.error("--max-bright must be between 1 and 255")
    if args.cycles < 1:
        parser.error("--cycles must be at least 1")
    if args.level_step < 1:
        parser.error("--level-step must be at least 1")
    if args.rainbow_inc < 0:
        parser.error("--rainbow-inc must not be negative")
    if args.start < 0:
        parser.error("--start must not be negative")


def animation_args(args: argparse.Namespace) -> AnimateConfig:
    return AnimateConfig(
        animation=cast(AnimationName, args.animation),
        speed=args.speed,
        fps=args.fps,
        duration=args.duration,
        pre_fill=args.pre_fill,
        center_in=args.center_in,
        individual_pixel=args.individual_pixel,
        step=args.step,
        start=args.start,
        end=args.end,
        width=1,
        count=args.count,
        tail=args.tail,
        chance=args.chance,
        min_speed=args.min_speed,
        max_speed=args.max_speed,
        total_pixels=args.total_pixels,
        fade_delay=args.fade_delay,
        density=args.density,
        max_bright=args.max_bright,
        cycles=args.cycles,
        level_step=args.level_step,
        rainbow_inc=args.rainbow_inc,
        max_led=args.max_led,
        reverse=args.reverse,
        n=args.n,
        order=args.order,
        inverted=args.inverted,
        variance=args.variance,
        bounds=tuple(args.bounds),
        color=None if args.color is None else tuple(args.color),
        color2=None if args.color2 is None else tuple(args.color2),
        colors=None if args.colors is None else tuple(args.colors),
        period=args.period,
        seed=args.seed,
    )


def print_preview_patterns() -> None:
    for animation in PREVIEW_ANIMATIONS:
        print(animation)


if __name__ == "__main__":
    raise SystemExit(main())
