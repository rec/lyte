from __future__ import annotations

import random
from collections.abc import Sequence
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray
from ufor import effects

from ... import animation
from ...animation import Family
from .. import validators
from ..colors import RGB, scale_color

SEARCHLIGHT_COLORS: tuple[RGB, ...] = (
    (60, 179, 113),
    (147, 112, 219),
    (199, 21, 133),
)


class SearchlightsState(animation.State):
    directions: list[int]
    random: random.Random
    steps: list[int]
    tail: int = 1


class Searchlights(effects.Searchlights, animation.Animation[SearchlightsState]):
    family: ClassVar[Family] = Family.EVENTS

    def initial_state(self, device: animation.Device) -> SearchlightsState:
        validators.validate_span(
            device.led_count,
            self.start,
            validators.resolve_end(device.led_count, self.end),
        )
        return SearchlightsState(
            directions=[1, 1, 1],
            random=random.Random(self.seed),
            steps=[1, 1, 1],
            tail=validators.bounded_tail(
                self.tail, validators.span_size(device.led_count, self.start, self.end)
            ),
        )

    def render(
        self, device: animation.Device, state: SearchlightsState
    ) -> NDArray[np.float32]:
        frame = np.zeros((device.led_count, 3), dtype=np.float32)
        end = validators.resolve_end(device.led_count, self.end)
        fade = 256 / state.tail
        for i in range(3):
            position = self.start + state.steps[i]
            color = self.colors[i]
            blend_float_color(frame, position, color)
            for j in range(1, state.tail):
                scaled = scale_color(color, round(255 - fade * j))
                blend_float_color(frame, position - j, scaled)
                blend_float_color(frame, position + j, scaled)
            if position >= end:
                state.directions[i] = -1
            elif position <= self.start:
                state.directions[i] = 1
            if state.random.random() > i * 0.05:
                state.steps[i] += state.directions[i]
        state.frame += 1
        return frame


def blend_float_color(
    frame: NDArray[np.float32], index: int, color: Sequence[int]
) -> None:
    if 0 <= index < len(frame):
        byte_frame = animation.byte_light_frame_from_float(frame[index : index + 1])
        blended = ((byte_frame[0].astype(np.uint16) + np.array(color)) // 2).astype(
            np.uint8
        )
        frame[index] = animation.float_color_from_rgb(
            (int(blended[0]), int(blended[1]), int(blended[2]))
        )
