from __future__ import annotations

import math
import random
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State
from .. import numerical


class ExpandingRipplesState(State):
    origins: list[float]
    ages: list[float]
    color_indexes: list[int]
    generator: random.Random
    spawn_credit: float = 0


class ExpandingRipples(effects.ExpandingRipples, Animation[ExpandingRipplesState]):
    family: ClassVar[Family] = Family.EVENTS

    def initial_state(self, device: Device) -> ExpandingRipplesState:
        generator = random.Random(self.seed)
        return ExpandingRipplesState(
            origins=[self.origins[0] * (device.led_count - 1)],
            ages=[0],
            color_indexes=[generator.randrange(len(self.palette))],
            generator=generator,
        )

    def render(
        self, device: Device, state: ExpandingRipplesState
    ) -> NDArray[np.float32]:
        dt = self.speed / state.fps
        indexes = np.arange(device.led_count, dtype=np.float32)
        colors = numerical.palette_array(self.palette)
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        keep: list[int] = []
        for i, (origin, age, color_index) in enumerate(
            zip(state.origins, state.ages, state.color_indexes, strict=True)
        ):
            radius = age * self.propagation_speed
            distance = np.abs(indexes - origin)
            wave = np.exp(-0.5 * ((distance - radius) / self.width) ** 2)
            amplitude = math.exp(-self.decay * age)
            frame += wave[:, None] * colors[color_index] * amplitude
            state.ages[i] += dt
            if radius <= device.led_count + self.width and amplitude > 0.01:
                keep.append(i)
        state.origins = [state.origins[i] for i in keep]
        state.ages = [state.ages[i] for i in keep]
        state.color_indexes = [state.color_indexes[i] for i in keep]
        state.spawn_credit += self.event_rate * dt
        while state.spawn_credit >= 1:
            state.spawn_credit -= 1
            origin = state.generator.choice(self.origins) * (device.led_count - 1)
            state.origins.append(origin)
            state.ages.append(0)
            state.color_indexes.append(state.generator.randrange(len(self.palette)))
        state.frame += 1
        return np.ascontiguousarray(np.clip(frame, 0, 1))
