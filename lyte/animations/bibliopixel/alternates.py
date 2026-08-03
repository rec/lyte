from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, State
from ..colors import RGB
from ..validators import resolve_end, validate_rgb


class AlternatesState(State):
    positive: bool = True


class Alternates(Animation[AlternatesState]):
    color1: RGB = (255, 255, 255)
    color2: RGB = (0, 0, 0)
    max_led: int | None = None

    @model_validator(mode='after')
    def validate_alternates(self) -> Alternates:
        validate_rgb(self.color1)
        validate_rgb(self.color2)
        return self

    def initial_state(self, device: Device) -> AlternatesState:
        if resolve_end(device.led_count, self.max_led) < 0:
            raise ValueError('max_led must not be negative')
        return AlternatesState()

    def render(self, device: Device, state: AlternatesState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        for i in range(resolve_end(device.led_count, self.max_led) + 1):
            odd = bool(i % 2)
            frame[i] = self.color1 if odd == state.positive else self.color2
        state.positive = not state.positive
        state.frame += 1
        return frame
