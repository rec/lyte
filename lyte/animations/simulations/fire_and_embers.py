from __future__ import annotations

import math
import random
from typing import ClassVar, Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import Field, model_validator

from ...animation import Animation, Device, Family, State
from .. import numerical
from ..colors import RGB


class FireAndEmbersState(State):
    heat: NDArray[np.float32]
    generator: random.Random


class FireAndEmbers(Animation[FireAndEmbersState], frozen=True):
    family: ClassVar[Family] = Family.SIMULATIONS

    palette: list[RGB] = Field(default_factory=lambda: list(numerical.FIRE_PALETTE))
    cooling: float = Field(default=1.4, gt=0)
    diffusion: float = Field(default=4.0, ge=0)
    spark_rate: float = Field(default=12.0, ge=0)
    wind: float = 3.0
    origin: Literal['start', 'end'] = 'start'
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_fire_and_embers(self) -> FireAndEmbers:
        numerical.validate_palette(self.palette)
        return self

    def initial_state(self, device: Device) -> FireAndEmbersState:
        return FireAndEmbersState(
            heat=np.zeros(device.led_count, dtype=np.float32),
            generator=random.Random(self.seed),
        )

    def render(self, device: Device, state: FireAndEmbersState) -> NDArray[np.float32]:
        dt = self.speed / state.fps
        state.heat *= math.exp(-self.cooling * dt)
        padded = np.pad(state.heat, 1, mode='edge')
        neighbours = (padded[:-2] + padded[2:]) / 2
        state.heat += min(0.5, self.diffusion * dt) * (neighbours - state.heat)
        direction = 1 if self.origin == 'start' else -1
        if self.wind:
            indexes = np.arange(device.led_count, dtype=np.float32)
            source = indexes - direction * self.wind * dt
            state.heat = np.interp(
                source,
                indexes,
                state.heat,
                left=0.0,
                right=0.0,
            ).astype(np.float32)
        spark_count = int(self.spark_rate * dt)
        if state.generator.random() < self.spark_rate * dt - spark_count:
            spark_count += 1
        for _ in range(spark_count):
            distance = state.generator.randrange(max(1, min(4, device.led_count)))
            index = distance if direction > 0 else device.led_count - 1 - distance
            state.heat[index] = min(
                1.0, state.heat[index] + state.generator.uniform(0.6, 1.0)
            )
        state.frame += 1
        return numerical.map_palette(state.heat, self.palette)
