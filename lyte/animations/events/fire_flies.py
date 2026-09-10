from __future__ import annotations

import random
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State, float_color_from_rgb
from ..validators import resolve_end, validate_span


class FireFliesState(State):
    random: random.Random


class FireFlies(effects.FireFlies, Animation[FireFliesState]):
    family: ClassVar[Family] = Family.EVENTS

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
