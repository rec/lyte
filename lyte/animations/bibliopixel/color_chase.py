from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, State, float_color_from_rgb
from .. import validators
from ..colors import RGB


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
        validators.validate_rgb(self.color)
        validators.validate_step(self.step)
        if self.width < 1:
            raise ValueError('width must be at least 1')
        validators.validate_start(self.start)
        return self

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
