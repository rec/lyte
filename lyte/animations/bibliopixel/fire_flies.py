from __future__ import annotations

import random

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, State, float_color_from_rgb
from ..colors import RGB
from ..validators import resolve_end, validate_palette, validate_span, validate_start


class FireFliesState(State):
    random: random.Random


class FireFlies(Animation[FireFliesState]):
    colors: tuple[RGB, ...] = ((255, 0, 0),)
    width: int = 1
    count: int = 1
    start: int = 0
    end: int | None = None
    seed: int | None = None

    @model_validator(mode='after')
    def validate_fire_flies(self) -> FireFlies:
        validate_palette(self.colors)
        if self.width < 1:
            raise ValueError('width must be at least 1')
        if self.count < 1:
            raise ValueError('count must be at least 1')
        validate_start(self.start)
        return self

    def initial_state(self, device: Device) -> FireFliesState:
        validate_span(
            device.led_count, self.start, resolve_end(device.led_count, self.end)
        )
        return FireFliesState(random=random.Random(self.seed))

    def render(self, device: Device, state: FireFliesState) -> NDArray[np.float32]:
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        end = resolve_end(device.led_count, self.end)
        for _ in range(self.count):
            pixel = state.random.randint(self.start, end)
            color = float_color_from_rgb(state.random.choice(self.colors))
            frame[pixel : min(pixel + self.width, end + 1)] = color
        state.frame += 1
        return frame
