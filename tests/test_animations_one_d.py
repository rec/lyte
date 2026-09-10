from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest
from numpy.testing import assert_array_equal

from lyte import animation
from lyte.animate import build, config
from lyte.animations import one_d


@pytest.mark.parametrize(
    'factory',
    [
        one_d.FireAndEmbers,
        one_d.Aurora,
        one_d.OceanCurrent,
        one_d.Interference,
        one_d.PaletteConveyor,
        one_d.ConfettiWithDecay,
        one_d.LightningStorm,
        one_d.CandleBank,
        one_d.CollidingParticles,
        one_d.ExpandingRipples,
        one_d.CellularAutomaton,
        one_d.ReactionDiffusionStrip,
        one_d.PacketTraffic,
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
        lambda: one_d.FireAndEmbers(seed=4),
        lambda: one_d.Aurora(seed=4),
        lambda: one_d.OceanCurrent(seed=4),
        one_d.Interference,
        one_d.PaletteConveyor,
        lambda: one_d.ConfettiWithDecay(seed=4),
        lambda: one_d.LightningStorm(seed=4),
        lambda: one_d.CandleBank(seed=4),
        lambda: one_d.CollidingParticles(seed=4),
        lambda: one_d.ExpandingRipples(seed=4),
        lambda: one_d.CellularAutomaton(seed=4),
        lambda: one_d.ReactionDiffusionStrip(seed=4),
        lambda: one_d.PacketTraffic(seed=4),
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
        one_d.FireAndEmbers,
        one_d.Aurora,
        one_d.OceanCurrent,
        one_d.Interference,
        one_d.PaletteConveyor,
        one_d.ConfettiWithDecay,
        one_d.LightningStorm,
        one_d.CandleBank,
        one_d.CollidingParticles,
        one_d.ExpandingRipples,
        one_d.CellularAutomaton,
        one_d.ReactionDiffusionStrip,
        one_d.PacketTraffic,
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
    source = one_d.ConfettiWithDecay(spawn_rate=0, decay=2, speed=1, seed=1)
    device = animation.Device(led_count=4)
    state = source.initial_state(device)
    state.spawn_credit = 0
    state.pixels[1] = 1

    first = source.render(device, state).copy()
    second = source.render(device, state).copy()

    assert 0 < second[1, 0] < first[1, 0] < 1


def test_expanding_ripple_moves_away_from_its_origin() -> None:
    source = one_d.ExpandingRipples(
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
    source = one_d.CellularAutomaton(
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
    first = one_d.ReactionDiffusionStrip(seed=3)
    second = one_d.ReactionDiffusionStrip(seed=3)
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
    source = one_d.PacketTraffic(
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
        ('fire_and_embers', one_d.FireAndEmbers),
        ('aurora', one_d.Aurora),
        ('ocean_current', one_d.OceanCurrent),
        ('interference', one_d.Interference),
        ('palette_conveyor', one_d.PaletteConveyor),
        ('confetti_with_decay', one_d.ConfettiWithDecay),
        ('lightning_storm', one_d.LightningStorm),
        ('candle_bank', one_d.CandleBank),
        ('colliding_particles', one_d.CollidingParticles),
        ('expanding_ripples', one_d.ExpandingRipples),
        ('cellular_automaton', one_d.CellularAutomaton),
        ('reaction_diffusion_strip', one_d.ReactionDiffusionStrip),
        ('packet_traffic', one_d.PacketTraffic),
    ],
)
def test_builder_constructs_one_d_animation(
    name: config.AnimationName, expected_type: type[animation.Animation]
) -> None:
    source = build.build_animation(config.AnimateConfig(animation=name, seed=3))

    assert isinstance(source, expected_type)
