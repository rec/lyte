from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, State, float_color_from_rgb
from ..colors import wheel_color
from ..validators import resolve_end, validate_step


class LinearRainbowState(State):
    current: int = 0
    frame_buffer: NDArray[np.float32]
    position: int = 0


class LinearRainbow(Animation[LinearRainbowState]):
    max_led: int | None = None
    individual_pixel: bool = False
    step: int = 1

    @model_validator(mode='after')
    def validate_linear_rainbow(self) -> LinearRainbow:
        validate_step(self.step)
        return self

    def initial_state(self, device: Device) -> LinearRainbowState:
        return LinearRainbowState(
            frame_buffer=np.zeros((device.led_count, 3), dtype=np.float32)
        )

    def render(self, device: Device, state: LinearRainbowState) -> NDArray[np.float32]:
        max_led = resolve_end(device.led_count, self.max_led)
        color = float_color_from_rgb(wheel_color(state.position))
        if self.individual_pixel:
            state.frame_buffer[state.current] = color
        else:
            state.frame_buffer[: state.current + 1] = color
        state.position += self.step
        state.current = 0 if state.current == max_led else state.current + self.step
        if state.current > max_led:
            state.current = max_led
        state.frame += 1
        return state.frame_buffer
