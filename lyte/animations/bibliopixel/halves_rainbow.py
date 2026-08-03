from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, State
from ..colors import wheel_color
from ..validators import resolve_end, validate_step


class HalvesRainbowState(State):
    current: int = 0
    frame_buffer: NDArray[np.uint8]
    position: int = 0


class HalvesRainbow(Animation[HalvesRainbowState]):
    max_led: int | None = None
    center_out: bool = True
    rainbow_inc: int = 4
    step: int = 1

    @model_validator(mode='after')
    def validate_halves_rainbow(self) -> HalvesRainbow:
        validate_step(self.step)
        if self.rainbow_inc < 0:
            raise ValueError('rainbow_inc must not be negative')
        return self

    def initial_state(self, device: Device) -> HalvesRainbowState:
        return HalvesRainbowState(
            frame_buffer=np.zeros((device.led_count, 3), dtype=np.uint8)
        )

    def render(self, device: Device, state: HalvesRainbowState) -> NDArray[np.uint8]:
        max_led = resolve_end(device.led_count, self.max_led)
        color = wheel_color(state.position)
        center = max_led / 2
        center_floor = math.floor(center)
        center_ceil = math.ceil(center)
        if self.center_out:
            state.frame_buffer[int(center_floor - state.current)] = color
            state.frame_buffer[int(center_ceil + state.current)] = color
        else:
            state.frame_buffer[state.current] = color
            state.frame_buffer[max_led - state.current] = color
        state.position += self.step + self.rainbow_inc
        state.current = (
            0 if state.current == center_floor else state.current + self.step
        )
        if state.current > center_floor:
            state.current = center_floor
        state.frame += 1
        return state.frame_buffer
