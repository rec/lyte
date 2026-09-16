from __future__ import annotations

import numpy as np
from numpy import testing

from lyte import animation
from lyte.animations import compositions


class Counter(animation.ConfiguredAnimation[animation.State], frozen=True):
    def render(self, device: animation.Device, state: animation.State) -> np.ndarray:
        state.frame += 1
        return animation.solid_float_light_frame(
            device.led_count, (state.frame / 100, 0, 0)
        )


def test_internal_mix_keeps_patch_states_independent() -> None:
    device = animation.Device(led_count=2)
    source = compositions.Mix(sources=[Counter(), Counter()], weights=[0.5, 0.5])
    state = source.initial_state(device)

    testing.assert_allclose(source.render(device, state)[:, 0], 0.01)

    assert state.states[0] is not state.states[1]


def test_internal_sequence_delays_start_and_keeps_state_after_overlap() -> None:
    device = animation.Device(led_count=1)
    source = compositions.Sequence(
        sources=[Counter(), Counter()],
        cues=[
            compositions.Cue(start=0.5, duration=1),
            compositions.Cue(start=1, duration=1),
        ],
    )
    state = source.initial_state(device)
    state.fps = 4

    frames = [source.render(device, state)[0, 0] for _ in range(9)]

    testing.assert_allclose(frames, [0, 0, 0.01, 0.02, 0.03, 0.03, 0.03, 0.04, 0])
    assert state.states[1].frame == 4
