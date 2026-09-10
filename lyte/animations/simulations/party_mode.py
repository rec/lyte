from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State, float_color_from_rgb


class PartyModeState(State):
    position: int = 0


class PartyMode(effects.PartyMode, Animation[PartyModeState]):
    family: ClassVar[Family] = Family.SIMULATIONS

    def initial_state(self, device: Device) -> PartyModeState:
        return PartyModeState()

    def render(self, device: Device, state: PartyModeState) -> NDArray[np.float32]:
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        if state.position % 2 == 0:
            frame[:] = float_color_from_rgb(
                self.colors[(state.position // 2) % len(self.colors)]
            )
        state.position += 1
        state.frame += 1
        return frame
