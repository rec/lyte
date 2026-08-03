from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, State
from ..colors import RGB
from ..validators import validate_palette


class SaberBladeState(State):
    color_index: int = 0
    position: int = 0
    speed: int


class SaberBlade(Animation[SaberBladeState]):
    colors: tuple[RGB, ...] = ((255, 0, 0),)
    speed: int = 1

    @model_validator(mode='after')
    def validate_saber_blade(self) -> SaberBlade:
        validate_palette(self.colors)
        if self.speed == 0:
            raise ValueError('speed must not be zero')
        return self

    def initial_state(self, device: Device) -> SaberBladeState:
        return SaberBladeState(speed=self.speed)

    def render(self, device: Device, state: SaberBladeState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        if state.position > 0:
            frame[: min(state.position, device.led_count)] = self.colors[
                state.color_index % len(self.colors)
            ]
        state.position += state.speed
        if state.speed > 0 and state.position + state.speed > device.led_count:
            state.speed *= -1
        elif state.speed < 0 and state.position <= 0:
            state.position = 0
            state.color_index += 1
            state.speed *= -1
        state.frame += 1
        return frame
