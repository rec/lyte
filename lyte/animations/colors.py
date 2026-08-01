from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

RGB = tuple[int, int, int]
DEFAULT_PATTERN: tuple[RGB, ...] = ((255, 0, 0), (0, 255, 0), (0, 0, 255))


def scale_color(color: RGB, level: int | float) -> RGB:
    level = max(0, min(255, round(level)))
    return (
        round(color[0] * level / 255),
        round(color[1] * level / 255),
        round(color[2] * level / 255),
    )


def blend_color(frame: NDArray[np.uint8], index: int, color: RGB) -> None:
    if 0 <= index < len(frame):
        frame[index] = ((frame[index].astype(np.uint16) + np.array(color)) // 2).astype(
            np.uint8
        )


def wheel_color(position: int | float) -> RGB:
    position = round(position) % 256
    if position < 85:
        return 255 - position * 3, position * 3, 0
    if position < 170:
        position -= 85
        return 0, 255 - position * 3, position * 3
    position -= 170
    return position * 3, 0, 255 - position * 3


def wave_color(color: RGB, value: float) -> RGB:
    if value >= 0:
        level = 1 - value
        return (
            round(255 - (255 - color[0]) * level),
            round(255 - (255 - color[1]) * level),
            round(255 - (255 - color[2]) * level),
        )
    level = value + 1
    return (
        round(color[0] * level),
        round(color[1] * level),
        round(color[2] * level),
    )
