from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from lyte import animation, reactive_effects, reactivity

FEATURES = reactivity.AudioFeatures(
    level=0.7,
    bass=0.9,
    mid=0.5,
    treble=0.3,
    onset=0.8,
    beat=1,
    spectrum=[index / 15 for index in range(16)],
)


@pytest.mark.parametrize('factory', list(reactive_effects.EFFECTS.values()))
def test_reactive_catalogue_renders_valid_changing_one_dimensional_frames(
    factory: Callable[[], reactive_effects.AudioReactiveAnimation],
) -> None:
    source = factory()
    device = animation.Device(led_count=32)
    state = source.initial_state(device)
    state.fps = 30

    frames = []
    for _ in range(6):
        reactive_effects.update_features(state, FEATURES)
        frames.append(source.render(device, state))

    for frame in frames:
        animation.validate_frame(device, frame)
    assert any(np.any(frame) for frame in frames)
    assert any(not np.array_equal(frames[0], frame) for frame in frames[1:])


@pytest.mark.parametrize('factory', list(reactive_effects.EFFECTS.values()))
def test_reactive_catalogue_supports_a_single_light(
    factory: Callable[[], reactive_effects.AudioReactiveAnimation],
) -> None:
    source = factory()
    device = animation.Device(led_count=1)
    state = source.initial_state(device)
    reactive_effects.update_features(state, FEATURES)

    animation.validate_frame(device, source.render(device, state))
