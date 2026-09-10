from __future__ import annotations

import random
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State, float_color_from_rgb
from ..colors import RGB, scale_color
from ..validators import bounded_tail


class PulseState(State):
    color: RGB | None = None
    position: int = 0
    random: random.Random
    speed: int = 0
    tail: int = 1


class Pulse(effects.Pulse, Animation[PulseState]):
    family: ClassVar[Family] = Family.EVENTS

    def initial_state(self, device: Device) -> PulseState:
        return PulseState(
            tail=bounded_tail(self.tail, device.led_count),
            random=random.Random(self.seed),
        )

    def render(self, device: Device, state: PulseState) -> NDArray[np.float32]:
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        if state.speed == 0 and state.random.randrange(0, 100) <= self.chance:
            color = state.random.choice(self.colors)
            state.color = color[0], color[1], color[2]
            state.speed = state.random.randrange(self.min_speed, self.max_speed)
            state.position = 0
        if state.speed > 0 and state.color is not None:
            fade = 256 // state.tail
            for i in range(state.tail):
                scaled = scale_color(state.color, max(0, 255 - fade * i))
                float_scaled = float_color_from_rgb(scaled)
                for index in (state.position - i, state.position + i):
                    if 0 <= index < device.led_count:
                        frame[index] = float_scaled
            if state.position > device.led_count + state.tail:
                state.speed = 0
            else:
                state.position += state.speed
        state.frame += 1
        return frame
