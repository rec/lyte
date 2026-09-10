from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State, float_color_from_rgb
from ..colors import wheel_color
from ..validators import resolve_end


class LinearRainbowState(State):
    current: int = 0
    frame_buffer: NDArray[np.float32]
    position: int = 0


class LinearRainbow(effects.LinearRainbow, Animation[LinearRainbowState]):
    family: ClassVar[Family] = Family.FIELDS

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
