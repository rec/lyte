from __future__ import annotations

import unittest

import numpy as np
from numpy import testing as npt
from numpy.typing import NDArray

from lyte import animation
from lyte.animations import bibliopixel
from lyte.animations.colors import solid_rgb_frame


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


class AnimationFrameTests(unittest.TestCase):
    def test_solid_rgb_frame(self) -> None:
        npt.assert_array_equal(
            solid_rgb_frame(3, 230, 85, 0),
            np.array([[230, 85, 0], [230, 85, 0], [230, 85, 0]], dtype=np.uint8),
        )

    def test_solid_float_light_frame(self) -> None:
        npt.assert_array_equal(
            animation.solid_float_light_frame(2, (1.0, 0.5, 0.0, 0.25)),
            np.array(
                [[1.0, 0.5, 0.0, 0.25], [1.0, 0.5, 0.0, 0.25]],
                dtype=np.float32,
            ),
        )

    def test_validate_float_light_frame_checks_shape_dtype_and_finiteness(
        self,
    ) -> None:
        frame = np.zeros((2, 3), dtype=np.float32)

        self.assertIs(animation.validate_float_light_frame(2, 3, frame), frame)
        with self.assertRaisesRegex(ValueError, 'dtype float32'):
            animation.validate_float_light_frame(2, 3, frame.astype(np.float64))
        with self.assertRaisesRegex(ValueError, 'shape light_count x light channels'):
            animation.validate_float_light_frame(2, 4, frame)
        with self.assertRaisesRegex(ValueError, 'finite'):
            animation.validate_float_light_frame(
                1,
                3,
                np.array([[np.nan, 0.0, 0.0]], dtype=np.float32),
            )
        with self.assertRaisesRegex(ValueError, 'C-contiguous'):
            animation.validate_float_light_frame(
                2, 3, np.zeros((3, 2), dtype=np.float32).T
            )

    def test_byte_light_frame_from_float_clips_rounds_and_contiguates(self) -> None:
        frame = np.array(
            [
                [-0.25, 0.0, 0.5],
                [1.0, 1.25, 128 / 255],
            ],
            dtype=np.float32,
        ).T

        encoded = animation.byte_light_frame_from_float(frame)

        npt.assert_array_equal(
            encoded,
            np.array([[0, 255], [0, 255], [128, 128]], dtype=np.uint8),
        )
        self.assertTrue(encoded.flags.c_contiguous)

    def test_float_rgb_helpers_convert_at_byte_boundary(self) -> None:
        self.assertEqual(
            animation.float_color_from_rgb((255, 128, 0)), (1.0, 128 / 255, 0.0)
        )
        self.assertEqual(
            animation.rgb_from_float_color((1.25, 0.5, -0.25)), (255, 128, 0)
        )
