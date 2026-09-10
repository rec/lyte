from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State


class LogGradient(effects.LogGradient, Animation[State]):
    family: ClassVar[Family] = Family.FIELDS

    def render(self, device: Device, state: State) -> NDArray[np.float32]:
        values = np.logspace(
            self.start, self.end, device.led_count, base=self.base, endpoint=False
        ).astype(np.float32)
        minimum = values.min()
        extent = values.max() - minimum
        values = np.ones_like(values) if extent == 0 else (values - minimum) / extent
        state.frame += 1
        return np.ascontiguousarray(np.outer(values, self.mask), dtype=np.float32)
