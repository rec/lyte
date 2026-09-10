from __future__ import annotations

import hashlib
import json
from pathlib import Path

import mido
import numpy as np
import pytest
from numpy import testing

from lyte import animation, daemon_runtime, installation, midi, show
from lyte.animate import build, config
from lyte.animations import compositions
from lyte.animations.patterns.color_fill import ColorFill
from lyte.preview import command
from lyte.preview.config import PreviewConfig


class Counter(animation.Animation[animation.State], frozen=True):
    def render(self, device: animation.Device, state: animation.State) -> np.ndarray:
        state.frame += 1
        return animation.solid_float_light_frame(
            device.led_count, (state.frame / 100, 0, 0)
        )


def test_generator_output_survives_family_reorganization() -> None:
    expected = json.loads(
        Path(__file__).with_name('data').joinpath('generator_baseline.json').read_text()
    )
    for name, digest in expected.items():
        source = build.build_animation(config.AnimateConfig(animation=name, seed=17))
        assert source.family is not None
        actual = hashlib.sha256()
        for count in (32, 250):
            device = animation.Device(led_count=count)
            state = source.initial_state(device)
            state.fps = 20
            for _ in range(24):
                actual.update(
                    animation.byte_light_frame_from_float(
                        source.render(device, state)
                    ).tobytes()
                )
        assert actual.hexdigest() == digest, name


def test_segments_leave_gaps_black_and_reverse_only_the_child() -> None:
    class Ramp(animation.Animation[animation.State], frozen=True):
        def render(
            self, device: animation.Device, state: animation.State
        ) -> np.ndarray:
            return np.repeat(
                np.linspace(0, 1, device.led_count, dtype=np.float32)[:, None],
                3,
                axis=1,
            )

    device = animation.Device(led_count=6)
    source = compositions.Segments(
        sources=[compositions.Reverse(sources=[Ramp()])],
        placements=[compositions.Placement(start=2, led_count=3)],
    )
    frame = source.render(device, source.initial_state(device))
    testing.assert_array_equal(frame[:, 0], [0, 0, 1, 0.5, 0, 0])
    assert frame.flags.c_contiguous
    with pytest.raises(ValueError, match='overlap'):
        compositions.Segments(
            sources=[Ramp(), Ramp()],
            placements=[
                compositions.Placement(start=0, led_count=3),
                compositions.Placement(start=2, led_count=3),
            ],
        )


def test_mix_preserves_gain_clipping_and_independent_states() -> None:
    device = animation.Device(led_count=2)
    child = Counter()
    source = compositions.Mix(sources=[child, child], weights=[0.5, 0.5])
    state = source.initial_state(device)
    testing.assert_allclose(source.render(device, state)[:, 0], 0.01)
    assert state.states[0] is not state.states[1]
    state.weights = [0.1, 0.1]
    testing.assert_allclose(source.render(device, state)[:, 0], 0.004)
    white = ColorFill(color=(255, 255, 255))
    clipped = compositions.Mix(sources=[white, white], weights=[1, 1])
    nested = compositions.Mix(sources=[clipped], weights=[0.5])
    testing.assert_allclose(nested.render(device, nested.initial_state(device)), 0.5)


@pytest.mark.parametrize('fps', [20, 40])
def test_crossfade_endpoints_and_incoming_state_continuation(fps: int) -> None:
    device = animation.Device(led_count=1)
    incoming = Counter()
    source = compositions.Crossfade(
        sources=[ColorFill(color=(0, 255, 0)), incoming],
        fade=compositions.Fade(duration=1),
    )
    state = source.initial_state(device)
    state.fps = fps
    testing.assert_array_equal(source.render(device, state), [[0, 1, 0]])
    for _ in range(fps):
        frame = source.render(device, state)
    testing.assert_allclose(frame[0, 0], (fps + 1) / 100)
    testing.assert_allclose(frame[0, 1], 0, atol=1e-6)
    testing.assert_allclose(
        incoming.render(device, state.states[1])[0, 0], (fps + 2) / 100
    )


def test_sequence_delays_start_and_keeps_state_after_overlap() -> None:
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


@pytest.mark.parametrize('fps', [20, 40])
def test_envelope_uses_seconds_and_can_control_whole_composition(fps: int) -> None:
    device = animation.Device(led_count=1)
    source = compositions.Envelope(
        sources=[ColorFill(color=(255, 255, 255))],
        points=[
            compositions.EnvelopePoint(time=0, gain=0),
            compositions.EnvelopePoint(time=1, gain=0.5),
        ],
        repeat=True,
    )
    state = source.initial_state(device)
    state.fps = fps
    for _ in range(fps // 2 + 1):
        frame = source.render(device, state)
    testing.assert_allclose(frame, 0.25)


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
    selector.receive(mido.Message('program_change'))
    selector.receive(mido.Message('note_off', note=60))
    assert not selector.render(device, 2).any()
    selector.receive(mido.Message('note_on', note=60, velocity=100))
    selector.receive(mido.Message('program_change'))
    selector.clear_performance()
    assert not selector.render(device, 2).any()


def test_example_graph_renders_identically_in_preview_and_playback(
    tmp_path: Path,
) -> None:
    path = Path('examples/composition.toml')
    source = build.build_animation(
        config.AnimateConfig(animation='composition', composition_file=path)
    )
    assert source.family == animation.Family.COMPOSITIONS
    offline = show.create_show_playback(
        show.load_show_file(path), show.build_show_graph(show.load_show_file(path))
    )
    state = source.initial_state(animation.Device(led_count=250))
    for _ in range(8):
        expected = show.render_show_target(offline.targets[0])
        frame = source.render(offline.targets[0].device, state)
        testing.assert_array_equal(frame, expected)
        testing.assert_allclose(frame[:125], frame[125:][::-1])
    output = tmp_path / 'preview.html'
    command.run_preview(
        PreviewConfig(
            animation='composition',
            composition_file=path,
            output=output,
            width=250,
            height=1,
            duration=1,
            fps=2,
        )
    )
    assert '<canvas' in output.read_text()


def test_installation_pixel_program_can_mix_named_sources() -> None:
    config = installation.parse_installation(
        {
            'twinkly': {'tree': {'host': '192.0.2.1', 'led_count': 3}},
            'programs': {
                'red': {
                    'kind': 'pixel',
                    'impl': 'lyte.animations.patterns.color_fill.ColorFill',
                    'params': {'color': [255, 0, 0]},
                },
                'green': {
                    'kind': 'pixel',
                    'impl': 'lyte.animations.patterns.color_fill.ColorFill',
                    'params': {'color': [0, 255, 0]},
                },
                'main': {
                    'kind': 'pixel',
                    'impl': 'lyte.animations.compositions.Mix',
                    'sources': ['red', 'green'],
                    'params': {'weights': [0.25, 0.75]},
                },
            },
            'run': {'tree': {'program': 'main'}},
        }
    )
    runtime = installation.build_runtime(config)
    testing.assert_array_equal(runtime.targets[0].render(), [[64, 191, 0]] * 3)


def test_family_listing_excludes_other_families(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command.print_preview_patterns(animation.Family.FIELDS)
    names = capsys.readouterr().out.splitlines()
    assert 'aurora' in names
    assert 'linear_gradient' in names
    assert 'color_chase' not in names
    assert 'composition' not in names


def test_sequence_rejects_three_overlapping_cues() -> None:
    with pytest.raises(ValueError, match='at most two'):
        compositions.Sequence(
            sources=[Counter()] * 3,
            cues=[compositions.Cue(start=i, duration=3) for i in range(3)],
        )
