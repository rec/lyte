from __future__ import annotations

from typing import ClassVar, Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import Field, model_validator

from ...animation import Animation, Device, Family, State
from .. import numerical
from ..colors import RGB


class PaletteConveyor(Animation[State], frozen=True):
    family: ClassVar[Family] = Family.FIELDS

    palette: list[RGB] = Field(default_factory=lambda: list(numerical.CONVEYOR_PALETTE))
    stop_spacing: float = Field(default=8.0, gt=0)
    speed: float = Field(default=1.0, ge=0)
    reverse: bool = False
    interpolation: Literal['linear', 'smooth'] = 'smooth'

    @model_validator(mode='after')
    def validate_palette_conveyor(self) -> PaletteConveyor:
        numerical.validate_palette(self.palette)
        return self

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
        return numerical.map_palette(values, self.palette, cyclic=True)
