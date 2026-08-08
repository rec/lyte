from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ...animation import Device, float_color_from_rgb
from ..colors import wheel_color
from ..validators import advance_rainbow, span_size
from .rainbow import Rainbow, RainbowState


class RainbowCycle(Rainbow, frozen=True):
    def render(self, device: Device, state: RainbowState) -> NDArray[np.float32]:
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        size = span_size(device.led_count, self.start, self.end)
        for i in range(size):
            frame[self.start + i] = float_color_from_rgb(
                wheel_color(round(i * 255 / size + state.position))
            )
        advance_rainbow(state, self.step)
        return frame
