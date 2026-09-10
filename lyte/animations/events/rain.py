from __future__ import annotations

import random
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, Family, State, float_color_from_rgb
from ..colors import RGB
from ..validators import validate_palette


class RainState(State):
    generator: random.Random
    pixels: NDArray[np.float32]
    wait: float = 0


class Rain(Animation[RainState], frozen=True):
    family: ClassVar[Family] = Family.EVENTS

    colors: tuple[RGB, ...] = ((70, 70, 70), (35, 35, 35), (80, 20, 20), (20, 80, 20))
    rate: float = 10
    seed: int | None = None

    @model_validator(mode='after')
    def validate_rain(self) -> Rain:
        validate_palette(self.colors)
        if self.rate <= 0:
            raise ValueError('rate must be greater than zero')
        return self

    def initial_state(self, device: Device) -> RainState:
        return RainState(
            generator=random.Random(self.seed),
            pixels=np.zeros((device.led_count, 3), dtype=np.float32),
        )

    def render(self, device: Device, state: RainState) -> NDArray[np.float32]:
        state.wait -= 1 / state.fps
        if state.wait <= 0:
            index = state.generator.randrange(device.led_count)
            state.pixels[index] = float_color_from_rgb(
                state.generator.choice(self.colors)
            )
            state.wait = state.generator.expovariate(self.rate)
        state.frame += 1
        return state.pixels
