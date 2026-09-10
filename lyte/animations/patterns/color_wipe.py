from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State, float_color_from_rgb
from .. import validators


class ColorWipeState(State):
    frame_buffer: NDArray[np.float32]
    position: int = 0


class ColorWipe(effects.ColorWipe, Animation[ColorWipeState]):
    family: ClassVar[Family] = Family.PATTERNS

    def initial_state(self, device: Device) -> ColorWipeState:
        validators.validate_span(
            device.led_count,
            self.start,
            validators.resolve_end(device.led_count, self.end),
        )
        return ColorWipeState(
            frame_buffer=np.zeros((device.led_count, 3), dtype=np.float32)
        )

    def render(self, device: Device, state: ColorWipeState) -> NDArray[np.float32]:
        end = validators.resolve_end(device.led_count, self.end)
        if state.position == 0:
            state.frame_buffer[:] = 0
        for i in range(self.step):
            index = self.start + state.position - i
            if self.start <= index <= end:
                state.frame_buffer[index] = float_color_from_rgb(self.color)
        state.position = validators.advance_position(
            self.start, end, state.position, self.step
        )
        state.frame += 1
        return state.frame_buffer
