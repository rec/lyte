from __future__ import annotations

import math
import random
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from pydantic import Field, model_validator

from ...animation import Animation, Device, Family, State, float_color_from_rgb
from .. import numerical
from ..colors import RGB


class ConfettiWithDecayState(State):
    pixels: NDArray[np.float32]
    generator: random.Random
    spawn_credit: float = 0


class ConfettiWithDecay(Animation[ConfettiWithDecayState], frozen=True):
    family: ClassVar[Family] = Family.EVENTS

    palette: list[RGB] = Field(default_factory=lambda: list(numerical.CONFETTI_PALETTE))
    spawn_rate: float = Field(default=8.0, ge=0)
    decay: float = Field(default=2.5, gt=0)
    width: int = Field(default=1, gt=0)
    speed: float = Field(default=1.0, ge=0)
    seed: int | None = None

    @model_validator(mode='after')
    def validate_confetti_with_decay(self) -> ConfettiWithDecay:
        numerical.validate_palette(self.palette)
        return self

    def initial_state(self, device: Device) -> ConfettiWithDecayState:
        return ConfettiWithDecayState(
            pixels=np.zeros((device.led_count, 3), dtype=np.float32),
            generator=random.Random(self.seed),
            spawn_credit=1,
        )

    def render(
        self, device: Device, state: ConfettiWithDecayState
    ) -> NDArray[np.float32]:
        dt = self.speed / state.fps
        state.pixels *= math.exp(-self.decay * dt)
        state.spawn_credit += self.spawn_rate * dt
        spawn_count = int(state.spawn_credit)
        state.spawn_credit -= spawn_count
        for _ in range(spawn_count):
            index = state.generator.randrange(device.led_count)
            color = float_color_from_rgb(state.generator.choice(self.palette))
            state.pixels[index : min(device.led_count, index + self.width)] = color
        state.frame += 1
        return np.ascontiguousarray(np.clip(state.pixels, 0, 1))
