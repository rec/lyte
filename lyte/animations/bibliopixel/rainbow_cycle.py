from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ...animation import Device
from ..util import advance_rainbow, span_size, wheel_color
from .rainbow import Rainbow, RainbowState


class RainbowCycle(Rainbow):
    def render(self, device: Device, state: RainbowState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        size = span_size(device.led_count, self.start, self.end)
        for i in range(size):
            frame[self.start + i] = wheel_color(round(i * 255 / size + state.position))
        advance_rainbow(state, self.step)
        return frame
