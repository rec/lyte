from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State, float_color_from_rgb


class SaberBladeState(State):
    color_index: int = 0
    position: int = 0
    speed: int


class SaberBlade(effects.SaberBlade, Animation[SaberBladeState]):
    family: ClassVar[Family] = Family.PATTERNS

    def initial_state(self, device: Device) -> SaberBladeState:
        return SaberBladeState(speed=self.speed)

    def render(self, device: Device, state: SaberBladeState) -> NDArray[np.float32]:
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        if state.position > 0:
            color = float_color_from_rgb(
                self.colors[state.color_index % len(self.colors)]
            )
            frame[: min(state.position, device.led_count)] = color
        state.position += state.speed
        if state.speed > 0 and state.position + state.speed > device.led_count:
            state.speed *= -1
        elif state.speed < 0 and state.position <= 0:
            state.position = 0
            state.color_index += 1
            state.speed *= -1
        state.frame += 1
        return frame
