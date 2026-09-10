from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from ..animation import float_color_from_rgb
from .colors import RGB
from .validators import validate_rgb


def validate_palette(palette: Sequence[Sequence[int]]) -> None:
    if not palette:
        raise ValueError('palette must not be empty')
    for color in palette:
        validate_rgb(color)


def palette_array(palette: Sequence[Sequence[int]]) -> NDArray[np.float32]:
    return np.array([float_color_from_rgb(c) for c in palette], dtype=np.float32)


def map_palette(
    values: NDArray[np.float32],
    palette: Sequence[Sequence[int]],
    cyclic: bool = False,
) -> NDArray[np.float32]:
    colors = palette_array(palette)
    if len(colors) == 1:
        return np.ascontiguousarray(np.clip(values, 0, 1)[:, None] * colors[0])
    if cyclic:
        scaled = np.mod(values, len(colors))
        lower = np.floor(scaled).astype(np.intp)
        upper = (lower + 1) % len(colors)
        fraction = scaled - lower
    else:
        scaled = np.clip(values, 0, 1) * (len(colors) - 1)
        lower = np.floor(scaled).astype(np.intp)
        upper = np.minimum(lower + 1, len(colors) - 1)
        fraction = scaled - lower
    frame = colors[lower] * (1 - fraction[:, None])
    frame += colors[upper] * fraction[:, None]
    return np.ascontiguousarray(np.clip(frame, 0, 1).astype(np.float32))


def laplacian(
    values: NDArray[np.float32], boundary_mode: Literal['bounded', 'ring']
) -> NDArray[np.float32]:
    left = np.roll(values, 1)
    right = np.roll(values, -1)
    if boundary_mode == 'bounded':
        left[0] = values[0]
        right[-1] = values[-1]
    return left + right - 2 * values


def packet_direction(
    direction: Literal['forward', 'reverse', 'both'], generator: random.Random
) -> int:
    if direction == 'forward':
        return 1
    if direction == 'reverse':
        return -1
    return generator.choice((-1, 1))


FIRE_PALETTE: tuple[RGB, ...] = (
    (0, 0, 0),
    (120, 0, 0),
    (255, 50, 0),
    (255, 190, 20),
    (255, 255, 220),
)

AURORA_PALETTE: tuple[RGB, ...] = (
    (20, 220, 120),
    (30, 100, 255),
    (180, 40, 255),
    (10, 255, 210),
)

OCEAN_PALETTE: tuple[RGB, ...] = (
    (0, 5, 20),
    (0, 50, 120),
    (0, 170, 210),
    (180, 255, 255),
)

INTERFERENCE_PALETTE: tuple[RGB, ...] = (
    (5, 0, 20),
    (200, 20, 120),
    (30, 220, 255),
)

CONVEYOR_PALETTE: tuple[RGB, ...] = (
    (255, 0, 80),
    (255, 180, 0),
    (0, 220, 140),
    (30, 80, 255),
)

CONFETTI_PALETTE: tuple[RGB, ...] = (
    (255, 40, 80),
    (255, 220, 40),
    (30, 220, 180),
    (80, 100, 255),
)

PARTICLE_PALETTE: tuple[RGB, ...] = (
    (255, 50, 30),
    (255, 220, 40),
    (30, 220, 180),
    (80, 100, 255),
    (220, 50, 255),
)

RIPPLE_PALETTE: tuple[RGB, ...] = (
    (40, 120, 255),
    (20, 255, 180),
    (220, 80, 255),
)

CELLULAR_PALETTE: tuple[RGB, ...] = (
    (0, 0, 0),
    (20, 40, 120),
    (40, 220, 180),
    (255, 240, 120),
)

REACTION_PALETTE: tuple[RGB, ...] = (
    (5, 0, 20),
    (40, 20, 130),
    (20, 190, 190),
    (240, 230, 120),
)

PACKET_PALETTE: tuple[RGB, ...] = (
    (50, 220, 255),
    (255, 70, 130),
    (255, 210, 50),
)
