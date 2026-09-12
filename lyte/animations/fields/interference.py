"""Combine moving periodic fields into constructive and destructive interference.

Slowly varying wavelengths create moire-like motion along the string.
Ufor defines wavelengths, rates, phase offsets, palette, contrast and speed.
"""

from __future__ import annotations

import math
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State
from .. import numerical


class Interference(effects.Interference, Animation[State]):
    family: ClassVar[Family] = Family.FIELDS

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
        return numerical.map_palette(
            values.astype(np.float32, copy=False), self.palette
        )
