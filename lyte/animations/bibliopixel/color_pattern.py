from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, State
from ..colors import DEFAULT_PATTERN, RGB
from ..validators import validate_palette


class ColorPatternState(State):
    offset: int = 0


class ColorPattern(Animation[ColorPatternState]):
    colors: tuple[RGB, ...] = DEFAULT_PATTERN
    width: int = 1
    reverse: bool = False

    @model_validator(mode='after')
    def validate_color_pattern(self) -> ColorPattern:
        validate_palette(self.colors)
        if self.width < 1:
            raise ValueError('width must be at least 1')
        return self

    def initial_state(self, device: Device) -> ColorPatternState:
        return ColorPatternState()

    def render(self, device: Device, state: ColorPatternState) -> NDArray[np.uint8]:
        frame = np.empty((device.led_count, 3), dtype=np.uint8)
        total_width = self.width * len(self.colors)
        for i in range(device.led_count):
            color_index = ((i + state.offset) % total_width) // self.width
            frame[i] = self.colors[color_index]
        state.offset += -1 if self.reverse else 1
        state.frame += 1
        return frame
