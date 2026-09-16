"""Orthographic framing shared by previews and movie exports."""

from typing import Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field


class SpatialView(BaseModel, frozen=True):
    plane: Literal['xy', 'xz', 'yz'] = 'xy'
    zoom: float = Field(default=1, gt=0, allow_inf_nan=False)
    led_size: float = Field(default=1, gt=0, allow_inf_nan=False)
    background: str = Field(default='#050506', pattern=r'^#[0-9a-fA-F]{6}$')


def projected_points(
    positions: list[list[float]], width: int, height: int, view: SpatialView
) -> NDArray[np.float64]:
    axes = {'xy': [0, 1], 'xz': [0, 2], 'yz': [1, 2]}[view.plane]
    padded = np.array([p + [0.0] * (3 - len(p)) for p in positions])
    points = padded[:, axes]
    minimum = points.min(axis=0)
    span = points.max(axis=0) - minimum
    pad = max(24, min(width, height) * 0.08)
    scale = (
        float(np.min((np.array([width, height]) - 2 * pad) / np.where(span, span, 1)))
        * view.zoom
    )
    offset = (np.array([width, height]) - span * scale) / 2
    return offset + (points - minimum) * scale
