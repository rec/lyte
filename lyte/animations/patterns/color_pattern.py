from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State, float_color_from_rgb


class ColorPatternState(State):
    offset: int = 0


class ColorPattern(effects.ColorPattern, Animation[ColorPatternState]):
    family: ClassVar[Family] = Family.PATTERNS

    def initial_state(self, device: Device) -> ColorPatternState:
        return ColorPatternState()

    def render(self, device: Device, state: ColorPatternState) -> NDArray[np.float32]:
        frame = np.empty((device.led_count, 3), dtype=np.float32)
        colors = [float_color_from_rgb(i) for i in self.colors]
        total_width = self.width * len(self.colors)
        for i in range(device.led_count):
            color_index = ((i + state.offset) % total_width) // self.width
            frame[i] = colors[color_index]
        state.offset += -1 if self.reverse else 1
        state.frame += 1
        return frame
