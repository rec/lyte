from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, State, float_color_from_rgb
from ..colors import wheel_color
from ..validators import (
    advance_rainbow,
    resolve_end,
    span_size,
    validate_span,
    validate_start,
    validate_step,
)


class RainbowState(State):
    position: int = 0


class Rainbow(Animation[RainbowState]):
    start: int = 0
    end: int | None = None
    step: int = 1

    @model_validator(mode='after')
    def validate_rainbow(self) -> Rainbow:
        validate_step(self.step)
        validate_start(self.start)
        return self

    def initial_state(self, device: Device) -> RainbowState:
        validate_span(
            device.led_count, self.start, resolve_end(device.led_count, self.end)
        )
        return RainbowState()

    def render(self, device: Device, state: RainbowState) -> NDArray[np.float32]:
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        for i in range(span_size(device.led_count, self.start, self.end)):
            frame[self.start + i] = float_color_from_rgb(
                wheel_color((i + state.position) % 255)
            )
        advance_rainbow(state, self.step)
        return frame
