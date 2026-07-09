"""Hamiltonian color streamer for Lyte realtime frames."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
from numpy import typing as npt
from pydantic import BaseModel, PrivateAttr, model_validator

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
    order: str | int = "rgb",
    inverted: str = "",
) -> Iterator[RGB]:
    counter = HamiltonianCounter(n=n, order=order, inverted=inverted)
    for _ in range(n**3):
        yield counter.next_color()


class HamiltonianCounter(BaseModel):
    n: int = 8
    order: str | int = "rgb"
    inverted: str = ""

    _color: RGB = PrivateAttr(default=(0, 0, 0))

    @model_validator(mode="after")
    def validate_counter(self) -> HamiltonianCounter:
        if self.n % 2:
            raise ValueError("n must be even")
        if self.n <= 2:
            raise ValueError("n must be greater than 2")
        parse_order(self.order)
        unknown = set(self.inverted.lower()) - set("rgb")
        if unknown:
            raise ValueError(f"Unknown inverted channels: {''.join(sorted(unknown))}")
        return self

    def next_color(self) -> RGB:
        ordered = tuple(self._color[i] for i in parse_order(self.order))
        scale = 256 / self.n
        values = []
        for channel, component in zip("rgb", ordered, strict=True):
            if channel in self.inverted.lower():
                component = self.n - component - 1
            values.append(round(scale * component))
        self._color = next_hamiltonian(self.n, *self._color)
        return values[0], values[1], values[2]


class HamiltonianStreamer(BaseModel):
    led_count: int
    speed: float = 25
    fps: float = 20
    n: int = 8
    order: str | int = "rgb"
    inverted: str = ""
    pre_fill: bool = False

    _cache: list[FloatRGB] = PrivateAttr(default_factory=list)
    _cache_offset: int = PrivateAttr(default=0)
    _counter: HamiltonianCounter = PrivateAttr()
    _total_pixels: float = PrivateAttr(default=0)

    @model_validator(mode="after")
    def validate_streamer(self) -> HamiltonianStreamer:
        if self.led_count <= 0:
            raise ValueError("led_count must be greater than zero")
        if self.fps <= 0:
            raise ValueError("fps must be greater than zero")
        if self.speed < 0:
            raise ValueError("speed must not be negative")
        self._counter = HamiltonianCounter(
            n=self.n,
            order=self.order,
            inverted=self.inverted,
        )
        self._cache = [(0.0, 0.0, 0.0)] * (self.led_count + 1)
        if self.pre_fill:
            self._cache = [
                to_float_rgb(self._counter.next_color()) for _ in self._cache
            ]
        return self

    def next_frame(self) -> npt.NDArray[np.uint8]:
        self._advance_cache()
        fraction = self._total_pixels % 1
        colors = [
            interpolate(left, right, fraction)
            for left, right in zip(self._cache[:-1], self._cache[1:], strict=True)
        ]
        return frame_array(colors)

    def _advance_cache(self) -> None:
        self._total_pixels += self.speed / self.fps
        needed = int(self._total_pixels) - self._cache_offset
        if needed <= 0:
            return

        if needed >= len(self._cache):
            self._cache_offset += needed - len(self._cache)
            needed = len(self._cache)
            start = 0
        else:
            self._cache[:-needed] = self._cache[needed:]
            start = len(self._cache) - needed

        for i in range(needed):
            self._cache[start + i] = to_float_rgb(self._counter.next_color())
        self._cache_offset += needed


def parse_order(order: str | int) -> tuple[int, int, int]:
    if isinstance(order, int):
        if order != 0:
            raise ValueError("Only integer order 0 is supported")
        return 0, 1, 2

    normalized = order.lower()
    if sorted(normalized) != ["b", "g", "r"]:
        raise ValueError("order must be a permutation of rgb")
    return (
        "rgb".index(normalized[0]),
        "rgb".index(normalized[1]),
        "rgb".index(normalized[2]),
    )


def interpolate(left: FloatRGB, right: FloatRGB, fraction: float) -> FloatRGB:
    return (
        (1 - fraction) * left[0] + fraction * right[0],
        (1 - fraction) * left[1] + fraction * right[1],
        (1 - fraction) * left[2] + fraction * right[2],
    )


def to_float_rgb(color: RGB) -> FloatRGB:
    return float(color[0]), float(color[1]), float(color[2])


def frame_array(colors: list[FloatRGB]) -> npt.NDArray[np.uint8]:
    frame = np.empty((len(colors), 3), dtype=np.uint8)
    for i, color in enumerate(colors):
        for channel, component in enumerate(color):
            frame[i, channel] = max(0, min(255, round(component)))
    return frame
