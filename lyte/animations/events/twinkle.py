from __future__ import annotations

import random
from collections.abc import Sequence
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel
from ufor import effects

from ...animation import Animation, Device, Family, State, float_color_from_rgb
from ..colors import RGB, scale_color


class TwinklePixel(BaseModel):
    direction: int = 0
    color: RGB = (0, 0, 0)
    level: int = 0


class TwinkleState(State):
    pixels: list[TwinklePixel]
    random: random.Random


class Twinkle(effects.Twinkle, Animation[TwinkleState]):
    family: ClassVar[Family] = Family.EVENTS

    @property
    def bounded_speed(self) -> int:
        return max(2, min(100, self.speed))

    @property
    def bounded_density(self) -> int:
        return max(2, min(100, self.density))

    @property
    def bounded_max_bright(self) -> int:
        return max(5, min(255, self.max_bright))

    def initial_state(self, device: Device) -> TwinkleState:
        return TwinkleState(
            pixels=[TwinklePixel() for _ in range(device.led_count)],
            random=random.Random(self.seed),
        )

    def render(self, device: Device, state: TwinkleState) -> NDArray[np.float32]:
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        pick_twinkle_led(state, self.colors, self.bounded_density, self.bounded_speed)
        for i, pixel in enumerate(state.pixels):
            if pixel.direction == 1:
                pixel.level += self.bounded_speed
                if pixel.level > self.bounded_max_bright:
                    pixel.level = self.bounded_max_bright
                    pixel.direction = 2
                frame[i] = float_color_from_rgb(scale_color(pixel.color, pixel.level))
            elif pixel.direction == 2:
                pixel.level -= self.bounded_speed
                if pixel.level < 0:
                    pixel.level = 0
                    pixel.direction = 0
                frame[i] = float_color_from_rgb(scale_color(pixel.color, pixel.level))
        state.frame += 1
        return frame


def pick_twinkle_led(
    state: TwinkleState,
    colors: Sequence[Sequence[int]],
    density: int,
    speed: int,
) -> None:
    index = state.random.randrange(0, len(state.pixels))
    pixel = state.pixels[index]
    if state.random.randrange(0, 100) < density and pixel.direction == 0:
        pixel.direction = 1
        color = state.random.choice(colors)
        pixel.color = color[0], color[1], color[2]
        pixel.level += speed
