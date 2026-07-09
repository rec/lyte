"""Random-walk color streamer for Lyte realtime frames."""

from __future__ import annotations

import random

from pydantic import BaseModel, PrivateAttr, model_validator

from .hamiltonian import FloatRGB, frame_bytes, interpolate


class RandomWalk(BaseModel):
    led_count: int
    speed: float = 10
    fps: float = 20
    variance: float = 1
    bounds: tuple[float, float] = (0, 180)
    color: FloatRGB | None = None
    period: float = 0
    pre_fill: bool = False
    seed: int | None = None

    _cache: list[FloatRGB] = PrivateAttr(default_factory=list)
    _cache_offset: int = PrivateAttr(default=0)
    _next_color: FloatRGB = PrivateAttr()
    _period: float = PrivateAttr(default=0)
    _random: random.Random = PrivateAttr()
    _total_pixels: float = PrivateAttr(default=0)

    @model_validator(mode="after")
    def validate_random_walk(self) -> RandomWalk:
        if self.led_count <= 0:
            raise ValueError("led_count must be greater than zero")
        if self.fps <= 0:
            raise ValueError("fps must be greater than zero")
        if self.speed < 0:
            raise ValueError("speed must not be negative")
        if self.variance < 0:
            raise ValueError("variance must not be negative")
        low, high = self.bounds
        if low >= high:
            raise ValueError("bounds must be ordered low, high")
        self._random = random.Random(self.seed)
        self._next_color = self.color or random_color(self._random, low, high)
        self._period = self.period * self.speed
        if self._period == 1:
            raise ValueError("period * speed must not equal 1")
        self._cache = [(0.0, 0.0, 0.0)] * (self.led_count + 1)
        if self.pre_fill:
            self._cache = [self.next_color(i) for i in range(len(self._cache))]
        return self

    def next_color(self, index: int) -> FloatRGB:
        variance = self.variance
        if self._period:
            variance *= (index % self._period) / (self._period - 1)

        result = self._next_color
        self._next_color = (
            perturb(result[0], variance, self.bounds, self._random),
            perturb(result[1], variance, self.bounds, self._random),
            perturb(result[2], variance, self.bounds, self._random),
        )
        return result

    def next_frame(self) -> bytes:
        self._advance_cache()
        fraction = self._total_pixels % 1
        colors = [
            interpolate(left, right, fraction)
            for left, right in zip(self._cache[:-1], self._cache[1:], strict=True)
        ]
        return frame_bytes(colors)

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
            self._cache[start + i] = self.next_color(self._cache_offset + i)
        self._cache_offset += needed


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
    bounds: tuple[float, float],
    generator: random.Random,
) -> float:
    if not variance:
        return component

    delta = generator.uniform(-1, 1) * variance
    out = component - delta < bounds[0] if delta < 0 else component + delta >= bounds[1]
    if out:
        return component - delta
    return component + delta
