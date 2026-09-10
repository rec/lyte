from __future__ import annotations

import math
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from pydantic import Field, model_validator

from ...animation import Animation, Device, Family, State
from .. import numerical
from ..colors import RGB


class Interference(Animation[State], frozen=True):
    family: ClassVar[Family] = Family.FIELDS

    palette: list[RGB] = Field(
        default_factory=lambda: list(numerical.INTERFERENCE_PALETTE)
    )
    wavelengths: list[float] = Field(default_factory=lambda: [13.0, 23.0, 37.0])
    rates: list[float] = Field(default_factory=lambda: [1.0, -0.63, 0.37])
    phase_offsets: list[float] = Field(default_factory=lambda: [0.0, 1.7, 3.1])
    contrast: float = Field(default=1.4, gt=0)
    speed: float = Field(default=1.0, ge=0)

    @model_validator(mode='after')
    def validate_interference(self) -> Interference:
        numerical.validate_palette(self.palette)
        if not self.wavelengths:
            raise ValueError('wavelengths must not be empty')
        if len(self.wavelengths) != len(self.rates) or len(self.rates) != len(
            self.phase_offsets
        ):
            raise ValueError(
                'wavelengths, rates, and phase_offsets must have equal size'
            )
        if any(v <= 0 for v in self.wavelengths):
            raise ValueError('wavelengths must be greater than zero')
        return self

    def render(self, device: Device, state: State) -> NDArray[np.float32]:
        indexes = np.arange(device.led_count, dtype=np.float32)
        elapsed = state.frame * self.speed / state.fps
        field = np.zeros(device.led_count, dtype=np.float32)
        for wavelength, rate, offset in zip(
            self.wavelengths, self.rates, self.phase_offsets, strict=True
        ):
            effective_wavelength = wavelength * (
                1 + 0.08 * math.sin(elapsed * 0.13 + offset)
            )
            field += np.sin(
                math.tau * indexes / effective_wavelength + elapsed * rate + offset
            )
        values = np.clip(0.5 + field / (2 * len(self.wavelengths)), 0, 1)
        values = np.clip(0.5 + (values - 0.5) * self.contrast, 0, 1)
        state.frame += 1
        return numerical.map_palette(values, self.palette)
