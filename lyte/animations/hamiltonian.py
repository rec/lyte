"""Hamiltonian color streamer for Lyte realtime frames."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, PrivateAttr, model_validator

from ..animation import Animation, Device, State

RGB = tuple[int, int, int]
FloatRGB = tuple[float, float, float]


def next_hamiltonian(n: int, a: int, b: int, c: int) -> RGB:
    if b == 0:
        if a != 0 and c == 0:
            return a - 1, b, c

        if a % 2 and a < n - 1 and c == 1:
            return a + 1, b, c

    next_c = c + (-1 if (a + b) % 2 else 1)
    if 0 <= next_c < n:
        return a, b, next_c

    next_b = b + (-1 if a % 2 else 1)
    if 0 <= next_b < n:
        return a, next_b, c

    return a + 1, b, c


def hamiltonian_colors(
    n: int = 8,
    order: str | int = 'rgb',
    inverted: str = '',
) -> Iterator[RGB]:
    counter = HamiltonianCounter(n=n, order=order, inverted=inverted)
    for _ in range(n**3):
        yield counter.next_color()


class HamiltonianCounter(BaseModel):
    n: int = 8
    order: str | int = 'rgb'
    inverted: str = ''

    _color: RGB = PrivateAttr(default=(0, 0, 0))

    @model_validator(mode='after')
    def validate_counter(self) -> HamiltonianCounter:
        if self.n % 2:
            raise ValueError('n must be even')
        if self.n <= 2:
            raise ValueError('n must be greater than 2')
        parse_order(self.order)
        unknown = set(self.inverted.lower()) - set('rgb')
        if unknown:
            raise ValueError(f'Unknown inverted channels: {"".join(sorted(unknown))}')
        return self

    def next_color(self) -> RGB:
        ordered = tuple(self._color[i] for i in parse_order(self.order))
        scale = 256 / self.n
        values = []
        for channel, component in zip('rgb', ordered, strict=True):
            if channel in self.inverted.lower():
                component = self.n - component - 1
            values.append(round(scale * component))
        self._color = next_hamiltonian(self.n, *self._color)
        return values[0], values[1], values[2]


class HamiltonianState(State):
    cache: list[FloatRGB] = []
    cache_offset: int = 0
    counter: HamiltonianCounter
    total_pixels: float = 0


class Hamiltonian(Animation[HamiltonianState]):
    speed: float = 25
    n: int = 8
    order: str | int = 'rgb'
    inverted: str = ''
    pre_fill: bool = False

    @model_validator(mode='after')
    def validate_hamiltonian(self) -> Hamiltonian:
        if self.speed < 0:
            raise ValueError('speed must not be negative')
        HamiltonianCounter(
            n=self.n,
            order=self.order,
            inverted=self.inverted,
        )
        return self

    def initial_state(self, device: Device) -> HamiltonianState:
        counter = HamiltonianCounter(
            n=self.n,
            order=self.order,
            inverted=self.inverted,
        )
        cache = [(0.0, 0.0, 0.0)] * (device.led_count + 1)
        if self.pre_fill:
            cache = [to_float_rgb(counter.next_color()) for _ in cache]
        return HamiltonianState(counter=counter, cache=cache)

    def render(self, device: Device, state: HamiltonianState) -> NDArray[np.float32]:
        self._advance_cache(device, state)
        fraction = state.total_pixels % 1
        colors = [
            interpolate(left, right, fraction)
            for left, right in zip(state.cache[:-1], state.cache[1:], strict=True)
        ]
        state.frame += 1
        return frame_array(colors)

    def _advance_cache(self, device: Device, state: HamiltonianState) -> None:
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
            state.cache[start + i] = to_float_rgb(state.counter.next_color())
        state.cache_offset += needed


def parse_order(order: str | int) -> tuple[int, int, int]:
    if isinstance(order, int):
        if order != 0:
            raise ValueError('Only integer order 0 is supported')
        return 0, 1, 2

    normalized = order.lower()
    if sorted(normalized) != ['b', 'g', 'r']:
        raise ValueError('order must be a permutation of rgb')
    return (
        'rgb'.index(normalized[0]),
        'rgb'.index(normalized[1]),
        'rgb'.index(normalized[2]),
    )


def interpolate(left: FloatRGB, right: FloatRGB, fraction: float) -> FloatRGB:
    return (
        (1 - fraction) * left[0] + fraction * right[0],
        (1 - fraction) * left[1] + fraction * right[1],
        (1 - fraction) * left[2] + fraction * right[2],
    )


def to_float_rgb(color: RGB) -> FloatRGB:
    return float(color[0]), float(color[1]), float(color[2])


def frame_array(colors: list[FloatRGB]) -> NDArray[np.float32]:
    frame = np.empty((len(colors), 3), dtype=np.float32)
    for i, color in enumerate(colors):
        for channel, component in enumerate(color):
            frame[i, channel] = max(0.0, min(1.0, component / 255))
    return frame
