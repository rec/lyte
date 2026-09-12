"""Layer long, low-contrast waves moving at different speeds and directions.

Rare bright crests and turbulence give the field a water-like appearance.
Ufor defines palette, wave count, speed, crest rate, turbulence and seed;
per-wave rates and wavelengths are seeded at startup.
"""

from __future__ import annotations

import math
import random
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State
from .. import numerical


class OceanCurrentState(State):
    phases: list[float]
    rates: list[float]
    wavelengths: list[float]
    crests: NDArray[np.float32]
    generator: random.Random


class OceanCurrent(effects.OceanCurrent, Animation[OceanCurrentState]):
    family: ClassVar[Family] = Family.FIELDS

    def initial_state(self, device: Device) -> OceanCurrentState:
        generator = random.Random(self.seed)
        return OceanCurrentState(
            phases=[generator.uniform(0, math.tau) for _ in range(self.wave_count)],
            rates=[generator.uniform(-0.8, 0.8) for _ in range(self.wave_count)],
            wavelengths=[generator.uniform(0.2, 0.8) for _ in range(self.wave_count)],
            crests=np.zeros(device.led_count, dtype=np.float32),
            generator=generator,
        )

    def render(self, device: Device, state: OceanCurrentState) -> NDArray[np.float32]:
        dt = self.speed / state.fps
        x = np.linspace(0, 1, device.led_count, dtype=np.float32)
        field = np.zeros(device.led_count, dtype=np.float32)
        for i in range(self.wave_count):
            field += np.sin(math.tau * x / state.wavelengths[i] + state.phases[i])
            state.phases[i] += state.rates[i] * dt
        field = 0.45 + 0.25 * field / self.wave_count
        state.crests *= math.exp(-4 * dt)
        if state.generator.random() < min(1.0, self.crest_rate * dt):
            center = state.generator.randrange(device.led_count)
            distance = np.arange(device.led_count, dtype=np.float32) - center
            width = max(1.0, device.led_count * 0.03)
            state.crests += np.exp(-0.5 * (distance / width) ** 2).astype(np.float32)
        noise = np.array(
            [state.generator.uniform(-1, 1) for _ in range(device.led_count)],
            dtype=np.float32,
        )
        values = field + state.crests * 0.45 + noise * self.turbulence * 0.05
        state.frame += 1
        return numerical.map_palette(values, self.palette)
