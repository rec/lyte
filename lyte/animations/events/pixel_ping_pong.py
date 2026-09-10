from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ... import animation
from ...animation import Family
from ..validators import resolve_end


class PixelPingPongState(animation.State):
    current: int = 0
    frame_buffer: NDArray[np.float32]
    positive: bool = True


class PixelPingPong(effects.PixelPingPong, animation.Animation[PixelPingPongState]):
    family: ClassVar[Family] = Family.EVENTS

    def initial_state(self, device: animation.Device) -> PixelPingPongState:
        return PixelPingPongState(
            frame_buffer=np.zeros((device.led_count, 3), dtype=np.float32)
        )

    def render(
        self, device: animation.Device, state: PixelPingPongState
    ) -> NDArray[np.float32]:
        byte_buffer = animation.byte_light_frame_from_float(state.frame_buffer)
        decrement = np.array(self.color, dtype=np.float64) / self.fade_delay
        faded = byte_buffer.astype(np.float64) - decrement
        state.frame_buffer[:] = (
            np.maximum(faded, 0).astype(np.uint8).astype(np.float32) / 255
        )
        max_led = resolve_end(device.led_count, self.max_led)
        end = min(state.current + self.total_pixels, max_led + 1)
        state.frame_buffer[state.current : end] = animation.float_color_from_rgb(
            self.color
        )
        state.current += 1 if state.positive else -1
        if state.current + self.total_pixels - 1 >= max_led:
            state.positive = False
        if state.current <= 0:
            state.current = 0
            state.positive = True
        state.frame += 1
        return state.frame_buffer
