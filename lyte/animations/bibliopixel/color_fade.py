from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, State, float_color_from_rgb
from .. import validators
from ..colors import RGB, scale_color


class ColorFadeState(State):
    levels: list[int]
    position: int = 0


class ColorFade(Animation[ColorFadeState]):
    colors: tuple[RGB, ...] = ((255, 0, 0),)
    level_step: int = 5
    start: int = 0
    end: int | None = None

    @model_validator(mode='after')
    def validate_color_fade(self) -> ColorFade:
        validators.validate_palette(self.colors)
        if self.level_step < 1:
            raise ValueError('level_step must be at least 1')
        validators.validate_start(self.start)
        return self

    def initial_state(self, device: Device) -> ColorFadeState:
        validators.validate_span(
            device.led_count,
            self.start,
            validators.resolve_end(device.led_count, self.end),
        )
        levels = list(range(30, 256, self.level_step))
        return ColorFadeState(levels=levels + list(reversed(levels[:-1])))

    def render(self, device: Device, state: ColorFadeState) -> NDArray[np.float32]:
        color_index, level_index = divmod(state.position, len(state.levels))
        color = scale_color(
            self.colors[color_index % len(self.colors)], state.levels[level_index]
        )
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        frame[self.start : validators.resolve_end(device.led_count, self.end) + 1] = (
            float_color_from_rgb(color)
        )
        state.position += 1
        state.frame += 1
        return frame
