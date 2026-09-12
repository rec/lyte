from pathlib import Path

import mido
import numpy as np
import pytest

from lyte import animation, patches


def make_patch(name: str, velocity: int = 100) -> patches.DeclarativeLightPatch:
    library = patches.load_patch_library(Path('patches/wearable-breath.toml'))
    patch = patches.build_light_patch(library, name)
    assert isinstance(patch, patches.DeclarativeLightPatch)
    patch.fps = 20
    patch.receive(mido.Message('note_on', note=60, velocity=velocity))
    return patch


def render(patch: patches.DeclarativeLightPatch) -> np.ndarray:
    return patch.render(animation.Device(led_count=250))


@pytest.mark.parametrize(
    'name',
    ['velocity_splash', 'breath_bloom', 'pitch_bend_travel', 'note_age_constellation'],
)
def test_reactive_catalogue_lifecycle(name: str) -> None:
    patch = make_patch(name)
    patch.receive(mido.Message('control_change', control=2, value=127))
    frame = render(patch)
    assert frame.shape == (250, 3)
    assert frame.dtype == np.float32 and frame.flags.c_contiguous
    assert np.isfinite(frame).all() and frame.min() >= 0 and frame.max() <= 1
    assert frame[:, 0].max() > 0
    assert not frame[:, 1:].any()
    patch.receive(mido.Message('note_off', note=60))
    assert not render(patch).any()
    patch.receive(mido.Message('note_on', note=64, velocity=100))
    patch.receive(mido.Message('control_change', control=2, value=127))
    assert render(patch)[:, 1].max() > 0


def test_velocity_changes_splash_width_and_brightness() -> None:
    quiet = render(make_patch('velocity_splash', 20))[:, 0]
    loud = render(make_patch('velocity_splash', 127))[:, 0]
    assert loud.max() > quiet.max()
    assert (loud > loud.max() / 2).sum() > (quiet > quiet.max() / 2).sum()


def test_breath_release_contracts_bloom_over_time() -> None:
    patch = make_patch('breath_bloom')
    assert not render(patch).any()
    patch.receive(mido.Message('control_change', control=2, value=127))
    for _ in range(30):
        full = render(patch)[:, 0]
    patch.receive(mido.Message('control_change', control=2, value=0))
    first = render(patch)[:, 0]
    for _ in range(10):
        later = render(patch)[:, 0]
    assert 0 < later.max() < first.max() < full.max()
    assert (later > later.max() / 2).sum() < (full > full.max() / 2).sum()


def test_pitch_travel_reaches_both_ends_and_breath_widens_halo() -> None:
    patch = make_patch('pitch_bend_travel')
    patch.receive(mido.Message('pitchwheel', pitch=-8192))
    left = render(patch)[:40, 0]
    patch.receive(mido.Message('pitchwheel', pitch=8191))
    right = render(patch)[:40, 0]
    assert left.argmax() == 0 and right.argmax() == 39
    patch.receive(mido.Message('control_change', control=2, value=127))
    halo = render(patch)[:40, 0]
    assert halo.max() > right.max()
    assert (halo > halo.max() / 2).sum() > (right > right.max() / 2).sum()


def test_constellation_separates_dims_and_restarts_on_new_note() -> None:
    patch = make_patch('note_age_constellation')
    first = render(patch)
    for _ in range(40):
        aged = render(patch)
    assert aged.max() < first.max()
    assert not np.allclose(aged, first)
    patch.receive(mido.Message('note_on', note=60, velocity=100))
    np.testing.assert_array_equal(render(patch), first)


@pytest.mark.parametrize(
    'name',
    ['velocity_splash', 'breath_bloom', 'pitch_bend_travel', 'note_age_constellation'],
)
def test_reactive_effect_handles_one_light(name: str) -> None:
    source = patches.build_layer_animation(patches.LayerSpec(kind=name, speed=1))
    device = animation.Device(led_count=1)
    state = source.initial_state(device)
    for _ in range(10):
        frame = source.render(device, state)
        animation.validate_frame(device, frame)
        assert 0 <= frame.min() <= frame.max() <= 1


def test_reactive_patch_respects_selected_regions() -> None:
    library = patches.load_patch_library(Path('patches/wearable-breath.toml'))
    specs = dict(library.patches)
    specs['velocity_splash'] = specs['velocity_splash'].model_copy(
        update={'regions': ['chest']}
    )
    patch = patches.build_light_patch(
        library.model_copy(update={'patches': specs}), 'velocity_splash'
    )
    patch.receive(mido.Message('note_on', note=60, velocity=127))
    frame = patch.render(animation.Device(led_count=250))
    assert not frame[:190].any()
    assert frame[190:].max() > 0
