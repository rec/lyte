from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray

from ...animation import Animation, Device, Family, FloatRGB, State


class LogGradient(Animation[State], frozen=True):
    family: ClassVar[Family] = Family.FIELDS

    start: float = 1
    end: float = 0
    base: float = 10
    mask: FloatRGB = (1, 1, 1)

    def render(self, device: Device, state: State) -> NDArray[np.float32]:
        values = np.logspace(
            self.start, self.end, device.led_count, base=self.base, endpoint=False
        ).astype(np.float32)
        values = (values - values.min()) / (values.max() - values.min())
        state.frame += 1
        return np.ascontiguousarray(np.outer(values, self.mask), dtype=np.float32)
