"""Installed renderers for Ufor's built-in RGB effect descriptions."""

from typing import cast

from ufor import effects

from ..animation import Animation
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
    hamiltonian,
    saber_blade,
)
from ..animations.simulations import (
    cellular_automaton,
    colliding_particles,
    fire_and_embers,
    party_mode,
    random_walk,
    randomize,
    reaction_diffusion_strip,
)


class RendererCapabilityError(ValueError):
    pass


def build_effect(effect: effects.EffectValue) -> Animation:
    renderer_type = EFFECT_RENDERERS.get(effect.effect)
    if renderer_type is None:
        raise RendererCapabilityError(
            f'Lyte has no installed renderer for effect {effect.effect!r}'
        )
    renderer_model = cast(type[effects.Effect], renderer_type)
    return cast(Animation, renderer_model.model_validate(effect.model_dump()))


EFFECT_RENDERERS: dict[str, type[Animation]] = {
    'alternates': alternates.Alternates,
    'aurora': aurora.Aurora,
    'candle_bank': candle_bank.CandleBank,
    'cellular_automaton': cellular_automaton.CellularAutomaton,
    'color_chase': color_chase.ColorChase,
    'color_fade': color_fade.ColorFade,
    'color_fill': color_fill.ColorFill,
    'color_pattern': color_pattern.ColorPattern,
    'color_wipe': color_wipe.ColorWipe,
    'colliding_particles': colliding_particles.CollidingParticles,
    'confetti_with_decay': confetti_with_decay.ConfettiWithDecay,
    'expanding_ripples': expanding_ripples.ExpandingRipples,
    'exponential_fade': exponential_fade.ExponentialFade,
    'fire_and_embers': fire_and_embers.FireAndEmbers,
    'fire_flies': fire_flies.FireFlies,
    'grey_code': grey_code.GreyCode,
    'halves_rainbow': halves_rainbow.HalvesRainbow,
    'hamiltonian': hamiltonian.Hamiltonian,
    'interference': interference.Interference,
    'larson_scanner': larson_scanner.LarsonScanner,
    'lightning_storm': lightning_storm.LightningStorm,
    'linear_gradient': linear_gradient.LinearGradient,
    'linear_rainbow': linear_rainbow.LinearRainbow,
    'log_gradient': log_gradient.LogGradient,
    'ocean_current': ocean_current.OceanCurrent,
    'packet_traffic': packet_traffic.PacketTraffic,
    'palette_conveyor': palette_conveyor.PaletteConveyor,
    'party_mode': party_mode.PartyMode,
    'pixel_ping_pong': pixel_ping_pong.PixelPingPong,
    'pulse': pulse.Pulse,
    'rain': rain.Rain,
    'rainbow': rainbow.Rainbow,
    'rainbow_cycle': rainbow_cycle.RainbowCycle,
    'random_walk': random_walk.RandomWalk,
    'randomize': randomize.Randomize,
    'reaction_diffusion_strip': reaction_diffusion_strip.ReactionDiffusionStrip,
    'saber_blade': saber_blade.SaberBlade,
    'searchlights': searchlights.Searchlights,
    'twinkle': twinkle.Twinkle,
    'wave': wave.Wave,
    'white_twinkle': white_twinkle.WhiteTwinkle,
}
