from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, Family, State, float_color_from_rgb
from ..colors import RGB
from ..validators import validate_rgb


class ExponentialFadeState(State):
    pixels: NDArray[np.float32]


class ExponentialFade(Animation[ExponentialFadeState], frozen=True):
    family: ClassVar[Family] = Family.FIELDS

    ratio: float = 0.98
    color: RGB = (255, 0, 0)

    @model_validator(mode='after')
    def validate_exponential_fade(self) -> ExponentialFade:
        if not 0 <= self.ratio < 1:
            raise ValueError('ratio must be between zero and one')
        validate_rgb(self.color)
        return self

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
