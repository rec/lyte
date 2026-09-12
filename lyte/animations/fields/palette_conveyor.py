"""Move a continuous color gradient along the string with interpolated stops.

The cyclic palette uses linear or smooth interpolation and can reverse or
pause at zero speed. Ufor defines palette, stop spacing, speed, reverse
and interpolation.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State
from .. import numerical


class PaletteConveyor(effects.PaletteConveyor, Animation[State]):
    family: ClassVar[Family] = Family.FIELDS

    def render(self, device: Device, state: State) -> NDArray[np.float32]:
        direction = -1 if self.reverse else 1
        offset = direction * state.frame * self.speed / state.fps
        values = np.arange(device.led_count, dtype=np.float32) / self.stop_spacing
        values += offset
        if self.interpolation == 'smooth':
            integral = np.floor(values)
            fraction = values - integral
            values = integral + fraction * fraction * (3 - 2 * fraction)
        state.frame += 1
        return numerical.map_palette(
            values.astype(np.float32, copy=False), self.palette, cyclic=True
        )
