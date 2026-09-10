from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State, float_color_from_rgb


class ColorFill(effects.ColorFill, Animation[State]):
    family: ClassVar[Family] = Family.PATTERNS

    def render(self, device: Device, state: State) -> NDArray[np.float32]:
        frame = np.empty((device.led_count, 3), dtype=np.float32)
        frame[:] = float_color_from_rgb(self.color)
        state.frame += 1
        return frame
