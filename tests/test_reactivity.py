from __future__ import annotations

import numpy as np

from lyte import reactivity


def test_audio_analyzer_separates_a_low_frequency_signal() -> None:
    rate = 48_000
    time = np.arange(rate // 10, dtype=np.float32) / rate
    samples = np.sin(2 * np.pi * 100 * time).astype(np.float32)

    features = reactivity.AudioAnalyzer().analyze(samples, rate)

    assert features.level > 0.6
    assert features.bass > features.mid
    assert features.bass > features.treble
    assert len(features.spectrum) == 16


def test_gradient_blend_and_filters_keep_one_dimensional_frame_shape() -> None:
    gradient = reactivity.Gradient(
        stops=[
            reactivity.GradientStop(position=0, color=[1, 0, 0]),
            reactivity.GradientStop(position=1, color=[0, 0, 1]),
        ]
    )
    positions = np.linspace(0, 1, 5, dtype=np.float32)
    frame = gradient.sample(positions)

    filtered = reactivity.mirror(reactivity.blur(frame, 1))
    masked = reactivity.apply_mask(
        filtered, np.array([0, 0.5, 1, 0.5, 0], dtype=np.float32)
    )
    result = reactivity.blend([masked, masked], 'add')

    assert result.shape == (5, 3)
    assert result.dtype == np.float32 and result.flags.c_contiguous
    assert not result[0].any() and not result[-1].any()


def test_smoothing_and_background_are_bounded() -> None:
    assert 0 < reactivity.smooth(0, 1, 4, 0.25) < 1
    frame = np.zeros((2, 3), dtype=np.float32)

    result = reactivity.background(frame, (1, 0.5, 0), 0.25)

    assert result.tolist() == [[0.25, 0.125, 0.0], [0.25, 0.125, 0.0]]
