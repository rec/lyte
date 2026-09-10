from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray

from ...animation import Animation, Device, Family, State


class RandomizeState(State):
    generator: np.random.Generator


class Randomize(Animation[RandomizeState], frozen=True):
    family: ClassVar[Family] = Family.SIMULATIONS

    seed: int | None = None

    def initial_state(self, device: Device) -> RandomizeState:
        return RandomizeState(generator=np.random.default_rng(self.seed))

    def render(self, device: Device, state: RandomizeState) -> NDArray[np.float32]:
        state.frame += 1
        return state.generator.random((device.led_count, 3)).astype(np.float32)
