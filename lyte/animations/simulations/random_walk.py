"""Random-walk color streamer for Lyte realtime frames."""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State
from ..patterns.hamiltonian import FloatRGB, frame_array, interpolate


class RandomWalkState(State):
    cache: list[FloatRGB] = []
    cache_offset: int = 0
    next_color: FloatRGB
    period: float = 0
    random: random.Random
    total_pixels: float = 0


class RandomWalk(effects.RandomWalk, Animation[RandomWalkState]):
    family: ClassVar[Family] = Family.SIMULATIONS

    def initial_state(self, device: Device) -> RandomWalkState:
        generator = random.Random(self.seed)
        low, high = self.bounds
        initial_color = (
            (self.color[0], self.color[1], self.color[2])
            if self.color is not None
            else random_color(generator, low, high)
        )
        state = RandomWalkState(
            cache=[(0.0, 0.0, 0.0)] * (device.led_count + 1),
            next_color=initial_color,
            period=self.period * self.speed,
            random=generator,
        )
        if self.pre_fill:
            state.cache = [self.next_color(state, i) for i in range(len(state.cache))]
        return state

    def next_color(self, state: RandomWalkState, index: int) -> FloatRGB:
        variance = self.variance
        if state.period:
            variance *= (index % state.period) / (state.period - 1)

        result = state.next_color
        state.next_color = (
            perturb(result[0], variance, self.bounds, state.random),
            perturb(result[1], variance, self.bounds, state.random),
            perturb(result[2], variance, self.bounds, state.random),
        )
        return result

    def render(self, device: Device, state: RandomWalkState) -> NDArray[np.float32]:
        self._advance_cache(device, state)
        fraction = state.total_pixels % 1
        colors = [
            interpolate(left, right, fraction)
            for left, right in zip(state.cache[:-1], state.cache[1:], strict=True)
        ]
        state.frame += 1
        return frame_array(colors)

    def _advance_cache(self, device: Device, state: RandomWalkState) -> None:
        state.total_pixels += self.speed / state.fps
        needed = int(state.total_pixels) - state.cache_offset
        if needed <= 0:
            return

        if needed >= len(state.cache):
            state.cache_offset += needed - len(state.cache)
            needed = len(state.cache)
            start = 0
        else:
            state.cache[:-needed] = state.cache[needed:]
            start = len(state.cache) - needed

        for i in range(needed):
            state.cache[start + i] = self.next_color(state, state.cache_offset + i)
        state.cache_offset += needed


def random_color(generator: random.Random, low: float, high: float) -> FloatRGB:
    rounded_low = round(low)
    rounded_high = round(high)
    return (
        float(generator.randint(rounded_low, rounded_high)),
        float(generator.randint(rounded_low, rounded_high)),
        float(generator.randint(rounded_low, rounded_high)),
    )


def perturb(
    component: float,
    variance: float,
    bounds: Sequence[float],
    generator: random.Random,
) -> float:
    if not variance:
        return component

    delta = generator.uniform(-1, 1) * variance
    out = component - delta < bounds[0] if delta < 0 else component + delta >= bounds[1]
    if out:
        return component - delta
    return component + delta
