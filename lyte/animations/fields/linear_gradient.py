from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State


class LinearGradient(effects.LinearGradient, Animation[State]):
    family: ClassVar[Family] = Family.FIELDS

    def render(self, device: Device, state: State) -> NDArray[np.float32]:
        values = np.linspace(
            self.start, self.end, device.led_count, endpoint=False, dtype=np.float32
        )
        state.frame += 1
        return np.ascontiguousarray(np.outer(values, self.mask), dtype=np.float32)
