from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, State
from ..util import (
    RGB,
    bounded_tail,
    resolve_end,
    scale_color,
    span_size,
    validate_rgb,
    validate_span,
    validate_start,
    validate_step,
    wheel_color,
)


class LarsonScannerState(State):
    direction: int = -1
    position: int = 0
    tail: int = 1


class LarsonScanner(Animation[LarsonScannerState]):
    color: RGB = (255, 0, 0)
    tail: int = 2
    start: int = 0
    end: int | None = None
    step: int = 1
    rainbow: bool = False

    @model_validator(mode="after")
    def validate_larson_scanner(self) -> LarsonScanner:
        validate_rgb(self.color)
        validate_step(self.step)
        if self.tail < 0:
            raise ValueError("tail must not be negative")
        validate_start(self.start)
        return self

    def initial_state(self, device: Device) -> LarsonScannerState:
        validate_span(
            device.led_count, self.start, resolve_end(device.led_count, self.end)
        )
        return LarsonScannerState(
            tail=bounded_tail(
                self.tail, span_size(device.led_count, self.start, self.end)
            )
        )

    def render(self, device: Device, state: LarsonScannerState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        end = resolve_end(device.led_count, self.end)
        center = self.start + state.position
        color = wheel_color(state.position) if self.rainbow else self.color
        fade = 256 // state.tail
        for i in range(state.tail):
            scaled = scale_color(color, max(0, 255 - fade * i))
            for index in (center - i, center + i):
                if self.start <= index <= end:
                    frame[index] = scaled
        if self.start + state.position >= end:
            state.direction = -state.direction
        elif state.position <= 0:
            state.direction = -state.direction
        state.position += state.direction * self.step
        state.frame += 1
        return frame
