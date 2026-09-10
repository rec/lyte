from __future__ import annotations

import math
import random
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State
from .. import numerical


class AuroraState(State):
    phases: list[float]
    rates: list[float]


class Aurora(effects.Aurora, Animation[AuroraState]):
    family: ClassVar[Family] = Family.FIELDS

    def initial_state(self, device: Device) -> AuroraState:
        generator = random.Random(self.seed)
        return AuroraState(
            phases=[generator.uniform(0, math.tau) for _ in range(self.band_count)],
            rates=[generator.uniform(0.12, 0.35) for _ in range(self.band_count)],
        )

    def render(self, device: Device, state: AuroraState) -> NDArray[np.float32]:
        x = np.linspace(0, 1, device.led_count, dtype=np.float32)
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        colors = numerical.palette_array(self.palette)
        for i, phase in enumerate(state.phases):
            center = 0.5 + 0.45 * math.sin(phase + 0.37 * math.sin(phase * 0.31))
            width = self.softness * (0.75 + 0.5 * math.sin(phase * 0.43) ** 2)
            band = np.exp(-0.5 * ((x - center) / width) ** 2).astype(np.float32)
            frame += band[:, None] * colors[i % len(colors)]
            state.phases[i] += state.rates[i] * self.speed / state.fps
        state.frame += 1
        return np.ascontiguousarray(np.clip(frame * self.intensity, 0, 1))
