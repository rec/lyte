from __future__ import annotations

import math
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State, float_color_from_rgb
from ..colors import wheel_color
from ..validators import resolve_end


class HalvesRainbowState(State):
    current: int = 0
    frame_buffer: NDArray[np.float32]
    position: int = 0


class HalvesRainbow(effects.HalvesRainbow, Animation[HalvesRainbowState]):
    family: ClassVar[Family] = Family.FIELDS

    def initial_state(self, device: Device) -> HalvesRainbowState:
        return HalvesRainbowState(
            frame_buffer=np.zeros((device.led_count, 3), dtype=np.float32)
        )

    def render(self, device: Device, state: HalvesRainbowState) -> NDArray[np.float32]:
        max_led = resolve_end(device.led_count, self.max_led)
        color = float_color_from_rgb(wheel_color(state.position))
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
