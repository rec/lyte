from __future__ import annotations

from collections.abc import Sequence

from ..animation import Animation
from ..animations import bibliopixel
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
        return bibliopixel.ColorChase(
            color=rgb_arg(args.color, (255, 0, 0)),
            width=args.width,
            start=args.start,
            end=args.end,
            step=args.step,
        )
    if args.animation == 'color_wipe':
        return bibliopixel.ColorWipe(
            color=rgb_arg(args.color, (255, 0, 0)),
            start=args.start,
            end=args.end,
            step=args.step,
        )
    if args.animation == 'color_fill':
        return bibliopixel.ColorFill(
            color=rgb_arg(args.color, (255, 0, 0)),
        )
    if args.animation == 'color_fade':
        return bibliopixel.ColorFade(
            colors=colors_arg(args.colors, ((255, 0, 0),)),
            level_step=args.level_step,
            start=args.start,
            end=args.end,
        )
    if args.animation == 'alternates':
        return bibliopixel.Alternates(
            color1=rgb_arg(args.color, (255, 255, 255)),
            color2=rgb_arg(args.color2, (0, 0, 0)),
            max_led=args.max_led,
        )
    if args.animation == 'color_pattern':
        return bibliopixel.ColorPattern(
            colors=colors_arg(args.colors),
            width=args.width,
            reverse=args.reverse,
        )
    if args.animation == 'party_mode':
        return bibliopixel.PartyMode(colors=colors_arg(args.colors))
    if args.animation == 'fire_flies':
        return bibliopixel.FireFlies(
            colors=colors_arg(args.colors, ((255, 0, 0),)),
            width=args.width,
            count=args.count,
            start=args.start,
            end=args.end,
            seed=args.seed,
        )
    if args.animation == 'saber_blade':
        return bibliopixel.SaberBlade(
            colors=colors_arg(args.colors, ((255, 0, 0),)),
            speed=round(args.speed),
        )
    if args.animation == 'rainbow':
        return bibliopixel.Rainbow(
            start=args.start,
            end=args.end,
            step=args.step,
        )
    if args.animation == 'rainbow_cycle':
        return bibliopixel.RainbowCycle(
            start=args.start,
            end=args.end,
            step=args.step,
        )
    if args.animation == 'linear_rainbow':
        return bibliopixel.LinearRainbow(
            max_led=args.max_led,
            individual_pixel=args.individual_pixel,
            step=args.step,
        )
    if args.animation == 'halves_rainbow':
        return bibliopixel.HalvesRainbow(
            max_led=args.max_led,
            center_out=not args.center_in,
            rainbow_inc=args.rainbow_inc,
            step=args.step,
        )
    if args.animation in ('larson_scanner', 'larson_rainbow'):
        return bibliopixel.LarsonScanner(
            color=rgb_arg(args.color, (255, 0, 0)),
            tail=args.tail,
            start=args.start,
            end=args.end,
            step=args.step,
            rainbow=args.animation == 'larson_rainbow',
        )
    if args.animation == 'pulse':
        return bibliopixel.Pulse(
            colors=colors_arg(args.colors, ((255, 0, 0),)),
            tail=args.tail,
            chance=args.chance,
            min_speed=args.min_speed,
            max_speed=args.max_speed,
            seed=args.seed,
        )
    if args.animation == 'pixel_ping_pong':
        return bibliopixel.PixelPingPong(
            color=rgb_arg(args.color, (255, 255, 255)),
            max_led=args.max_led,
            total_pixels=args.total_pixels,
            fade_delay=args.fade_delay,
        )
    if args.animation == 'searchlights':
        return bibliopixel.Searchlights(
            colors=colors_arg(args.colors, bibliopixel.DEFAULT_PATTERN),
            tail=args.tail,
            start=args.start,
            end=args.end,
            seed=args.seed,
        )
    if args.animation in ('wave', 'wave_move'):
        return bibliopixel.Wave(
            color=rgb_arg(args.color, (255, 0, 0)),
            cycles=args.cycles,
            start=args.start,
            end=args.end,
            moving=args.animation == 'wave_move',
        )
    if args.animation == 'twinkle':
        return bibliopixel.Twinkle(
            colors=colors_arg(args.colors),
            density=args.density,
            speed=round(args.speed),
            max_bright=args.max_bright,
            seed=args.seed,
        )
    if args.animation == 'white_twinkle':
        return bibliopixel.WhiteTwinkle(
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


def rgb_arg(value: Sequence[int] | None, default: bibliopixel.RGB) -> bibliopixel.RGB:
    if value is None:
        return default
    return value[0], value[1], value[2]


def colors_arg(
    value: Sequence[int] | None,
    default: tuple[bibliopixel.RGB, ...] = bibliopixel.DEFAULT_PATTERN,
) -> tuple[bibliopixel.RGB, ...]:
    if value is None:
        return default
    return tuple(
        (value[i], value[i + 1], value[i + 2]) for i in range(0, len(value), 3)
    )
