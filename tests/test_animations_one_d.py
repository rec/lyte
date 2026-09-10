from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest
from numpy.testing import assert_array_equal

from lyte import animation
from lyte.animate import build, config
from lyte.animations.events import (
    confetti_with_decay,
    expanding_ripples,
    lightning_storm,
    packet_traffic,
)
from lyte.animations.fields import (
    aurora,
    candle_bank,
    interference,
    ocean_current,
    palette_conveyor,
)
from lyte.animations.simulations import (
    cellular_automaton,
    colliding_particles,
    fire_and_embers,
    reaction_diffusion_strip,
)


@pytest.mark.parametrize(
    'factory',
    [
        fire_and_embers.FireAndEmbers,
        aurora.Aurora,
        ocean_current.OceanCurrent,
        interference.Interference,
        palette_conveyor.PaletteConveyor,
        confetti_with_decay.ConfettiWithDecay,
        lightning_storm.LightningStorm,
        candle_bank.CandleBank,
        colliding_particles.CollidingParticles,
        expanding_ripples.ExpandingRipples,
        cellular_automaton.CellularAutomaton,
        reaction_diffusion_strip.ReactionDiffusionStrip,
        packet_traffic.PacketTraffic,
    ],
)
def test_one_d_animations_render_valid_changing_frames(
    factory: Callable[[], animation.Animation],
) -> None:
    source = factory()
    device = animation.Device(led_count=32)
    state = source.initial_state(device)
    state.fps = 20

    frames = [
        animation.validate_frame(device, source.render(device, state)) for _ in range(8)
    ]

    assert state.frame == 8
    assert all(np.all((f >= 0) & (f <= 1)) for f in frames)
    assert any(np.any(f) for f in frames)
    assert any(not np.array_equal(frames[0], f) for f in frames[1:])


@pytest.mark.parametrize(
    'factory',
    [
        lambda: fire_and_embers.FireAndEmbers(seed=4),
        lambda: aurora.Aurora(seed=4),
        lambda: ocean_current.OceanCurrent(seed=4),
        interference.Interference,
        palette_conveyor.PaletteConveyor,
        lambda: confetti_with_decay.ConfettiWithDecay(seed=4),
        lambda: lightning_storm.LightningStorm(seed=4),
        lambda: candle_bank.CandleBank(seed=4),
        lambda: colliding_particles.CollidingParticles(seed=4),
        lambda: expanding_ripples.ExpandingRipples(seed=4),
        lambda: cellular_automaton.CellularAutomaton(seed=4),
        lambda: reaction_diffusion_strip.ReactionDiffusionStrip(seed=4),
        lambda: packet_traffic.PacketTraffic(seed=4),
    ],
)
def test_one_d_animations_are_deterministic(
    factory: Callable[[], animation.Animation],
) -> None:
    device = animation.Device(led_count=24)
    first = factory()
    second = factory()
    first_state = first.initial_state(device)
    second_state = second.initial_state(device)

    for _ in range(6):
        assert_array_equal(
            first.render(device, first_state),
            second.render(device, second_state),
        )


@pytest.mark.parametrize(
    'factory',
    [
        fire_and_embers.FireAndEmbers,
        aurora.Aurora,
        ocean_current.OceanCurrent,
        interference.Interference,
        palette_conveyor.PaletteConveyor,
        confetti_with_decay.ConfettiWithDecay,
        lightning_storm.LightningStorm,
        candle_bank.CandleBank,
        colliding_particles.CollidingParticles,
        expanding_ripples.ExpandingRipples,
        cellular_automaton.CellularAutomaton,
        reaction_diffusion_strip.ReactionDiffusionStrip,
        packet_traffic.PacketTraffic,
    ],
)
def test_one_d_animations_support_one_led(
    factory: Callable[[], animation.Animation],
) -> None:
    source = factory()
    device = animation.Device(led_count=1)
    state = source.initial_state(device)

    frame = source.render(device, state)

    animation.validate_frame(device, frame)


def test_confetti_persists_and_decays() -> None:
    source = confetti_with_decay.ConfettiWithDecay(
        spawn_rate=0, decay=2, speed=1, seed=1
    )
    device = animation.Device(led_count=4)
    state = source.initial_state(device)
    state.spawn_credit = 0
    state.pixels[1] = 1

    first = source.render(device, state).copy()
    second = source.render(device, state).copy()

    assert 0 < second[1, 0] < first[1, 0] < 1


def test_expanding_ripple_moves_away_from_its_origin() -> None:
    source = expanding_ripples.ExpandingRipples(
        palette=[(255, 255, 255)],
        event_rate=0,
        propagation_speed=4,
        width=0.25,
        decay=0.1,
    )
    device = animation.Device(led_count=9)
    state = source.initial_state(device)
    state.fps = 1

    source.render(device, state)
    frame = source.render(device, state)

    assert frame[0, 0] > frame[4, 0]
    assert frame[8, 0] > frame[4, 0]


def test_cellular_automaton_applies_rule() -> None:
    source = cellular_automaton.CellularAutomaton(
        palette=[(0, 0, 0), (255, 255, 255)],
        rule=0,
        initial_density=1,
        generation_rate=1,
        history_decay=100,
        boundary_mode='bounded',
        speed=1,
    )
    device = animation.Device(led_count=5)
    state = source.initial_state(device)
    state.fps = 1

    frame = source.render(device, state)

    assert not state.cells.any()
    assert np.max(frame) < 0.001


def test_reaction_diffusion_uses_elapsed_time() -> None:
    device = animation.Device(led_count=24)
    first = reaction_diffusion_strip.ReactionDiffusionStrip(seed=3)
    second = reaction_diffusion_strip.ReactionDiffusionStrip(seed=3)
    first_state = first.initial_state(device)
    second_state = second.initial_state(device)
    first_state.fps = 20
    second_state.fps = 40

    for _ in range(20):
        first_frame = first.render(device, first_state)
    for _ in range(40):
        second_frame = second.render(device, second_state)

    assert_array_equal(first_frame, second_frame)


def test_packet_acknowledgement_does_not_create_an_acknowledgement() -> None:
    source = packet_traffic.PacketTraffic(
        direction='forward',
        packet_rate=0,
        error_rate=0,
        speed=10,
        seed=1,
    )
    device = animation.Device(led_count=5)
    state = source.initial_state(device)
    state.fps = 1

    source.render(device, state)
    assert state.is_acknowledgement == [True]

    source.render(device, state)
    assert state.is_acknowledgement == []


@pytest.mark.parametrize(
    ('name', 'expected_type'),
    [
        ('fire_and_embers', fire_and_embers.FireAndEmbers),
        ('aurora', aurora.Aurora),
        ('ocean_current', ocean_current.OceanCurrent),
        ('interference', interference.Interference),
        ('palette_conveyor', palette_conveyor.PaletteConveyor),
        ('confetti_with_decay', confetti_with_decay.ConfettiWithDecay),
        ('lightning_storm', lightning_storm.LightningStorm),
        ('candle_bank', candle_bank.CandleBank),
        ('colliding_particles', colliding_particles.CollidingParticles),
        ('expanding_ripples', expanding_ripples.ExpandingRipples),
        ('cellular_automaton', cellular_automaton.CellularAutomaton),
        ('reaction_diffusion_strip', reaction_diffusion_strip.ReactionDiffusionStrip),
        ('packet_traffic', packet_traffic.PacketTraffic),
    ],
)
def test_builder_constructs_one_d_animation(
    name: config.AnimationName, expected_type: type[animation.Animation]
) -> None:
    source = build.build_animation(config.AnimateConfig(animation=name, seed=3))

    assert isinstance(source, expected_type)
