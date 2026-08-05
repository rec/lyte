from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import (
    Animation,
    Device,
    State,
    byte_light_frame_from_float,
    float_color_from_rgb,
)
from ..colors import RGB
from ..validators import resolve_end, validate_rgb


class PixelPingPongState(State):
    current: int = 0
    frame_buffer: NDArray[np.float32]
    positive: bool = True


class PixelPingPong(Animation[PixelPingPongState]):
    color: RGB = (255, 255, 255)
    max_led: int | None = None
    total_pixels: int = 1
    fade_delay: int = 1

    @model_validator(mode='after')
    def validate_pixel_ping_pong(self) -> PixelPingPong:
        validate_rgb(self.color)
        if self.total_pixels < 1:
            raise ValueError('total_pixels must be at least 1')
        if self.fade_delay < 1:
            raise ValueError('fade_delay must be at least 1')
        return self

    def initial_state(self, device: Device) -> PixelPingPongState:
        return PixelPingPongState(
            frame_buffer=np.zeros((device.led_count, 3), dtype=np.float32)
        )

    def render(self, device: Device, state: PixelPingPongState) -> NDArray[np.float32]:
        byte_buffer = byte_light_frame_from_float(state.frame_buffer)
        decrement = np.array(self.color, dtype=np.float64) / self.fade_delay
        faded = byte_buffer.astype(np.float64) - decrement
        state.frame_buffer[:] = (
            np.maximum(faded, 0).astype(np.uint8).astype(np.float32) / 255
        )
        max_led = resolve_end(device.led_count, self.max_led)
        end = min(state.current + self.total_pixels, max_led + 1)
        state.frame_buffer[state.current : end] = float_color_from_rgb(self.color)
        state.current += 1 if state.positive else -1
        if state.current + self.total_pixels - 1 >= max_led:
            state.positive = False
        if state.current <= 0:
            state.current = 0
            state.positive = True
        state.frame += 1
        return state.frame_buffer
