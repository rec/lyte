from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State, float_color_from_rgb
from ..validators import resolve_end


class AlternatesState(State):
    positive: bool = True


class Alternates(effects.Alternates, Animation[AlternatesState]):
    family: ClassVar[Family] = Family.PATTERNS

    def initial_state(self, device: Device) -> AlternatesState:
        if resolve_end(device.led_count, self.max_led) < 0:
            raise ValueError('max_led must not be negative')
        return AlternatesState()

    def render(self, device: Device, state: AlternatesState) -> NDArray[np.float32]:
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        color1 = float_color_from_rgb(self.color1)
        color2 = float_color_from_rgb(self.color2)
        for i in range(resolve_end(device.led_count, self.max_led) + 1):
            odd = bool(i % 2)
            frame[i] = color1 if odd == state.positive else color2
        state.positive = not state.positive
        state.frame += 1
        return frame
