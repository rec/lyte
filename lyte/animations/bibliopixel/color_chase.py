from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, State
from ..colors import RGB
from ..validators import (
    advance_position,
    resolve_end,
    validate_rgb,
    validate_span,
    validate_start,
    validate_step,
)


class ColorChaseState(State):
    position: int = 0


class ColorChase(Animation[ColorChaseState]):
    color: RGB = (255, 0, 0)
    width: int = 1
    start: int = 0
    end: int | None = None
    step: int = 1

    @model_validator(mode='after')
    def validate_color_chase(self) -> ColorChase:
        validate_rgb(self.color)
        validate_step(self.step)
        if self.width < 1:
            raise ValueError('width must be at least 1')
        validate_start(self.start)
        return self

    def initial_state(self, device: Device) -> ColorChaseState:
        validate_span(
            device.led_count, self.start, resolve_end(device.led_count, self.end)
        )
        return ColorChaseState()

    def render(self, device: Device, state: ColorChaseState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        end = resolve_end(device.led_count, self.end)
        position = self.start + state.position
        for i in range(self.width):
            index = position + i
            if self.start <= index <= end:
                frame[index] = self.color
        state.position = advance_position(self.start, end, state.position, self.step)
        state.frame += 1
        return frame
