from __future__ import annotations

import unittest

import numpy as np
from numpy import testing as npt
from numpy.typing import NDArray

from lyte import animation
from lyte.animations import bibliopixel


class SegmentAnimationTests(unittest.TestCase):
    def test_segments_render_contiguous_frames_with_independent_states(self) -> None:
        class CountingState(animation.State):
            led_count: int

        class CountingAnimation(animation.Animation[CountingState]):
            def initial_state(self, device: animation.Device) -> CountingState:
                return CountingState(led_count=device.led_count)

            def render(
                self, device: animation.Device, state: CountingState
            ) -> NDArray[np.float32]:
                state.frame += 1
                return animation.solid_float_light_frame(
                    device.led_count,
                    (state.frame / 10, device.led_count / 10, state.fps / 100),
                )

        source = CountingAnimation()
        composite = animation.SegmentAnimation(
            segments=[
                animation.AnimationSegment(animation=source, led_count=2),
                animation.AnimationSegment(animation=source, led_count=3),
            ]
        )
        device = animation.Device(led_count=5)
        state = composite.initial_state(device)
        state.fps = 60

        npt.assert_allclose(
            composite.render(device, state),
            np.array(
                [
                    [0.1, 0.2, 0.6],
                    [0.1, 0.2, 0.6],
                    [0.1, 0.3, 0.6],
                    [0.1, 0.3, 0.6],
                    [0.1, 0.3, 0.6],
                ],
                dtype=np.float32,
            ),
        )
        self.assertIsNot(state.states[0], state.states[1])
        self.assertEqual(state.frame, 1)

        npt.assert_allclose(
            composite.render(device, state)[:, 0],
            np.full(5, 0.2, dtype=np.float32),
        )

    def test_requires_at_least_two_segments(self) -> None:
        with self.assertRaisesRegex(ValueError, 'at least two segments'):
            animation.SegmentAnimation(segments=[])

    def test_requires_segment_lengths_to_match_device(self) -> None:
        source = bibliopixel.ColorFill(color=(1, 2, 3))
        composite = animation.SegmentAnimation(
            segments=[
                animation.AnimationSegment(animation=source, led_count=2),
                animation.AnimationSegment(animation=source, led_count=3),
            ]
        )

        with self.assertRaisesRegex(ValueError, 'must total device led_count'):
            composite.initial_state(animation.Device(led_count=4))
