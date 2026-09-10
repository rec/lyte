from __future__ import annotations

import mido
import numpy as np
import pytest
from numpy import testing

from lyte import animation, daemon_runtime, midi
from lyte.animations import compositions
from lyte.animations.patterns.color_fill import ColorFill


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


def test_patch_crossfade_stops_on_note_off_and_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def patch(library: object, name: str) -> midi.LightPatch:
        color = (255, 0, 0) if name == 'red' else (0, 255, 0)
        return midi.RegionLightPatch(
            config=compositions.Segments(
                sources=[ColorFill(color=color)],
                placements=[compositions.Placement(start=0, led_count=1)],
            )
        )

    monkeypatch.setattr(daemon_runtime.patches, 'build_light_patch', patch)
    selector = daemon_runtime.PatchSelector.create(object(), ['red', 'green'], 1)
    device = animation.Device(led_count=1)
    selector.receive(mido.Message('note_on', note=60, velocity=100))
    selector.receive(mido.Message('program_change'))
    testing.assert_array_equal(selector.render(device, 2), [[1, 0, 0]])
    testing.assert_array_equal(selector.render(device, 2), [[0.5, 0.5, 0]])
    selector.receive(mido.Message('note_off', note=61))
    testing.assert_array_equal(selector.render(device, 2), [[0, 1, 0]])
    selector.clear_performance()
    assert not selector.render(device, 2).any()
