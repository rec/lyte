from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, State
from ..colors import RGB, wave_color
from ..validators import (
    resolve_end,
    span_size,
    validate_rgb,
    validate_span,
    validate_start,
)


class WaveState(State):
    move_step: int = 0
    position: int = 0


class Wave(Animation[WaveState]):
    color: RGB = (255, 0, 0)
    cycles: int = 2
    start: int = 0
    end: int | None = None
    moving: bool = False

    @model_validator(mode="after")
    def validate_wave(self) -> Wave:
        validate_rgb(self.color)
        if self.cycles < 1:
            raise ValueError("cycles must be at least 1")
        validate_start(self.start)
        return self

    def initial_state(self, device: Device) -> WaveState:
        validate_span(
            device.led_count, self.start, resolve_end(device.led_count, self.end)
        )
        return WaveState()

    def render(self, device: Device, state: WaveState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        size = span_size(device.led_count, self.start, self.end)
        for i in range(size):
            if self.moving:
                value = math.sin(math.pi * self.cycles * i / size + state.move_step)
            else:
                value = math.sin(math.pi * self.cycles * state.position * i / size)
            frame[self.start + i] = wave_color(self.color, value)
        if self.moving:
            state.move_step += 2
            if state.move_step >= size:
                state.move_step = 0
        else:
            state.position += 1
        state.frame += 1
        return frame
