from __future__ import annotations

import random
import unittest

import numpy as np
from numpy import testing as npt
from numpy.typing import NDArray

from lyte import animation
from lyte.animations.christmas import hamiltonian
from lyte.animations.christmas.random_walk import RandomWalk, perturb


def render(
    source: animation.Animation,
    device: animation.Device,
    state: animation.State,
) -> NDArray[np.uint8]:
    return animation.byte_light_frame_from_float(source.render(device, state))


def initial_state(
    source: animation.Animation, led_count: int
) -> tuple[animation.Device, animation.State]:
    device = animation.Device(led_count=led_count)
    return device, source.initial_state(device)


class ChristmasAnimationTests(unittest.TestCase):
    def test_ported_animations_render_float_frames(self) -> None:
        from lyte.animations.christmas import effects, gradients

        device = animation.Device(led_count=4)
        sources = [
            effects.ExponentialFade(),
            effects.GreyCode(),
            effects.Rain(seed=1),
            effects.Randomize(seed=1),
            gradients.LinearGradient(),
            gradients.LogGradient(),
        ]

        for source in sources:
            state = source.initial_state(device)
            frame = source.render(device, state)
            self.assertEqual(frame.shape, (4, 3))
            self.assertEqual(frame.dtype, np.float32)
            self.assertTrue(frame.flags.c_contiguous)


class HamiltonianTests(unittest.TestCase):
    def test_next_hamiltonian_matches_loop_special_case(self) -> None:
        self.assertEqual(hamiltonian.next_hamiltonian(4, 1, 0, 0), (0, 0, 0))
        self.assertEqual(hamiltonian.next_hamiltonian(4, 1, 0, 1), (2, 0, 1))

    def test_counter_produces_scaled_rgb_values(self) -> None:
        counter = hamiltonian.HamiltonianCounter(n=4)

        self.assertEqual(counter.next_color(), (0, 0, 0))
        self.assertEqual(counter.next_color(), (0, 0, 64))
        self.assertEqual(counter.next_color(), (0, 0, 128))

    def test_hamiltonian_colors_generates_one_full_cycle(self) -> None:
        colors = list(hamiltonian.hamiltonian_colors(n=4))

        self.assertEqual(len(colors), 64)
        self.assertEqual(colors[:3], [(0, 0, 0), (0, 0, 64), (0, 0, 128)])

    def test_counter_supports_order_and_inversion(self) -> None:
        counter = hamiltonian.HamiltonianCounter(n=4, order='bgr', inverted='r')

        self.assertEqual(counter.next_color(), (192, 0, 0))
        self.assertEqual(counter.next_color(), (128, 0, 0))

    def test_parse_order_rejects_invalid_orders(self) -> None:
        with self.assertRaises(ValueError):
            hamiltonian.parse_order('rrg')

    def test_hamiltonian_returns_one_rgb_triplet_per_led(self) -> None:
        animation = hamiltonian.Hamiltonian(n=4, speed=4)
        device, state = initial_state(animation, 3)
        state.fps = 4

        npt.assert_array_equal(
            render(animation, device, state),
            np.zeros((3, 3), dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(animation, device, state),
            np.zeros((3, 3), dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(animation, device, state),
            np.array([[0, 0, 0], [0, 0, 0], [0, 0, 64]], dtype=np.uint8),
        )


class RandomWalkTests(unittest.TestCase):
    def test_perturb_matches_original_random_step(self) -> None:
        generator = random.Random(1)

        self.assertAlmostEqual(perturb(0, 5, (0, 10), generator), -3.656357558875988)
        self.assertAlmostEqual(perturb(9, 5, (0, 10), generator), 5.525662630627673)

    def test_next_color_returns_current_color_before_advancing(self) -> None:
        walk = RandomWalk(color=(10.0, 20.0, 30.0), variance=0)
        device = animation.Device(led_count=1)
        state = walk.initial_state(device)

        self.assertEqual(walk.next_color(state, 0), (10.0, 20.0, 30.0))
        self.assertEqual(walk.next_color(state, 1), (10.0, 20.0, 30.0))

    def test_render_streams_walk_through_leds(self) -> None:
        walk = RandomWalk(speed=1, color=(10.0, 20.0, 30.0), variance=0)
        device, state = initial_state(walk, 2)
        state.fps = 1

        npt.assert_array_equal(
            render(walk, device, state),
            np.zeros((2, 3), dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(walk, device, state),
            np.array([[0, 0, 0], [10, 20, 30]], dtype=np.uint8),
        )


class HamiltonianAnimationTests(unittest.TestCase):
    def test_hamiltonian_renders_rgb_frame(self) -> None:
        animation = hamiltonian.Hamiltonian(speed=64, n=4)
        device, state = initial_state(animation, 3)
        state.fps = 1

        frame = render(animation, device, state)

        self.assertEqual(frame.shape, (3, 3))
        self.assertEqual(frame.dtype, np.uint8)
