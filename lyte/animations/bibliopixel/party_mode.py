from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, State, float_light_frame_from_byte
from ..colors import DEFAULT_PATTERN, RGB
from ..validators import validate_palette


class PartyModeState(State):
    position: int = 0


class PartyMode(Animation[PartyModeState]):
    colors: tuple[RGB, ...] = DEFAULT_PATTERN

    @model_validator(mode='after')
    def validate_party_mode(self) -> PartyMode:
        validate_palette(self.colors)
        return self

    def initial_state(self, device: Device) -> PartyModeState:
        return PartyModeState()

    def render(self, device: Device, state: PartyModeState) -> NDArray[np.float32]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        if state.position % 2 == 0:
            frame[:] = self.colors[(state.position // 2) % len(self.colors)]
        state.position += 1
        state.frame += 1
        return float_light_frame_from_byte(frame)
