from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, FloatRGB, State


class GreyCodeState(State):
    elapsed: FloatRGB = (0, 0, 0)


class GreyCode(effects.GreyCode, Animation[GreyCodeState]):
    family: ClassVar[Family] = Family.PATTERNS

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
