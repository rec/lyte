from __future__ import annotations

import random

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, model_validator

from ...animation import Animation, Device, State
from ..util import DEFAULT_PATTERN, RGB, scale_color, validate_palette


class TwinklePixel(BaseModel):
    direction: int = 0
    color: RGB = (0, 0, 0)
    level: int = 0


class TwinkleState(State):
    pixels: list[TwinklePixel]
    random: random.Random


class Twinkle(Animation[TwinkleState]):
    colors: tuple[RGB, ...] = DEFAULT_PATTERN
    density: int = 20
    speed: int = 2
    max_bright: int = 255
    seed: int | None = None

    @model_validator(mode="after")
    def validate_twinkle(self) -> Twinkle:
        validate_palette(self.colors)
        return self

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

    def render(self, device: Device, state: TwinkleState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        pick_twinkle_led(state, self.colors, self.bounded_density, self.bounded_speed)
        for i, pixel in enumerate(state.pixels):
            if pixel.direction == 1:
                pixel.level += self.bounded_speed
                if pixel.level > self.bounded_max_bright:
                    pixel.level = self.bounded_max_bright
                    pixel.direction = 2
                frame[i] = scale_color(pixel.color, pixel.level)
            elif pixel.direction == 2:
                pixel.level -= self.bounded_speed
                if pixel.level < 0:
                    pixel.level = 0
                    pixel.direction = 0
                frame[i] = scale_color(pixel.color, pixel.level)
        state.frame += 1
        return frame


def pick_twinkle_led(
    state: TwinkleState,
    colors: tuple[RGB, ...],
    density: int,
    speed: int,
) -> None:
    index = state.random.randrange(0, len(state.pixels))
    pixel = state.pixels[index]
    if state.random.randrange(0, 100) < density and pixel.direction == 0:
        pixel.direction = 1
        pixel.color = state.random.choice(colors)
        pixel.level += speed
