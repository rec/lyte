from __future__ import annotations

import sys
from typing import NoReturn

from .config import PreviewConfig


def validate_args(args: PreviewConfig) -> None:
    if args.fps <= 0:
        fail('--fps must be greater than zero')
    if args.duration <= 0:
        fail('--duration must be greater than zero')
    if args.width <= 0:
        fail('--width must be greater than zero')
    if args.height <= 0:
        fail('--height must be greater than zero')
    if args.spacing <= 0:
        fail('--spacing must be greater than zero')
    if args.led_size <= 0:
        fail('--led-size must be greater than zero')
    if args.speed < 0:
        fail('--speed must not be negative')
    if args.variance < 0:
        fail('--variance must not be negative')
    if args.bounds[0] >= args.bounds[1]:
        fail('--bounds must be ordered low high')
    if args.color is not None and any(c < 0 or c > 255 for c in args.color):
        fail('--color components must be between 0 and 255')
    if args.color2 is not None and any(c < 0 or c > 255 for c in args.color2):
        fail('--color2 components must be between 0 and 255')
    if args.colors is not None:
        if len(args.colors) % 3:
            fail('--colors must contain complete RGB triples')
        if any(c < 0 or c > 255 for c in args.colors):
            fail('--colors components must be between 0 and 255')
    if args.step < 1:
        fail('--step must be at least 1')
    if args.count < 1:
        fail('--count must be at least 1')
    if args.tail < 0:
        fail('--tail must not be negative')
    if args.chance < 0 or args.chance > 100:
        fail('--chance must be between 0 and 100')
    if args.min_speed < 1 or args.max_speed <= args.min_speed:
        fail('--min-speed and --max-speed must define a non-empty range')
    if args.total_pixels < 1:
        fail('--total-pixels must be at least 1')
    if args.fade_delay < 1:
        fail('--fade-delay must be at least 1')
    if args.density < 1:
        fail('--density must be at least 1')
    if args.max_bright < 1 or args.max_bright > 255:
        fail('--max-bright must be between 1 and 255')
    if args.cycles < 1:
        fail('--cycles must be at least 1')
    if args.level_step < 1:
        fail('--level-step must be at least 1')
    if args.rainbow_inc < 0:
        fail('--rainbow-inc must not be negative')
    if args.start < 0:
        fail('--start must not be negative')


def fail(message: str) -> NoReturn:
    sys.exit(message)
