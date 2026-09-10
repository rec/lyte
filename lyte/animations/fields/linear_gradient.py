from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray

from ...animation import Animation, Device, Family, FloatRGB, State


class LinearGradient(Animation[State], frozen=True):
    family: ClassVar[Family] = Family.FIELDS

    start: float = 1
    end: float = 0
    mask: FloatRGB = (1, 1, 1)

    def render(self, device: Device, state: State) -> NDArray[np.float32]:
        values = np.linspace(
            self.start, self.end, device.led_count, endpoint=False, dtype=np.float32
        )
        state.frame += 1
        return np.ascontiguousarray(np.outer(values, self.mask), dtype=np.float32)
