import json
from pathlib import Path

import numpy as np
from numpy import testing
from pydantic import TypeAdapter
from ufor import effects

from lyte import animation
from lyte.animate import build


def test_ufor_effect_reference_frames() -> None:
    fixture = json.loads(Path('tests/data/ufor_effect_frames.json').read_text())
    metadata = fixture['metadata']
    tolerance = metadata['absolute_tolerance']
    for expected in fixture['cases'].values():
        description = TypeAdapter(effects.EffectValue).validate_python(
            expected['settings']
        )
        source = build.build_effect(description)
        device = animation.Device(led_count=metadata['lights'])
        state = source.initial_state(device)
        state.fps = metadata['logical_rate']
        frames = [source.render(device, state) for _ in range(metadata['frames'])]

        testing.assert_allclose(
            np.asarray([f.sum(axis=0) for f in frames]),
            expected['component_sums'],
            rtol=0,
            atol=tolerance,
        )
        testing.assert_allclose(
            np.asarray([f[0] for f in frames]),
            expected['first_light'],
            rtol=0,
            atol=tolerance,
        )
        testing.assert_allclose(
            np.asarray([f[-1] for f in frames]),
            expected['last_light'],
            rtol=0,
            atol=tolerance,
        )
