from __future__ import annotations

import random
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State, float_color_from_rgb


class RainState(State):
    generator: random.Random
    pixels: NDArray[np.float32]
    wait: float = 0


class Rain(effects.Rain, Animation[RainState]):
    family: ClassVar[Family] = Family.EVENTS

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
