from __future__ import annotations

import math
import random
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State, float_color_from_rgb


class LightningStormState(State):
    pixels: NDArray[np.float32]
    generator: random.Random
    wait: float = 0
    burst_remaining: int = 0


class LightningStorm(effects.LightningStorm, Animation[LightningStormState]):
    family: ClassVar[Family] = Family.EVENTS

    def initial_state(self, device: Device) -> LightningStormState:
        return LightningStormState(
            pixels=np.zeros((device.led_count, 3), dtype=np.float32),
            generator=random.Random(self.seed),
        )

    def render(self, device: Device, state: LightningStormState) -> NDArray[np.float32]:
        dt = self.speed / state.fps
        state.pixels *= math.exp(-self.afterglow * dt)
        state.wait -= dt
        if state.wait <= 0:
            center = state.generator.randrange(device.led_count)
            distance = np.abs(np.arange(device.led_count, dtype=np.float32) - center)
            flash = np.exp(-distance / self.branch_width).astype(np.float32)
            color = np.array(float_color_from_rgb(self.color), dtype=np.float32)
            state.pixels = np.maximum(state.pixels, flash[:, None] * color)
            if state.burst_remaining <= 0:
                state.burst_remaining = state.generator.randrange(self.maximum_burst)
            if state.burst_remaining:
                state.burst_remaining -= 1
                state.wait = state.generator.uniform(0.04, 0.16)
            else:
                state.wait = state.generator.expovariate(self.flash_rate)
        state.frame += 1
        return np.ascontiguousarray(np.clip(state.pixels, 0, 1))
