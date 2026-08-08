from __future__ import annotations

import random

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, FloatRGB, State, float_color_from_rgb
from ..colors import RGB
from ..validators import validate_palette, validate_rgb


class ExponentialFadeState(State):
    pixels: NDArray[np.float32]


class ExponentialFade(Animation[ExponentialFadeState]):
    ratio: float = 0.98
    color: RGB = (255, 0, 0)

    @model_validator(mode='after')
    def validate_exponential_fade(self) -> ExponentialFade:
        if not 0 <= self.ratio < 1:
            raise ValueError('ratio must be between zero and one')
        validate_rgb(self.color)
        return self

    def initial_state(self, device: Device) -> ExponentialFadeState:
        return ExponentialFadeState(
            pixels=np.zeros((device.led_count, 3), dtype=np.float32)
        )

    def render(
        self, device: Device, state: ExponentialFadeState
    ) -> NDArray[np.float32]:
        state.pixels *= self.ratio
        state.pixels += (1 - self.ratio) * np.array(
            float_color_from_rgb(self.color), dtype=np.float32
        )
        state.frame += 1
        return state.pixels


class RandomizeState(State):
    generator: np.random.Generator


class Randomize(Animation[RandomizeState]):
    seed: int | None = None

    def initial_state(self, device: Device) -> RandomizeState:
        return RandomizeState(generator=np.random.default_rng(self.seed))

    def render(self, device: Device, state: RandomizeState) -> NDArray[np.float32]:
        state.frame += 1
        return state.generator.random((device.led_count, 3)).astype(np.float32)


class RainState(State):
    generator: random.Random
    pixels: NDArray[np.float32]
    wait: float = 0


class Rain(Animation[RainState]):
    colors: tuple[RGB, ...] = ((70, 70, 70), (35, 35, 35), (80, 20, 20), (20, 80, 20))
    rate: float = 10
    seed: int | None = None

    @model_validator(mode='after')
    def validate_rain(self) -> Rain:
        validate_palette(self.colors)
        if self.rate <= 0:
            raise ValueError('rate must be greater than zero')
        return self

    def initial_state(self, device: Device) -> RainState:
        return RainState(
            generator=random.Random(self.seed),
            pixels=np.zeros((device.led_count, 3), dtype=np.float32),
        )

    def render(self, device: Device, state: RainState) -> NDArray[np.float32]:
        state.wait -= 1 / state.fps
        if state.wait <= 0:
            index = state.generator.randrange(device.led_count)
            state.pixels[index] = float_color_from_rgb(
                state.generator.choice(self.colors)
            )
            state.wait = state.generator.expovariate(self.rate)
        state.frame += 1
        return state.pixels


class GreyCodeState(State):
    elapsed: FloatRGB = (0, 0, 0)


class GreyCode(Animation[GreyCodeState]):
    offsets: FloatRGB = (0, 100, 200)
    speeds: FloatRGB = (-0.01, 0.023, 0.014)

    def initial_state(self, device: Device) -> GreyCodeState:
        return GreyCodeState()

    def render(self, device: Device, state: GreyCodeState) -> NDArray[np.float32]:
        indexes = np.arange(device.led_count, dtype=np.float32)[:, None]
        offsets = np.array(self.offsets, dtype=np.float32)
        elapsed = np.array(state.elapsed, dtype=np.float32)
        values = (indexes + offsets + elapsed).astype(np.int32) % 256
        frame = ((values ^ (values // 2)) / 255).astype(np.float32)
        state.elapsed = tuple(elapsed + self.speeds)
        state.frame += 1
        return frame
