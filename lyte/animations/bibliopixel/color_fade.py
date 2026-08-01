from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, State
from ..util import (
    RGB,
    resolve_end,
    scale_color,
    validate_palette,
    validate_span,
    validate_start,
)


class ColorFadeState(State):
    levels: list[int]
    position: int = 0


class ColorFade(Animation[ColorFadeState]):
    colors: tuple[RGB, ...] = ((255, 0, 0),)
    level_step: int = 5
    start: int = 0
    end: int | None = None

    @model_validator(mode="after")
    def validate_color_fade(self) -> ColorFade:
        validate_palette(self.colors)
        if self.level_step < 1:
            raise ValueError("level_step must be at least 1")
        validate_start(self.start)
        return self

    def initial_state(self, device: Device) -> ColorFadeState:
        validate_span(
            device.led_count, self.start, resolve_end(device.led_count, self.end)
        )
        levels = list(range(30, 256, self.level_step))
        return ColorFadeState(levels=levels + list(reversed(levels[:-1])))

    def render(self, device: Device, state: ColorFadeState) -> NDArray[np.uint8]:
        color_index, level_index = divmod(state.position, len(state.levels))
        color = scale_color(
            self.colors[color_index % len(self.colors)], state.levels[level_index]
        )
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        frame[self.start : resolve_end(device.led_count, self.end) + 1] = color
        state.position += 1
        state.frame += 1
        return frame
