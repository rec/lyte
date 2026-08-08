from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from ...animation import Animation, Device, FloatRGB, State


class LinearGradient(Animation[State], frozen=True):
    start: float = 1
    end: float = 0
    mask: FloatRGB = (1, 1, 1)

    def render(self, device: Device, state: State) -> NDArray[np.float32]:
        values = np.linspace(
            self.start, self.end, device.led_count, endpoint=False, dtype=np.float32
        )
        state.frame += 1
        return np.ascontiguousarray(np.outer(values, self.mask), dtype=np.float32)


class LogGradient(Animation[State], frozen=True):
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
