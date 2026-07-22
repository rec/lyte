#!/usr/bin/env python3
"""Render a Lyte animation to a standalone HTML preview."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lyte_animate import ANIMATIONS, build_animation

from lyte import Layout, render_animation_html


def main() -> int:
    args = parse_args()
    layout = Layout.model_validate_json(args.layout.read_text())
    animation = build_animation(args)
    render_animation_html(
        animation,
        layout,
        args.output,
        fps=args.fps,
        duration=args.duration,
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "animation",
        choices=tuple(a for a in ANIMATIONS if a not in ("off", "random")),
        help="Animation to preview.",
    )
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=float, default=20)
    parser.add_argument("--duration", type=float, default=10)
    parser.add_argument("--speed", type=float, default=25)
    parser.add_argument("--pre-fill", action="store_true")
    parser.add_argument("--center-in", action="store_true")
    parser.add_argument("--individual-pixel", action="store_true")
    parser.add_argument("--step", type=int, default=1)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int)
    parser.add_argument("--width", type=int, default=1)
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
    if args.width < 1:
        parser.error("--width must be at least 1")
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


if __name__ == "__main__":
    raise SystemExit(main())
