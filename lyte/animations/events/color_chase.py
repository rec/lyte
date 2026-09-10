from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State, float_color_from_rgb
from .. import validators


class ColorChaseState(State):
    position: int = 0


class ColorChase(effects.ColorChase, Animation[ColorChaseState]):
    family: ClassVar[Family] = Family.EVENTS

    def initial_state(self, device: Device) -> ColorChaseState:
        validators.validate_span(
            device.led_count,
            self.start,
            validators.resolve_end(device.led_count, self.end),
        )
        return ColorChaseState()

    def render(self, device: Device, state: ColorChaseState) -> NDArray[np.float32]:
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        color = float_color_from_rgb(self.color)
        end = validators.resolve_end(device.led_count, self.end)
        position = self.start + state.position
        for i in range(self.width):
            index = position + i
            if self.start <= index <= end:
                frame[index] = color
        state.position = validators.advance_position(
            self.start, end, state.position, self.step
        )
        state.frame += 1
        return frame
