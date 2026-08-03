from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, State
from ..colors import RGB
from ..validators import validate_rgb


class ColorFill(Animation[State]):
    color: RGB = (255, 0, 0)

    @model_validator(mode='after')
    def validate_color_fill(self) -> ColorFill:
        validate_rgb(self.color)
        return self

    def render(self, device: Device, state: State) -> NDArray[np.uint8]:
        frame = np.empty((device.led_count, 3), dtype=np.uint8)
        frame[:] = self.color
        state.frame += 1
        return frame
