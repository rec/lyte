from __future__ import annotations

from collections.abc import Sequence

from ..animation import Animation
from ..animations.bibliopixel import (
    DEFAULT_PATTERN,
    RGB,
    Alternates,
    ColorChase,
    ColorFade,
    ColorFill,
    ColorPattern,
    ColorWipe,
    FireFlies,
    HalvesRainbow,
    LarsonScanner,
    LinearRainbow,
    PartyMode,
    PixelPingPong,
    Pulse,
    Rainbow,
    RainbowCycle,
    SaberBlade,
    Searchlights,
    Twinkle,
    Wave,
    WhiteTwinkle,
)
from ..animations.hamiltonian import Hamiltonian
from ..animations.random_walk import RandomWalk
from .config import AnimateConfig


def build_animation(args: AnimateConfig) -> Animation:
    if args.animation == 'hamiltonian':
        return Hamiltonian(
            speed=args.speed,
            n=args.n,
            order=args.order,
            inverted=args.inverted,
            pre_fill=args.pre_fill,
        )
    if args.animation == 'color_chase':
        return ColorChase(
            color=rgb_arg(args.color, (255, 0, 0)),
            width=args.width,
            start=args.start,
            end=args.end,
            step=args.step,
        )
    if args.animation == 'color_wipe':
        return ColorWipe(
            color=rgb_arg(args.color, (255, 0, 0)),
            start=args.start,
            end=args.end,
            step=args.step,
        )
    if args.animation == 'color_fill':
        return ColorFill(
            color=rgb_arg(args.color, (255, 0, 0)),
        )
    if args.animation == 'color_fade':
        return ColorFade(
            colors=colors_arg(args.colors, ((255, 0, 0),)),
            level_step=args.level_step,
            start=args.start,
            end=args.end,
        )
    if args.animation == 'alternates':
        return Alternates(
            color1=rgb_arg(args.color, (255, 255, 255)),
            color2=rgb_arg(args.color2, (0, 0, 0)),
            max_led=args.max_led,
        )
    if args.animation == 'color_pattern':
        return ColorPattern(
            colors=colors_arg(args.colors),
            width=args.width,
            reverse=args.reverse,
        )
    if args.animation == 'party_mode':
        return PartyMode(colors=colors_arg(args.colors))
    if args.animation == 'fire_flies':
        return FireFlies(
            colors=colors_arg(args.colors, ((255, 0, 0),)),
            width=args.width,
            count=args.count,
            start=args.start,
            end=args.end,
            seed=args.seed,
        )
    if args.animation == 'saber_blade':
        return SaberBlade(
            colors=colors_arg(args.colors, ((255, 0, 0),)),
            speed=round(args.speed),
        )
    if args.animation == 'rainbow':
        return Rainbow(
            start=args.start,
            end=args.end,
            step=args.step,
        )
    if args.animation == 'rainbow_cycle':
        return RainbowCycle(
            start=args.start,
            end=args.end,
            step=args.step,
        )
    if args.animation == 'linear_rainbow':
        return LinearRainbow(
            max_led=args.max_led,
            individual_pixel=args.individual_pixel,
            step=args.step,
        )
    if args.animation == 'halves_rainbow':
        return HalvesRainbow(
            max_led=args.max_led,
            center_out=not args.center_in,
            rainbow_inc=args.rainbow_inc,
            step=args.step,
        )
    if args.animation in ('larson_scanner', 'larson_rainbow'):
        return LarsonScanner(
            color=rgb_arg(args.color, (255, 0, 0)),
            tail=args.tail,
            start=args.start,
            end=args.end,
            step=args.step,
            rainbow=args.animation == 'larson_rainbow',
        )
    if args.animation == 'pulse':
        return Pulse(
            colors=colors_arg(args.colors, ((255, 0, 0),)),
            tail=args.tail,
            chance=args.chance,
            min_speed=args.min_speed,
            max_speed=args.max_speed,
            seed=args.seed,
        )
    if args.animation == 'pixel_ping_pong':
        return PixelPingPong(
            color=rgb_arg(args.color, (255, 255, 255)),
            max_led=args.max_led,
            total_pixels=args.total_pixels,
            fade_delay=args.fade_delay,
        )
    if args.animation == 'searchlights':
        return Searchlights(
            colors=colors_arg(args.colors, DEFAULT_PATTERN),
            tail=args.tail,
            start=args.start,
            end=args.end,
            seed=args.seed,
        )
    if args.animation in ('wave', 'wave_move'):
        return Wave(
            color=rgb_arg(args.color, (255, 0, 0)),
            cycles=args.cycles,
            start=args.start,
            end=args.end,
            moving=args.animation == 'wave_move',
        )
    if args.animation == 'twinkle':
        return Twinkle(
            colors=colors_arg(args.colors),
            density=args.density,
            speed=round(args.speed),
            max_bright=args.max_bright,
            seed=args.seed,
        )
    if args.animation == 'white_twinkle':
        return WhiteTwinkle(
            density=args.density,
            speed=round(args.speed),
            max_bright=args.max_bright,
            seed=args.seed,
        )
    color = (
        None
        if args.color is None
        else (float(args.color[0]), float(args.color[1]), float(args.color[2]))
    )
    return RandomWalk(
        speed=args.speed,
        variance=args.variance,
        bounds=(args.bounds[0], args.bounds[1]),
        color=color,
        period=args.period,
        pre_fill=args.pre_fill,
        seed=args.seed,
    )


def rgb_arg(value: Sequence[int] | None, default: RGB) -> RGB:
    if value is None:
        return default
    return value[0], value[1], value[2]


def colors_arg(
    value: Sequence[int] | None,
    default: tuple[RGB, ...] = DEFAULT_PATTERN,
) -> tuple[RGB, ...]:
    if value is None:
        return default
    return tuple(
        (value[i], value[i + 1], value[i + 2]) for i in range(0, len(value), 3)
    )
