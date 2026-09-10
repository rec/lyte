from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State, float_color_from_rgb


class ExponentialFadeState(State):
    pixels: NDArray[np.float32]


class ExponentialFade(effects.ExponentialFade, Animation[ExponentialFadeState]):
    family: ClassVar[Family] = Family.FIELDS

    def initial_state(self, device: Device) -> ExponentialFadeState:
        return ExponentialFadeState(
            pixels=np.zeros((device.led_count, 3), dtype=np.float32)
        )

    def render(
        self, device: Device, state: ExponentialFadeState
    ) -> NDArray[np.float32]:
        state.pixels *= self.ratio
        state.pixels += (1 - self.ratio) * np.array(
            float_color_from_rgb(self.color), dtype=np.float32
        )
        state.frame += 1
        return state.pixels
