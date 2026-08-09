from __future__ import annotations

import unittest

import numpy as np
from numpy import testing as npt
from numpy.typing import NDArray

from lyte import animation
from lyte.animations import bibliopixel


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


class BiblioPixelTests(unittest.TestCase):
    def test_color_fill_fills_all_leds(self) -> None:
        animation = bibliopixel.ColorFill(color=(1, 2, 3))
        device, state = initial_state(animation, 3)

        npt.assert_array_equal(
            render(animation, device, state),
            np.array([[1, 2, 3], [1, 2, 3], [1, 2, 3]], dtype=np.uint8),
        )

    def test_color_chase_moves_lit_window(self) -> None:
        chase = bibliopixel.ColorChase(color=(9, 8, 7), width=2)
        device, state = initial_state(chase, 5)

        npt.assert_array_equal(
            render(chase, device, state),
            np.array(
                [[9, 8, 7], [9, 8, 7], [0, 0, 0], [0, 0, 0], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )
        npt.assert_array_equal(
            render(chase, device, state),
            np.array(
                [[0, 0, 0], [9, 8, 7], [9, 8, 7], [0, 0, 0], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )

    def test_color_wipe_preserves_previous_lit_leds(self) -> None:
        wipe = bibliopixel.ColorWipe(color=(1, 2, 3))
        device, state = initial_state(wipe, 4)

        npt.assert_array_equal(
            render(wipe, device, state),
            np.array(
                [[1, 2, 3], [0, 0, 0], [0, 0, 0], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )
        npt.assert_array_equal(
            render(wipe, device, state),
            np.array(
                [[1, 2, 3], [1, 2, 3], [0, 0, 0], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )

    def test_alternates_flips_each_frame(self) -> None:
        source = bibliopixel.Alternates(color1=(1, 1, 1), color2=(2, 2, 2))
        device, state = initial_state(source, 4)

        npt.assert_array_equal(
            render(source, device, state),
            np.array(
                [[2, 2, 2], [1, 1, 1], [2, 2, 2], [1, 1, 1]],
                dtype=np.uint8,
            ),
        )
        npt.assert_array_equal(
            render(source, device, state),
            np.array(
                [[1, 1, 1], [2, 2, 2], [1, 1, 1], [2, 2, 2]],
                dtype=np.uint8,
            ),
        )

    def test_color_pattern_repeats_color_widths(self) -> None:
        pattern = bibliopixel.ColorPattern(
            colors=((1, 0, 0), (0, 2, 0), (0, 0, 3)),
            width=2,
        )
        device, state = initial_state(pattern, 6)

        npt.assert_array_equal(
            render(pattern, device, state),
            np.array(
                [[1, 0, 0], [1, 0, 0], [0, 2, 0], [0, 2, 0], [0, 0, 3], [0, 0, 3]],
                dtype=np.uint8,
            ),
        )
        npt.assert_array_equal(
            render(pattern, device, state),
            np.array(
                [[1, 0, 0], [0, 2, 0], [0, 2, 0], [0, 0, 3], [0, 0, 3], [1, 0, 0]],
                dtype=np.uint8,
            ),
        )

    def test_color_fade_scales_color_across_span(self) -> None:
        fade = bibliopixel.ColorFade(
            colors=((10, 20, 30),),
            level_step=225,
            start=1,
            end=2,
        )
        device, state = initial_state(fade, 4)

        npt.assert_array_equal(
            render(fade, device, state),
            np.array(
                [[0, 0, 0], [1, 2, 4], [1, 2, 4], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )

    def test_party_mode_alternates_color_and_blank_frames(self) -> None:
        party = bibliopixel.PartyMode(colors=((1, 2, 3), (4, 5, 6)))
        device, state = initial_state(party, 2)

        npt.assert_array_equal(
            render(party, device, state),
            np.array([[1, 2, 3], [1, 2, 3]], dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(party, device, state),
            np.zeros((2, 3), dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(party, device, state),
            np.array([[4, 5, 6], [4, 5, 6]], dtype=np.uint8),
        )

    def test_fire_flies_lights_seeded_random_pixels(self) -> None:
        source = bibliopixel.FireFlies(
            colors=((1, 2, 3),),
            width=2,
            count=1,
            seed=1,
        )
        device, state = initial_state(source, 5)

        frame = render(source, device, state)

        self.assertEqual(frame.shape, (5, 3))
        self.assertGreaterEqual(np.count_nonzero(frame[:, 0]), 1)
        self.assertLessEqual(np.count_nonzero(frame[:, 0]), 2)

    def test_saber_blade_extends_then_retracts(self) -> None:
        saber = bibliopixel.SaberBlade(colors=((1, 2, 3),), speed=1)
        device, state = initial_state(saber, 3)

        npt.assert_array_equal(
            render(saber, device, state),
            np.zeros((3, 3), dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(saber, device, state),
            np.array([[1, 2, 3], [0, 0, 0], [0, 0, 0]], dtype=np.uint8),
        )

    def test_rainbows_generate_wheel_frames(self) -> None:
        source = bibliopixel.Rainbow()
        cycle = bibliopixel.RainbowCycle()
        device, state = initial_state(source, 3)
        cycle_device, cycle_state = initial_state(cycle, 3)

        npt.assert_array_equal(
            render(source, device, state),
            np.array([[255, 0, 0], [252, 3, 0], [249, 6, 0]], dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(cycle, cycle_device, cycle_state),
            np.array([[255, 0, 0], [0, 255, 0], [0, 0, 255]], dtype=np.uint8),
        )

    def test_linear_rainbow_fills_progressively(self) -> None:
        source = bibliopixel.LinearRainbow()
        device, state = initial_state(source, 3)

        npt.assert_array_equal(
            render(source, device, state),
            np.array([[255, 0, 0], [0, 0, 0], [0, 0, 0]], dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(source, device, state),
            np.array([[252, 3, 0], [252, 3, 0], [0, 0, 0]], dtype=np.uint8),
        )

    def test_halves_rainbow_expands_from_center(self) -> None:
        source = bibliopixel.HalvesRainbow()
        device, state = initial_state(source, 5)

        npt.assert_array_equal(
            render(source, device, state),
            np.array(
                [[0, 0, 0], [0, 0, 0], [255, 0, 0], [0, 0, 0], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )
        npt.assert_array_equal(
            render(source, device, state),
            np.array(
                [[0, 0, 0], [240, 15, 0], [255, 0, 0], [240, 15, 0], [0, 0, 0]],
                dtype=np.uint8,
            ),
        )

    def test_larson_scanner_bounces_lit_pixel(self) -> None:
        scanner = bibliopixel.LarsonScanner(color=(1, 2, 3), tail=0)
        device, state = initial_state(scanner, 3)

        npt.assert_array_equal(
            render(scanner, device, state),
            np.array([[1, 2, 3], [0, 0, 0], [0, 0, 0]], dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(scanner, device, state),
            np.array([[0, 0, 0], [1, 2, 3], [0, 0, 0]], dtype=np.uint8),
        )

    def test_pulse_starts_when_chance_always_hits(self) -> None:
        source = bibliopixel.Pulse(
            colors=((10, 20, 30),),
            tail=0,
            chance=100,
            min_speed=1,
            max_speed=2,
            seed=1,
        )
        device, state = initial_state(source, 4)

        frame = render(source, device, state)

        self.assertGreater(np.count_nonzero(frame), 0)

    def test_pixel_ping_pong_fades_previous_pixels(self) -> None:
        ping_pong = bibliopixel.PixelPingPong(color=(10, 0, 0), fade_delay=1)
        device, state = initial_state(ping_pong, 3)

        npt.assert_array_equal(
            render(ping_pong, device, state),
            np.array([[10, 0, 0], [0, 0, 0], [0, 0, 0]], dtype=np.uint8),
        )
        npt.assert_array_equal(
            render(ping_pong, device, state),
            np.array([[0, 0, 0], [10, 0, 0], [0, 0, 0]], dtype=np.uint8),
        )

    def test_searchlights_blend_moving_beams(self) -> None:
        source = bibliopixel.Searchlights(
            colors=((10, 0, 0), (0, 20, 0), (0, 0, 30)),
            tail=0,
            seed=1,
        )
        device, state = initial_state(source, 8)

        frame = render(source, device, state)

        self.assertEqual(frame.shape, (8, 3))
        self.assertGreater(np.count_nonzero(frame), 0)

    def test_wave_generates_sine_colored_frame(self) -> None:
        source = bibliopixel.Wave(color=(10, 20, 30), cycles=1)
        device, state = initial_state(source, 3)

        npt.assert_array_equal(
            render(source, device, state),
            np.array([[10, 20, 30], [10, 20, 30], [10, 20, 30]], dtype=np.uint8),
        )

    def test_twinkle_lights_seeded_random_pixel(self) -> None:
        source = bibliopixel.Twinkle(
            colors=((10, 20, 30),),
            density=100,
            speed=10,
            seed=1,
        )
        device, state = initial_state(source, 4)

        frame = render(source, device, state)

        self.assertGreater(np.count_nonzero(frame), 0)

    def test_white_twinkle_uses_white_pixels(self) -> None:
        source = bibliopixel.WhiteTwinkle(density=100, speed=10, seed=1)
        device, state = initial_state(source, 4)

        frame = render(source, device, state)

        self.assertGreater(np.count_nonzero(frame), 0)
        self.assertTrue(np.all(frame[frame > 0] == int(np.max(frame))))
