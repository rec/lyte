from __future__ import annotations

import math
import random
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from pydantic import Field, model_validator

from ...animation import Animation, Device, Family, State, float_color_from_rgb
from ..colors import RGB
from ..validators import validate_rgb


class CandleBankState(State):
    levels: list[float]
    targets: list[float]
    generator: random.Random


class CandleBank(Animation[CandleBankState], frozen=True):
    family: ClassVar[Family] = Family.FIELDS

    color: RGB = (255, 120, 30)
    zone_size: int = Field(default=8, gt=0)
    base_level: float = Field(default=0.55, ge=0, le=1)
    flicker: float = Field(default=0.18, ge=0, le=1)
    flare_rate: float = Field(default=0.3, ge=0)
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_candle_bank(self) -> CandleBank:
        validate_rgb(self.color)
        return self

    def initial_state(self, device: Device) -> CandleBankState:
        generator = random.Random(self.seed)
        zone_count = math.ceil(device.led_count / self.zone_size)
        levels = [self.base_level for _ in range(zone_count)]
        return CandleBankState(levels=levels, targets=list(levels), generator=generator)

    def render(self, device: Device, state: CandleBankState) -> NDArray[np.float32]:
        dt = self.speed / state.fps
        color = np.array(float_color_from_rgb(self.color), dtype=np.float32)
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        for i in range(len(state.levels)):
            if state.generator.random() < min(1.0, self.flare_rate * dt):
                state.targets[i] = min(1.0, self.base_level + self.flicker * 2)
            elif state.generator.random() < min(1.0, 5 * dt):
                variation = state.generator.uniform(-self.flicker, self.flicker)
                state.targets[i] = min(1.0, max(0.0, self.base_level + variation))
            state.levels[i] += (state.targets[i] - state.levels[i]) * min(1.0, 8 * dt)
            start = i * self.zone_size
            frame[start : min(device.led_count, start + self.zone_size)] = (
                color * state.levels[i]
            )
        state.frame += 1
        return np.ascontiguousarray(np.clip(frame, 0, 1))
