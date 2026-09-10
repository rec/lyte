from __future__ import annotations

from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ...animation import Animation, Device, Family, State, float_color_from_rgb
from .. import validators
from ..colors import scale_color, wheel_color


class LarsonScannerState(State):
    direction: int = -1
    position: int = 0
    tail: int = 1


class LarsonScanner(effects.LarsonScanner, Animation[LarsonScannerState]):
    family: ClassVar[Family] = Family.EVENTS

    def initial_state(self, device: Device) -> LarsonScannerState:
        validators.validate_span(
            device.led_count,
            self.start,
            validators.resolve_end(device.led_count, self.end),
        )
        return LarsonScannerState(
            tail=validators.bounded_tail(
                self.tail, validators.span_size(device.led_count, self.start, self.end)
            )
        )

    def render(self, device: Device, state: LarsonScannerState) -> NDArray[np.float32]:
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        end = validators.resolve_end(device.led_count, self.end)
        center = self.start + state.position
        color = wheel_color(state.position) if self.rainbow else self.color
        fade = 256 // state.tail
        for i in range(state.tail):
            scaled = scale_color(color, max(0, 255 - fade * i))
            float_scaled = float_color_from_rgb(scaled)
            for index in (center - i, center + i):
                if self.start <= index <= end:
                    frame[index] = float_scaled
        if self.start + state.position >= end:
            state.direction = -state.direction
        elif state.position <= 0:
            state.direction = -state.direction
        state.position += state.direction * self.step
        state.frame += 1
        return frame
