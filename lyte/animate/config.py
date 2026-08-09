from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Annotated, Literal, NoReturn

import tyro

ANIMATIONS: tuple[str, ...] = (
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
    'linear_gradient',
    'log_gradient',
    'grey_code',
    'exponential_fade',
    'randomize',
    'rain',
    'off',
    'party_mode',
    'pixel_ping_pong',
    'pulse',
    'rainbow',
    'rainbow_cycle',
    'random',
    'random_walk',
    'saber_blade',
    'searchlights',
    'twinkle',
    'wave',
    'wave_move',
    'white_twinkle',
)
AnimationName = Literal[
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
    'linear_gradient',
    'log_gradient',
    'grey_code',
    'exponential_fade',
    'randomize',
    'rain',
    'off',
    'party_mode',
    'pixel_ping_pong',
    'pulse',
    'rainbow',
    'rainbow_cycle',
    'random',
    'random_walk',
    'saber_blade',
    'searchlights',
    'twinkle',
    'wave',
    'wave_move',
    'white_twinkle',
]
RANDOM_ANIMATIONS: tuple[str, ...] = tuple(
    a for a in ANIMATIONS if a not in ('off', 'random')
)
RANDOM_MIN_DURATION = 10.0
RANDOM_MAX_DURATION = 30.0
RANDOM_WALK_SPEED = 80.0
RANDOM_WALK_VARIANCE = 80.0
RANDOM_WALK_BOUNDS = (0.0, 255.0)
RANDOM_WALK_PERIOD = 6.0


@dataclass(frozen=True)
class AnimateConfig:
    animation: Annotated[AnimationName, tyro.conf.Positional] = 'random'
    host: str | None = None
    timeout: float = 5.0
    discovery_timeout: float | None = None
    attempts: int = 10
    retry_delay: float = 0.5
    retry_backoff: float = 2.0
    led_count: int | None = None
    speed: float = 25
    fps: float = 20
    duration: float | None = None
    pre_fill: bool = False
    center_in: bool = False
    individual_pixel: bool = False
    step: int = 1
    start: int = 0
    end: int | None = None
    width: int = 1
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


def validate_args(args: AnimateConfig) -> None:
    if args.attempts < 1:
        fail('--attempts must be at least 1')
    if args.retry_delay < 0:
        fail('--retry-delay must not be negative')
    if args.retry_backoff < 1:
        fail('--retry-backoff must be at least 1')
    if args.fps <= 0:
        fail('--fps must be greater than zero')
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
    if args.width < 1:
        fail('--width must be at least 1')
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
