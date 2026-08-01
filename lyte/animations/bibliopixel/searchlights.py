from __future__ import annotations

import random

import numpy as np
from numpy.typing import NDArray
from pydantic import model_validator

from ...animation import Animation, Device, State
from ..util import (
    RGB,
    blend_color,
    bounded_tail,
    resolve_end,
    scale_color,
    span_size,
    validate_palette,
    validate_span,
    validate_start,
)

SEARCHLIGHT_COLORS: tuple[RGB, ...] = (
    (60, 179, 113),
    (147, 112, 219),
    (199, 21, 133),
)


class SearchlightsState(State):
    directions: list[int]
    random: random.Random
    steps: list[int]
    tail: int = 1


class Searchlights(Animation[SearchlightsState]):
    colors: tuple[RGB, ...] = SEARCHLIGHT_COLORS
    tail: int = 5
    start: int = 0
    end: int | None = None
    seed: int | None = None

    @model_validator(mode="after")
    def validate_searchlights(self) -> Searchlights:
        validate_palette(self.colors)
        if len(self.colors) < 3:
            raise ValueError("colors must contain at least three colors")
        if self.tail < 0:
            raise ValueError("tail must not be negative")
        validate_start(self.start)
        return self

    def initial_state(self, device: Device) -> SearchlightsState:
        validate_span(
            device.led_count, self.start, resolve_end(device.led_count, self.end)
        )
        return SearchlightsState(
            directions=[1, 1, 1],
            random=random.Random(self.seed),
            steps=[1, 1, 1],
            tail=bounded_tail(
                self.tail, span_size(device.led_count, self.start, self.end)
            ),
        )

    def render(self, device: Device, state: SearchlightsState) -> NDArray[np.uint8]:
        frame = np.zeros((device.led_count, 3), dtype=np.uint8)
        end = resolve_end(device.led_count, self.end)
        fade = 256 / state.tail
        for i in range(3):
            position = self.start + state.steps[i]
            color = self.colors[i]
            blend_color(frame, position, color)
            for j in range(1, state.tail):
                scaled = scale_color(color, round(255 - fade * j))
                blend_color(frame, position - j, scaled)
                blend_color(frame, position + j, scaled)
            if position >= end:
                state.directions[i] = -1
            elif position <= self.start:
                state.directions[i] = 1
            if state.random.random() > i * 0.05:
                state.steps[i] += state.directions[i]
        state.frame += 1
        return frame
