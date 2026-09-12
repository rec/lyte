"""Spawn colored points into a persistent frame that fades exponentially.

Existing points decay between spawns, producing sparse glitter or dense
confetti. Ufor defines palette, spawn rate, decay, width, speed and seed.
Lifetime follows the decay rate rather than a separate lifetime control.
"""

from __future__ import annotations

import math
import random
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State, float_color_from_rgb


class ConfettiWithDecayState(State):
    pixels: NDArray[np.float32]
    generator: random.Random
    spawn_credit: float = 0


class ConfettiWithDecay(effects.ConfettiWithDecay, Animation[ConfettiWithDecayState]):
    family: ClassVar[Family] = Family.EVENTS

    def initial_state(self, device: Device) -> ConfettiWithDecayState:
        return ConfettiWithDecayState(
            pixels=np.zeros((device.led_count, 3), dtype=np.float32),
            generator=random.Random(self.seed),
            spawn_credit=1,
        )

    def render(
        self, device: Device, state: ConfettiWithDecayState
    ) -> NDArray[np.float32]:
        dt = self.speed / state.fps
        state.pixels *= math.exp(-self.decay * dt)
        state.spawn_credit += self.spawn_rate * dt
        spawn_count = int(state.spawn_credit)
        state.spawn_credit -= spawn_count
        for _ in range(spawn_count):
            index = state.generator.randrange(device.led_count)
            color = float_color_from_rgb(state.generator.choice(self.palette))
            state.pixels[index : min(device.led_count, index + self.width)] = color
        state.frame += 1
        return np.ascontiguousarray(np.clip(state.pixels, 0, 1))
