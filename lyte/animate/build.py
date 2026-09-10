from __future__ import annotations

from collections.abc import Sequence

from .. import show
from ..animation import Animation
from ..animations import colors, numerical
from ..animations.events import (
    color_chase,
    confetti_with_decay,
    expanding_ripples,
    fire_flies,
    larson_scanner,
    lightning_storm,
    packet_traffic,
    pixel_ping_pong,
    pulse,
    rain,
    searchlights,
    twinkle,
    white_twinkle,
)
from ..animations.fields import (
    aurora,
    candle_bank,
    color_fade,
    exponential_fade,
    halves_rainbow,
    interference,
    linear_gradient,
    linear_rainbow,
    log_gradient,
    ocean_current,
    palette_conveyor,
    rainbow,
    rainbow_cycle,
    wave,
)
from ..animations.patterns import (
    alternates,
    color_fill,
    color_pattern,
    color_wipe,
    grey_code,
    saber_blade,
)
from ..animations.patterns.hamiltonian import Hamiltonian
from ..animations.simulations import (
    cellular_automaton,
    colliding_particles,
    fire_and_embers,
    party_mode,
    randomize,
    reaction_diffusion_strip,
)
from ..animations.simulations.random_walk import RandomWalk
from .config import AnimateConfig


def build_animation(args: AnimateConfig) -> Animation:
    if args.animation == 'composition':
        if args.composition_file is None:
            raise ValueError('composition requires --composition-file')
        graph = show.build_show_graph(show.load_show_file(args.composition_file))
        if args.composition_source not in graph.sources:
            raise ValueError(f'unknown composition source {args.composition_source!r}')
        return graph.sources[args.composition_source]
    effect_speed = args.speed / 25
    if args.animation == 'fire_and_embers':
        return fire_and_embers.FireAndEmbers(
            palette=color_list_arg(args.colors, numerical.FIRE_PALETTE),
            origin='end' if args.reverse else 'start',
            speed=effect_speed,
            seed=args.seed,
        )
    if args.animation == 'aurora':
        return aurora.Aurora(
            palette=color_list_arg(args.colors, numerical.AURORA_PALETTE),
            speed=effect_speed,
            seed=args.seed,
        )
    if args.animation == 'ocean_current':
        return ocean_current.OceanCurrent(
            palette=color_list_arg(args.colors, numerical.OCEAN_PALETTE),
            speed=effect_speed,
            seed=args.seed,
        )
    if args.animation == 'interference':
        return interference.Interference(
            palette=color_list_arg(args.colors, numerical.INTERFERENCE_PALETTE),
            speed=effect_speed,
        )
    if args.animation == 'palette_conveyor':
        return palette_conveyor.PaletteConveyor(
            palette=color_list_arg(args.colors, numerical.CONVEYOR_PALETTE),
            speed=effect_speed,
            reverse=args.reverse,
        )
    if args.animation == 'confetti_with_decay':
        return confetti_with_decay.ConfettiWithDecay(
            palette=color_list_arg(args.colors, numerical.CONFETTI_PALETTE),
            speed=effect_speed,
            seed=args.seed,
        )
    if args.animation == 'lightning_storm':
        return lightning_storm.LightningStorm(
            color=rgb_arg(args.color, (200, 220, 255)),
            speed=effect_speed,
            seed=args.seed,
        )
    if args.animation == 'candle_bank':
        return candle_bank.CandleBank(
            color=rgb_arg(args.color, (255, 120, 30)),
            speed=effect_speed,
            seed=args.seed,
        )
    if args.animation == 'colliding_particles':
        return colliding_particles.CollidingParticles(
            palette=color_list_arg(args.colors, numerical.PARTICLE_PALETTE),
            speed=effect_speed,
            seed=args.seed,
        )
    if args.animation == 'expanding_ripples':
        return expanding_ripples.ExpandingRipples(
            palette=color_list_arg(args.colors, numerical.RIPPLE_PALETTE),
            speed=effect_speed,
            seed=args.seed,
        )
    if args.animation == 'cellular_automaton':
        return cellular_automaton.CellularAutomaton(
            palette=color_list_arg(args.colors, numerical.CELLULAR_PALETTE),
            speed=effect_speed,
            seed=args.seed,
        )
    if args.animation == 'reaction_diffusion_strip':
        return reaction_diffusion_strip.ReactionDiffusionStrip(
            palette=color_list_arg(args.colors, numerical.REACTION_PALETTE),
            speed=effect_speed,
            seed=args.seed,
        )
    if args.animation == 'packet_traffic':
        direction = 'reverse' if args.reverse else 'both'
        return packet_traffic.PacketTraffic(
            palette=color_list_arg(args.colors, numerical.PACKET_PALETTE),
            direction=direction,
            speed=effect_speed,
            seed=args.seed,
        )
    if args.animation == 'hamiltonian':
        return Hamiltonian(
            speed=args.speed,
            n=args.n,
            order=args.order,
            inverted=args.inverted,
            pre_fill=args.pre_fill,
        )
    if args.animation == 'color_chase':
        return color_chase.ColorChase(
            color=rgb_arg(args.color, (255, 0, 0)),
            width=args.width,
            start=args.start,
            end=args.end,
            step=args.step,
        )
    if args.animation == 'color_wipe':
        return color_wipe.ColorWipe(
            color=rgb_arg(args.color, (255, 0, 0)),
            start=args.start,
            end=args.end,
            step=args.step,
        )
    if args.animation == 'color_fill':
        return color_fill.ColorFill(
            color=rgb_arg(args.color, (255, 0, 0)),
        )
    if args.animation == 'color_fade':
        return color_fade.ColorFade(
            colors=colors_arg(args.colors, ((255, 0, 0),)),
            level_step=args.level_step,
            start=args.start,
            end=args.end,
        )
    if args.animation == 'linear_gradient':
        return linear_gradient.LinearGradient()
    if args.animation == 'log_gradient':
        return log_gradient.LogGradient()
    if args.animation == 'grey_code':
        return grey_code.GreyCode()
    if args.animation == 'exponential_fade':
        return exponential_fade.ExponentialFade(color=rgb_arg(args.color, (255, 0, 0)))
    if args.animation == 'randomize':
        return randomize.Randomize(seed=args.seed)
    if args.animation == 'rain':
        return rain.Rain(
            colors=colors_arg(args.colors, rain.Rain.model_fields['colors'].default),
            seed=args.seed,
        )
    if args.animation == 'alternates':
        return alternates.Alternates(
            color1=rgb_arg(args.color, (255, 255, 255)),
            color2=rgb_arg(args.color2, (0, 0, 0)),
            max_led=args.max_led,
        )
    if args.animation == 'color_pattern':
        return color_pattern.ColorPattern(
            colors=colors_arg(args.colors),
            width=args.width,
            reverse=args.reverse,
        )
    if args.animation == 'party_mode':
        return party_mode.PartyMode(colors=colors_arg(args.colors))
    if args.animation == 'fire_flies':
        return fire_flies.FireFlies(
            colors=colors_arg(args.colors, ((255, 0, 0),)),
            width=args.width,
            count=args.count,
            start=args.start,
            end=args.end,
            seed=args.seed,
        )
    if args.animation == 'saber_blade':
        return saber_blade.SaberBlade(
            colors=colors_arg(args.colors, ((255, 0, 0),)),
            speed=round(args.speed),
        )
    if args.animation == 'rainbow':
        return rainbow.Rainbow(
            start=args.start,
            end=args.end,
            step=args.step,
        )
    if args.animation == 'rainbow_cycle':
        return rainbow_cycle.RainbowCycle(
            start=args.start,
            end=args.end,
            step=args.step,
        )
    if args.animation == 'linear_rainbow':
        return linear_rainbow.LinearRainbow(
            max_led=args.max_led,
            individual_pixel=args.individual_pixel,
            step=args.step,
        )
    if args.animation == 'halves_rainbow':
        return halves_rainbow.HalvesRainbow(
            max_led=args.max_led,
            center_out=not args.center_in,
            rainbow_inc=args.rainbow_inc,
            step=args.step,
        )
    if args.animation in ('larson_scanner', 'larson_rainbow'):
        return larson_scanner.LarsonScanner(
            color=rgb_arg(args.color, (255, 0, 0)),
            tail=args.tail,
            start=args.start,
            end=args.end,
            step=args.step,
            rainbow=args.animation == 'larson_rainbow',
        )
    if args.animation == 'pulse':
        return pulse.Pulse(
            colors=colors_arg(args.colors, ((255, 0, 0),)),
            tail=args.tail,
            chance=args.chance,
            min_speed=args.min_speed,
            max_speed=args.max_speed,
            seed=args.seed,
        )
    if args.animation == 'pixel_ping_pong':
        return pixel_ping_pong.PixelPingPong(
            color=rgb_arg(args.color, (255, 255, 255)),
            max_led=args.max_led,
            total_pixels=args.total_pixels,
            fade_delay=args.fade_delay,
        )
    if args.animation == 'searchlights':
        return searchlights.Searchlights(
            colors=colors_arg(args.colors, colors.DEFAULT_PATTERN),
            tail=args.tail,
            start=args.start,
            end=args.end,
            seed=args.seed,
        )
    if args.animation in ('wave', 'wave_move'):
        return wave.Wave(
            color=rgb_arg(args.color, (255, 0, 0)),
            cycles=args.cycles,
            start=args.start,
            end=args.end,
            moving=args.animation == 'wave_move',
        )
    if args.animation == 'twinkle':
        return twinkle.Twinkle(
            colors=colors_arg(args.colors),
            density=args.density,
            speed=round(args.speed),
            max_bright=args.max_bright,
            seed=args.seed,
        )
    if args.animation == 'white_twinkle':
        return white_twinkle.WhiteTwinkle(
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


def rgb_arg(value: Sequence[int] | None, default: colors.RGB) -> colors.RGB:
    if value is None:
        return default
    return value[0], value[1], value[2]


def colors_arg(
    value: Sequence[int] | None,
    default: tuple[colors.RGB, ...] = colors.DEFAULT_PATTERN,
) -> tuple[colors.RGB, ...]:
    if value is None:
        return default
    return tuple(
        (value[i], value[i + 1], value[i + 2]) for i in range(0, len(value), 3)
    )


def color_list_arg(
    value: Sequence[int] | None, default: tuple[colors.RGB, ...]
) -> list[colors.RGB]:
    return list(colors_arg(value, default))
