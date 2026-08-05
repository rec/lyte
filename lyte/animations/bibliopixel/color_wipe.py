from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, State, float_color_from_rgb
from ..colors import RGB
from ..validators import (
    advance_position,
    resolve_end,
    validate_rgb,
    validate_span,
    validate_start,
    validate_step,
)


class ColorWipeState(State):
    frame_buffer: NDArray[np.float32]
    position: int = 0


class ColorWipe(Animation[ColorWipeState]):
    color: RGB = (255, 0, 0)
    start: int = 0
    end: int | None = None
    step: int = 1

    @model_validator(mode='after')
    def validate_color_wipe(self) -> ColorWipe:
        validate_rgb(self.color)
        validate_step(self.step)
        validate_start(self.start)
        return self

    def initial_state(self, device: Device) -> ColorWipeState:
        validate_span(
            device.led_count, self.start, resolve_end(device.led_count, self.end)
        )
        return ColorWipeState(
            frame_buffer=np.zeros((device.led_count, 3), dtype=np.float32)
        )

    def render(self, device: Device, state: ColorWipeState) -> NDArray[np.float32]:
        end = resolve_end(device.led_count, self.end)
        if state.position == 0:
            state.frame_buffer[:] = 0
        for i in range(self.step):
            index = self.start + state.position - i
            if self.start <= index <= end:
                state.frame_buffer[index] = float_color_from_rgb(self.color)
        state.position = advance_position(self.start, end, state.position, self.step)
        state.frame += 1
        return state.frame_buffer
