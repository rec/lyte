from __future__ import annotations

import random

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, State
from ..colors import RGB, scale_color
from ..validators import bounded_tail, validate_palette


class PulseState(State):
    color: RGB | None = None
    position: int = 0
    random: random.Random
    speed: int = 0
    tail: int = 1


class Pulse(Animation[PulseState]):
    colors: tuple[RGB, ...] = ((255, 0, 0),)
    tail: int = 2
    chance: int = 30
    min_speed: int = 1
    max_speed: int = 5
    seed: int | None = None

    @model_validator(mode="after")
    def validate_pulse(self) -> Pulse:
        validate_palette(self.colors)
        if self.tail < 0:
            raise ValueError("tail must not be negative")
        if self.chance < 0 or self.chance > 100:
            raise ValueError("chance must be between 0 and 100")
        if self.min_speed < 1 or self.max_speed <= self.min_speed:
            raise ValueError("min_speed and max_speed must define a non-empty range")
        return self

    def initial_state(self, device: Device) -> PulseState:
        return PulseState(
            tail=bounded_tail(self.tail, device.led_count),
            random=random.Random(self.seed),
        )

    def render(self, device: Device, state: PulseState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        if state.speed == 0 and state.random.randrange(0, 100) <= self.chance:
            state.color = state.random.choice(self.colors)
            state.speed = state.random.randrange(self.min_speed, self.max_speed)
            state.position = 0
        if state.speed > 0 and state.color is not None:
            fade = 256 // state.tail
            for i in range(state.tail):
                scaled = scale_color(state.color, max(0, 255 - fade * i))
                for index in (state.position - i, state.position + i):
                    if 0 <= index < device.led_count:
                        frame[index] = scaled
            if state.position > device.led_count + state.tail:
                state.speed = 0
            else:
                state.position += state.speed
        state.frame += 1
        return frame
